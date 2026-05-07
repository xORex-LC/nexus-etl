"""
Unit-тесты для централизованных projection-функций из connector/config/projections.py.

Проверяют: корректность маппинга полей, rename error_rate_threshold_pct,
override chain (per-DB vs global), намеренное отсутствие schema_retry_count
в identity DB config, отсутствие resolve_batch полей в MatchBatchSettings.

Каждый тест — чистая функция: создаёт AppConfig напрямую (без IO).
"""
from __future__ import annotations

from connector.config.models import AppConfig, SqliteConfig
from connector.config.projections import (
    to_cache_db_config,
    to_dataset_registry_path,
    to_identity_db_config,
    to_match_batch_settings,
    to_operational_paths,
    to_resolver_settings,
    to_vault_management_settings,
    to_vault_db_config,
    to_vault_rollout_policy_settings,
    to_vault_rollout_thresholds,
)
from connector.domain.secrets.policy.rollout_metrics import VaultRolloutThresholds
from connector.domain.secrets.policy.rollout_policy import VaultRolloutPolicySettings
from connector.domain.transform.matcher.match_deps import MatchBatchSettings
from connector.domain.transform.resolver.resolve_deps import ResolverSettings
from connector.infra.sqlite.config import SqliteDbConfig
from connector.usecases.operations.vault_management_settings import VaultManagementSettings


# ──────────────────────────────────────────────────────────────────────────────
# to_resolver_settings
# ──────────────────────────────────────────────────────────────────────────────


def test_to_resolver_settings_maps_all_fields() -> None:
    """Все 6 pending-полей ResolverConfig → ResolverSettings передаются корректно."""
    cfg = AppConfig.model_validate({
        "resolver": {
            "pending_ttl_seconds": 200,
            "pending_max_attempts": 7,
            "pending_sweep_interval_seconds": 90,
            "pending_on_expire": "skip",
            "pending_allow_partial": True,
            "pending_retention_days": 30,
        }
    })

    result = to_resolver_settings(cfg)

    assert isinstance(result, ResolverSettings)
    assert result.pending_ttl_seconds == 200
    assert result.pending_max_attempts == 7
    assert result.pending_sweep_interval_seconds == 90
    assert result.pending_on_expire == "skip"
    assert result.pending_allow_partial is True
    assert result.pending_retention_days == 30


def test_to_resolver_settings_default_values_match_config_defaults() -> None:
    """ResolverConfig() → ResolverSettings: дефолты совпадают с Settings (regression guard)."""
    cfg = AppConfig()

    result = to_resolver_settings(cfg)

    assert result.pending_max_attempts == 5
    assert result.pending_ttl_seconds == 120
    assert result.pending_on_expire == "error"
    assert result.pending_allow_partial is False
    assert result.pending_retention_days == 14


# ──────────────────────────────────────────────────────────────────────────────
# to_vault_rollout_policy_settings
# ──────────────────────────────────────────────────────────────────────────────


def test_to_vault_rollout_policy_settings_mode_literal() -> None:
    """mode='staging_dry_run' → VaultRolloutPolicySettings.mode='staging_dry_run'."""
    cfg = AppConfig.model_validate({"vault_rollout": {"mode": "staging_dry_run"}})

    result = to_vault_rollout_policy_settings(cfg)

    assert isinstance(result, VaultRolloutPolicySettings)
    assert result.mode == "staging_dry_run"


def test_to_vault_rollout_policy_settings_canary_datasets_tuple() -> None:
    """canary_datasets=('ds1', 'ds2') → VaultRolloutPolicySettings.canary_datasets == ('ds1', 'ds2')."""
    cfg = AppConfig.model_validate({"vault_rollout": {"canary_datasets": ["ds1", "ds2"]}})

    result = to_vault_rollout_policy_settings(cfg)

    assert isinstance(result.canary_datasets, tuple)
    assert result.canary_datasets == ("ds1", "ds2")


# ──────────────────────────────────────────────────────────────────────────────
# to_vault_rollout_thresholds
# ──────────────────────────────────────────────────────────────────────────────


