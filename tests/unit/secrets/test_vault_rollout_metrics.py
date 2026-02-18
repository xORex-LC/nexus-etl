from __future__ import annotations

from types import SimpleNamespace

from connector.domain.secrets.vault_rollout_metrics import (
    VaultRolloutThresholds,
    build_vault_operational_metrics,
)


def _summary(*, created: int, updated: int, failed: int, items_total: int, error_stats: dict[str, int]):
    return SimpleNamespace(
        created=created,
        updated=updated,
        failed=failed,
        items_total=items_total,
        error_stats=error_stats,
    )


def test_operational_metrics_marks_rollback_on_threshold_breach() -> None:
    metrics = build_vault_operational_metrics(
        summary=_summary(
            created=8,
            updated=0,
            failed=2,
            items_total=10,
            error_stats={"SECRET_REQUIRED": 2},
        ),
        startup_guard_passed=True,
        thresholds=VaultRolloutThresholds(
            row_failure_rate_threshold_pct=10.0,
            vault_error_rate_threshold_pct=10.0,
            latency_regression_threshold_pct=15.0,
            busy_timeout_rate_threshold_pct=0.0,
            schema_changed_rate_threshold_pct=0.0,
        ),
    )
    assert metrics["metrics"]["row_failure_rate_pct"] == 20.0
    assert metrics["metrics"]["vault_error_rate_pct"] == 20.0
    assert metrics["rollback"]["required"] is True
    assert metrics["rollback"]["triggers"]["row_failure_rate"] is True
    assert metrics["rollback"]["triggers"]["vault_error_rate"] is True


def test_operational_metrics_respects_startup_guard_trigger() -> None:
    metrics = build_vault_operational_metrics(
        summary=_summary(
            created=0,
            updated=0,
            failed=0,
            items_total=0,
            error_stats={},
        ),
        startup_guard_passed=False,
        thresholds=VaultRolloutThresholds(),
    )
    assert metrics["metrics"]["startup_success_rate_pct"] == 0.0
    assert metrics["rollback"]["required"] is True
    assert metrics["rollback"]["triggers"]["startup_error"] is True
