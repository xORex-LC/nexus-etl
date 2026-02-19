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


_SECRET_ERROR_CODES = frozenset(
    {
        "SECRET_REQUIRED",
        "SECRET_READ_ERROR",
        "SECRET_DECRYPTION_ERROR",
        "SECRET_INTEGRITY_ERROR",
    }
)


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
    total_items = max(0, int(summary.items_total))
    successful_items = max(0, int(summary.created) + int(summary.updated))
    failed_items = max(0, int(summary.failed))
    error_stats = dict(summary.error_stats or {})

    vault_error_count = sum(int(error_stats.get(code, 0)) for code in _SECRET_ERROR_CODES)
    secret_read_failure_count = vault_error_count
    secret_read_attempts = successful_items + secret_read_failure_count

    row_failure_rate_pct = _pct(failed_items, total_items)
    vault_error_rate_pct = _pct(vault_error_count, total_items)
    secret_read_success_rate_pct = _pct(successful_items, secret_read_attempts)
    startup_success_rate_pct = 100.0 if startup_guard_passed else 0.0
    busy_timeout_rate_pct = _pct(busy_timeout_count, total_items)
    schema_changed_rate_pct = _pct(schema_changed_count, total_items)

    trigger_startup = not startup_guard_passed
    trigger_row_failure = row_failure_rate_pct > thresholds.row_failure_rate_threshold_pct
    trigger_vault_error = vault_error_rate_pct > thresholds.vault_error_rate_threshold_pct
    trigger_latency = (latency_regression_pct or 0.0) > thresholds.latency_regression_threshold_pct
    trigger_throughput = (throughput_regression_pct or 0.0) > thresholds.latency_regression_threshold_pct
    trigger_busy_timeout = busy_timeout_rate_pct > thresholds.busy_timeout_rate_threshold_pct
    trigger_schema_changed = schema_changed_rate_pct > thresholds.schema_changed_rate_threshold_pct

    rollback_required = any(
        (
            trigger_startup,
            trigger_row_failure,
            trigger_vault_error,
            trigger_latency,
            trigger_throughput,
            trigger_busy_timeout,
            trigger_schema_changed,
        )
    )

    return {
        "metrics": {
            "startup_success_rate_pct": startup_success_rate_pct,
            "secret_read_success_rate_pct": secret_read_success_rate_pct,
            "row_failure_rate_pct": row_failure_rate_pct,
            "vault_error_rate_pct": vault_error_rate_pct,
            "busy_timeout_rate_pct": busy_timeout_rate_pct,
            "schema_changed_rate_pct": schema_changed_rate_pct,
            "vault_error_counts": {
                "SECRET_REQUIRED": int(error_stats.get("SECRET_REQUIRED", 0)),
                "SECRET_READ_ERROR": int(error_stats.get("SECRET_READ_ERROR", 0)),
                "SECRET_DECRYPTION_ERROR": int(error_stats.get("SECRET_DECRYPTION_ERROR", 0)),
                "SECRET_INTEGRITY_ERROR": int(error_stats.get("SECRET_INTEGRITY_ERROR", 0)),
            },
            "latency_regression_pct": latency_regression_pct,
            "throughput_regression_pct": throughput_regression_pct,
            "total_items": total_items,
            "successful_items": successful_items,
            "failed_items": failed_items,
        },
        "thresholds": {
            "row_failure_rate_threshold_pct": thresholds.row_failure_rate_threshold_pct,
            "vault_error_rate_threshold_pct": thresholds.vault_error_rate_threshold_pct,
            "latency_regression_threshold_pct": thresholds.latency_regression_threshold_pct,
            "busy_timeout_rate_threshold_pct": thresholds.busy_timeout_rate_threshold_pct,
            "schema_changed_rate_threshold_pct": thresholds.schema_changed_rate_threshold_pct,
        },
        "rollback": {
            "required": rollback_required,
            "triggers": {
                "startup_error": trigger_startup,
                "row_failure_rate": trigger_row_failure,
                "vault_error_rate": trigger_vault_error,
                "latency_regression": trigger_latency,
                "throughput_regression": trigger_throughput,
                "busy_timeout_rate": trigger_busy_timeout,
                "schema_changed_rate": trigger_schema_changed,
            },
        },
    }


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((float(numerator) / float(denominator)) * 100.0, 3)


__all__ = ["VaultRolloutThresholds", "build_vault_operational_metrics"]
