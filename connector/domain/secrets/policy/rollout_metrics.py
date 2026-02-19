"""Назначение:
    Вычислить operational метрики rollout и rollback-сигналы по apply-счётчикам.

Граница ответственности:
    Модуль чистый: не читает окружение, не выполняет IO и не работает с report-артефактами.
    На вход получает уже собранные счётчики с границы command/use-case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


class ApplySummaryLike(Protocol):
    """Назначение:
        Минимальный контракт счётчиков, требуемый от apply summary объекта.
    """

    created: int
    updated: int
    failed: int
    items_total: int
    error_stats: Mapping[str, int]


_SECRET_ERROR_CODE_ORDER = (
    "SECRET_REQUIRED",
    "SECRET_READ_ERROR",
    "SECRET_DECRYPTION_ERROR",
    "SECRET_INTEGRITY_ERROR",
)
_SECRET_ERROR_CODES = frozenset(_SECRET_ERROR_CODE_ORDER)


@dataclass(frozen=True)
class VaultRolloutThresholds:
    """Назначение:
        Операторские пороги, по которым формируется рекомендация rollback.
    """

    row_failure_rate_threshold_pct: float = 5.0
    vault_error_rate_threshold_pct: float = 5.0
    latency_regression_threshold_pct: float = 15.0
    busy_timeout_rate_threshold_pct: float = 0.0
    schema_changed_rate_threshold_pct: float = 0.0


@dataclass(frozen=True)
class _OperationalMetricValues:
    startup_success_rate_pct: float
    secret_read_success_rate_pct: float
    row_failure_rate_pct: float
    vault_error_rate_pct: float
    busy_timeout_rate_pct: float
    schema_changed_rate_pct: float
    vault_error_counts: dict[str, int]
    latency_regression_pct: float | None
    throughput_regression_pct: float | None
    total_items: int
    successful_items: int
    failed_items: int


def build_vault_operational_metrics(
    *,
    summary: ApplySummaryLike,
    startup_guard_passed: bool,
    thresholds: VaultRolloutThresholds,
    latency_regression_pct: float | None = None,
    throughput_regression_pct: float | None = None,
    busy_timeout_count: int = 0,
    schema_changed_count: int = 0,
) -> dict[str, object]:
    """Назначение:
        Собрать payload operational метрик и rollback-trigger hints для apply report.

    Контракт:
        - Использует только счётчики `ApplySummary` и опциональные benchmark-дельты.
        - Возвращает сериализуемый `dict`, пригодный для report context.
        - При отсутствии benchmark-дельт regression-триггеры по умолчанию не активируются.
    """
    metric_values = _compute_metric_values(
        summary=summary,
        startup_guard_passed=startup_guard_passed,
        latency_regression_pct=latency_regression_pct,
        throughput_regression_pct=throughput_regression_pct,
        busy_timeout_count=busy_timeout_count,
        schema_changed_count=schema_changed_count,
    )
    triggers = _compute_rollback_triggers(
        startup_guard_passed=startup_guard_passed,
        thresholds=thresholds,
        metric_values=metric_values,
    )
    return _build_payload(
        metric_values=metric_values,
        thresholds=thresholds,
        triggers=triggers,
    )


def _compute_metric_values(
    *,
    summary: ApplySummaryLike,
    startup_guard_passed: bool,
    latency_regression_pct: float | None,
    throughput_regression_pct: float | None,
    busy_timeout_count: int,
    schema_changed_count: int,
) -> _OperationalMetricValues:
    total_items = max(0, int(summary.items_total))
    successful_items = max(0, int(summary.created) + int(summary.updated))
    failed_items = max(0, int(summary.failed))
    error_stats = dict(summary.error_stats or {})

    vault_error_counts = _build_vault_error_counts(error_stats=error_stats)
    vault_error_count = sum(vault_error_counts.values())
    secret_read_failure_count = vault_error_count
    secret_read_attempts = successful_items + secret_read_failure_count

    return _OperationalMetricValues(
        startup_success_rate_pct=100.0 if startup_guard_passed else 0.0,
        secret_read_success_rate_pct=_pct(successful_items, secret_read_attempts),
        row_failure_rate_pct=_pct(failed_items, total_items),
        vault_error_rate_pct=_pct(vault_error_count, total_items),
        busy_timeout_rate_pct=_pct(busy_timeout_count, total_items),
        schema_changed_rate_pct=_pct(schema_changed_count, total_items),
        vault_error_counts=vault_error_counts,
        latency_regression_pct=latency_regression_pct,
        throughput_regression_pct=throughput_regression_pct,
        total_items=total_items,
        successful_items=successful_items,
        failed_items=failed_items,
    )


def _compute_rollback_triggers(
    *,
    startup_guard_passed: bool,
    thresholds: VaultRolloutThresholds,
    metric_values: _OperationalMetricValues,
) -> dict[str, bool]:
    return {
        "startup_error": not startup_guard_passed,
        "row_failure_rate": metric_values.row_failure_rate_pct > thresholds.row_failure_rate_threshold_pct,
        "vault_error_rate": metric_values.vault_error_rate_pct > thresholds.vault_error_rate_threshold_pct,
        "latency_regression": (metric_values.latency_regression_pct or 0.0)
        > thresholds.latency_regression_threshold_pct,
        "throughput_regression": (metric_values.throughput_regression_pct or 0.0)
        > thresholds.latency_regression_threshold_pct,
        "busy_timeout_rate": metric_values.busy_timeout_rate_pct > thresholds.busy_timeout_rate_threshold_pct,
        "schema_changed_rate": metric_values.schema_changed_rate_pct > thresholds.schema_changed_rate_threshold_pct,
    }


def _build_payload(
    *,
    metric_values: _OperationalMetricValues,
    thresholds: VaultRolloutThresholds,
    triggers: dict[str, bool],
) -> dict[str, object]:
    return {
        "metrics": {
            "startup_success_rate_pct": metric_values.startup_success_rate_pct,
            "secret_read_success_rate_pct": metric_values.secret_read_success_rate_pct,
            "row_failure_rate_pct": metric_values.row_failure_rate_pct,
            "vault_error_rate_pct": metric_values.vault_error_rate_pct,
            "busy_timeout_rate_pct": metric_values.busy_timeout_rate_pct,
            "schema_changed_rate_pct": metric_values.schema_changed_rate_pct,
            "vault_error_counts": metric_values.vault_error_counts,
            "latency_regression_pct": metric_values.latency_regression_pct,
            "throughput_regression_pct": metric_values.throughput_regression_pct,
            "total_items": metric_values.total_items,
            "successful_items": metric_values.successful_items,
            "failed_items": metric_values.failed_items,
        },
        "thresholds": {
            "row_failure_rate_threshold_pct": thresholds.row_failure_rate_threshold_pct,
            "vault_error_rate_threshold_pct": thresholds.vault_error_rate_threshold_pct,
            "latency_regression_threshold_pct": thresholds.latency_regression_threshold_pct,
            "busy_timeout_rate_threshold_pct": thresholds.busy_timeout_rate_threshold_pct,
            "schema_changed_rate_threshold_pct": thresholds.schema_changed_rate_threshold_pct,
        },
        "rollback": {
            "required": any(triggers.values()),
            "triggers": triggers,
        },
    }


def _build_vault_error_counts(*, error_stats: Mapping[str, int]) -> dict[str, int]:
    return {code: int(error_stats.get(code, 0)) for code in _SECRET_ERROR_CODE_ORDER}


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((float(numerator) / float(denominator)) * 100.0, 3)


__all__ = ["VaultRolloutThresholds", "build_vault_operational_metrics"]