def test_to_vault_rollout_thresholds_renames_error_rate() -> None:
    """VaultRolloutConfig.error_rate_threshold_pct → VaultRolloutThresholds.vault_error_rate_threshold_pct."""
    cfg = AppConfig.model_validate({"vault_rollout": {"error_rate_threshold_pct": 3.5}})

    result = to_vault_rollout_thresholds(cfg)

    assert isinstance(result, VaultRolloutThresholds)
    assert result.vault_error_rate_threshold_pct == 3.5


def test_to_vault_rollout_thresholds_default_values() -> None:
    """Дефолты из VaultRolloutConfig(): row=5.0, latency=15.0, busy=0.0, schema=0.0 (regression guard)."""
    cfg = AppConfig()

    result = to_vault_rollout_thresholds(cfg)

    assert result.row_failure_rate_threshold_pct == 5.0
    assert result.vault_error_rate_threshold_pct == 5.0
    assert result.latency_regression_threshold_pct == 15.0
    assert result.busy_timeout_rate_threshold_pct == 0.0
    assert result.schema_changed_rate_threshold_pct == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# to_match_batch_settings
# ──────────────────────────────────────────────────────────────────────────────


def test_to_match_batch_settings_maps_match_fields() -> None:
    """match_batch_size, match_flush_interval_ms → MatchBatchSettings корректно."""
    cfg = AppConfig.model_validate({
        "matching_runtime": {
            "match_batch_size": 250,
            "match_flush_interval_ms": 100,
        }
    })

    result = to_match_batch_settings(cfg)

    assert isinstance(result, MatchBatchSettings)
    assert result.batch_size == 250
    assert result.flush_interval_ms == 100


def test_to_match_batch_settings_no_resolve_fields() -> None:
    """MatchBatchSettings не содержит resolve_batch_size / resolve_flush_interval_ms.

    Resolve batch-параметры живут в AppConfig.resolver и доставляются
    через DI-wiring напрямую (нет domain-порта IResolveBatchSettings).
    """
    cfg = AppConfig()

    result = to_match_batch_settings(cfg)

    assert not hasattr(result, "resolve_batch_size")
    assert not hasattr(result, "resolve_flush_interval_ms")


# ──────────────────────────────────────────────────────────────────────────────
# to_vault_db_config
# ──────────────────────────────────────────────────────────────────────────────


def test_to_vault_db_config_uses_vault_override_when_set() -> None:
    """vault_busy_timeout_ms=1234 → SqliteDbConfig.busy_timeout_ms=1234."""
    cfg = AppConfig(sqlite=SqliteConfig(
        busy_timeout_ms=5000,
        vault_busy_timeout_ms=1234,
    ))

    result = to_vault_db_config(cfg)

    assert isinstance(result, SqliteDbConfig)
    assert result.busy_timeout_ms == 1234


def test_to_vault_db_config_falls_back_to_global() -> None:
    """vault_busy_timeout_ms=None → SqliteDbConfig.busy_timeout_ms = global busy_timeout_ms."""
    cfg = AppConfig(sqlite=SqliteConfig(
        busy_timeout_ms=8000,
        vault_busy_timeout_ms=None,
    ))

    result = to_vault_db_config(cfg)

    assert result.busy_timeout_ms == 8000


def test_to_vault_db_config_includes_schema_retry_count() -> None:
    """vault DB включает schema_retry_count (vault использует schema migration с retry)."""
    cfg = AppConfig(sqlite=SqliteConfig(vault_schema_retry_count=3))

    result = to_vault_db_config(cfg)

    assert result.schema_retry_count == 3


# ──────────────────────────────────────────────────────────────────────────────
# to_cache_db_config
# ──────────────────────────────────────────────────────────────────────────────


def test_to_cache_db_config_deferred_transaction_mode() -> None:
    """Cache DB всегда использует transaction_mode='deferred'."""
    cfg = AppConfig()

    result = to_cache_db_config(cfg)

    assert isinstance(result, SqliteDbConfig)
    assert result.transaction_mode == "deferred"


# ──────────────────────────────────────────────────────────────────────────────
# to_identity_db_config
# ──────────────────────────────────────────────────────────────────────────────


def test_to_identity_db_config_no_schema_retry_field() -> None:
    """to_identity_db_config() возвращает SqliteDbConfig с schema_retry_count=0 (default).

    schema_retry_count не включён намеренно: identity DB не использует
    schema migration с retry. Результат получает дефолт SqliteDbConfig (0).
    """
    cfg = AppConfig(sqlite=SqliteConfig(vault_schema_retry_count=5))

    result = to_identity_db_config(cfg)

    # Projection не передаёт vault_schema_retry_count → SqliteDbConfig default = 0
    assert result.schema_retry_count == 0


def test_to_identity_db_config_uses_global_defaults_only() -> None:
    """Identity DB строится только из глобальных дефолтов (нет per-DB override полей)."""
    cfg = AppConfig(sqlite=SqliteConfig(
        busy_timeout_ms=6000,
        journal_mode="DELETE",
        synchronous="FULL",
        wal_autocheckpoint=2000,
    ))

    result = to_identity_db_config(cfg)

    assert result.busy_timeout_ms == 6000
    assert result.journal_mode == "DELETE"
    assert result.synchronous == "FULL"
    assert result.wal_autocheckpoint == 2000
    # transaction_mode не передаётся явно → SqliteDbConfig default = "deferred"
    assert result.transaction_mode == "deferred"


# ──────────────────────────────────────────────────────────────────────────────
# to_vault_management_settings
# ──────────────────────────────────────────────────────────────────────────────


def test_to_vault_management_settings_maps_fields() -> None:
    cfg = AppConfig.model_validate({
        "runtime": {
            "runtime_root": "/opt/nexus",
        },
        "vault_management": {
            "require_admin_password_for_manual_ops": True,
            "admin_password_hash_file": "./environment/vault-admin.env",
            "admin_password_env_var": "ANKEY_VAULT_ADMIN_PASSWORD",
        }
    })

    result = to_vault_management_settings(cfg)

    assert isinstance(result, VaultManagementSettings)
    assert result.require_admin_password_for_manual_ops is True
    assert result.admin_password_hash_file == "/opt/nexus/environment/vault-admin.env"
    assert result.admin_password_env_var == "ANKEY_VAULT_ADMIN_PASSWORD"


def test_to_vault_management_settings_keeps_absolute_hash_file_path() -> None:
    cfg = AppConfig.model_validate({
        "vault_management": {
            "admin_password_hash_file": "/srv/nexus/environment/vault-admin.env",
        }
    })

    result = to_vault_management_settings(cfg)

    assert result.admin_password_hash_file == "/srv/nexus/environment/vault-admin.env"


def test_to_vault_management_settings_defaults_follow_config_defaults() -> None:
    cfg = AppConfig()

    result = to_vault_management_settings(cfg)

    assert result.require_admin_password_for_manual_ops is True
    assert result.admin_password_hash_file is None
    assert result.admin_password_env_var == "ANKEY_VAULT_ADMIN_PASSWORD"


def test_to_dataset_registry_path_resolves_relative_path_against_runtime_root() -> None:
    cfg = AppConfig.model_validate({
        "runtime": {
            "runtime_root": "/opt/nexus",
        },
        "dataset": {
            "registry_path": "./datasets/employees.registry.yaml",
        },
    })

    result = to_dataset_registry_path(cfg)

    assert result == "/opt/nexus/datasets/employees.registry.yaml"


def test_to_dataset_registry_path_keeps_absolute_path() -> None:
    cfg = AppConfig.model_validate({
        "dataset": {
            "registry_path": "/srv/nexus/datasets/employees.registry.yaml",
        },
    })

    result = to_dataset_registry_path(cfg)

    assert result == "/srv/nexus/datasets/employees.registry.yaml"


def test_to_operational_paths_resolves_relative_dirs_against_runtime_root(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    (runtime_root / "datasets").mkdir(parents=True, exist_ok=True)
    (runtime_root / "datasets" / "registry.yaml").write_text("targets: {}\ndatasets: {}\n", encoding="utf-8")

    cfg = AppConfig.model_validate({
        "runtime": {
            "runtime_root": str(runtime_root),
        },
        "paths": {
            "cache_dir": "var/cache",
            "log_dir": "var/logs",
            "report_dir": "reports",
        },
    })

    result = to_operational_paths(cfg)

    assert result.cache_dir == str((runtime_root / "var/cache").resolve())
    assert result.log_dir == str((runtime_root / "var/logs").resolve())
    assert result.report_dir == str((runtime_root / "reports").resolve())
