"""
Назначение:
    Централизованные projection-функции: AppConfig → domain policy inputs
    и component-local infra configs.

Граница ответственности:
    - Owns: преобразование AppConfig секций в типы domain/infra слоёв.
    - Does NOT: бизнес-логику, IO, DI-wiring, загрузку конфигурации.
    - Вызывается: DI-контейнером и command handlers (НЕ domain-кодом).

Инварианты:
    - Projection разрешён только при смене архитектурной роли:
      config-layer model → domain policy input / infra component config.
    - Каждая функция — чистая функция: только маппинг полей, без IO.
    - Дублирующие _rollout_settings() в command handlers заменяются этими функциями.

Примечания по именам:
    - VaultRolloutConfig.error_rate_threshold_pct
        → VaultRolloutThresholds.vault_error_rate_threshold_pct
      Префикс vault_ убран в config-модели как несогласованный (legacy).
      Projection восстанавливает доменное имя.

    - to_identity_db_config() не включает schema_retry_count:
      identity DB не использует schema migration с retry.

    - resolve_batch_size / resolve_flush_interval_ms живут в ResolverConfig
      и доставляются через DI-wiring напрямую (нет domain-порта IResolveBatchSettings).

Связанные ADR:
    - CONFIG-DEC-003: settings taxonomy and boundary adapters
"""
from __future__ import annotations

from connector.config.models import AppConfig
from connector.domain.secrets.policy.rollout_metrics import VaultRolloutThresholds
from connector.domain.secrets.policy.rollout_policy import VaultRolloutPolicySettings
from connector.domain.secrets.policy.rotation_policy import VaultRotationInterval
from connector.domain.transform.matcher.match_deps import MatchBatchSettings
from connector.domain.transform.resolver.resolve_deps import ResolverSettings
from connector.infra.sqlite.config import SqliteDbConfig
from connector.usecases.operations.vault_management_settings import VaultManagementSettings


def to_resolver_settings(config: AppConfig) -> ResolverSettings:
    """AppConfig.resolver → domain ResolverSettings.

    Все 6 pending-полей маппируются 1:1.
    resolve_batch_size / resolve_flush_interval_ms остаются в AppConfig.resolver
    и доставляются через DI-wiring (не входят в domain ResolverSettings).
    """
    r = config.resolver
    return ResolverSettings(
        pending_ttl_seconds=r.pending_ttl_seconds,
        pending_max_attempts=r.pending_max_attempts,
        pending_sweep_interval_seconds=r.pending_sweep_interval_seconds,
        pending_on_expire=r.pending_on_expire,
        pending_allow_partial=r.pending_allow_partial,
        pending_retention_days=r.pending_retention_days,
    )


def to_vault_rollout_policy_settings(config: AppConfig) -> VaultRolloutPolicySettings:
    """AppConfig.vault_rollout → domain VaultRolloutPolicySettings.

    canary_datasets: VaultRolloutConfig хранит tuple[str, ...] —
    Pydantic v2 автоматически coerce-ит YAML-list → tuple при загрузке.
    Передаётся без дополнительной конвертации.
    mode включает "staging_dry_run", поддерживаемый evaluate_vault_rollout().
    """
    vr = config.vault_rollout
    return VaultRolloutPolicySettings(
        mode=vr.mode,
        canary_percent=vr.canary_percent,
        canary_datasets=vr.canary_datasets,
        canary_seed=vr.canary_seed,
    )


def to_vault_rollout_thresholds(config: AppConfig) -> VaultRolloutThresholds:
    """AppConfig.vault_rollout → domain VaultRolloutThresholds.

    Переименование поля:
      VaultRolloutConfig.error_rate_threshold_pct
        → VaultRolloutThresholds.vault_error_rate_threshold_pct
    Префикс vault_ в доменной модели унаследован до унификации config-слоя.
    В VaultRolloutConfig он убран как несогласованный.

    Production defaults живут только в VaultRolloutConfig (config-layer).
    Доменные дефолты VaultRolloutThresholds() shadowed этой проекцией.
    """
    vr = config.vault_rollout
    return VaultRolloutThresholds(
        row_failure_rate_threshold_pct=vr.row_failure_rate_threshold_pct,
        vault_error_rate_threshold_pct=vr.error_rate_threshold_pct,  # rename: vault_ removed
        latency_regression_threshold_pct=vr.latency_regression_threshold_pct,
        busy_timeout_rate_threshold_pct=vr.busy_timeout_rate_threshold_pct,
        schema_changed_rate_threshold_pct=vr.schema_changed_rate_threshold_pct,
    )


def to_match_batch_settings(config: AppConfig) -> MatchBatchSettings:
    """AppConfig.matching_runtime → domain MatchBatchSettings (match side only).

    Только match micro-batching параметры передаются в MatchBatchSettings.
    resolve_batch_size / resolve_flush_interval_ms находятся в AppConfig.resolver
    и доставляются через DI-wiring (нет domain-порта IResolveBatchSettings).
    """
    mr = config.matching_runtime
    return MatchBatchSettings(
        batch_size=mr.match_batch_size,
        flush_interval_ms=mr.match_flush_interval_ms,
    )


def to_vault_db_config(config: AppConfig) -> SqliteDbConfig:
    """AppConfig.sqlite → infra SqliteDbConfig для vault DB.

    per-DB override chain: vault_busy_timeout_ms or global busy_timeout_ms.
    schema_retry_count включён: vault DB использует schema migration с retry.
    Путь к файлу (vault_db_path) используется DI-контейнером отдельно.
    """
    s = config.sqlite
    return SqliteDbConfig(
        transaction_mode=s.vault_transaction_mode,
        busy_timeout_ms=s.vault_busy_timeout_ms or s.busy_timeout_ms,
        journal_mode=s.vault_journal_mode or s.journal_mode,
        synchronous=s.synchronous,
        wal_autocheckpoint=s.wal_autocheckpoint,
        schema_retry_count=s.vault_schema_retry_count,
    )


def to_cache_db_config(config: AppConfig) -> SqliteDbConfig:
    """AppConfig.sqlite → infra SqliteDbConfig для cache DB.

    per-DB override chain: cache_busy_timeout_ms or global busy_timeout_ms.
    schema_retry_count не включён: cache DB не использует schema migration с retry.
    """
    s = config.sqlite
    return SqliteDbConfig(
        transaction_mode=s.cache_transaction_mode,
        busy_timeout_ms=s.cache_busy_timeout_ms or s.busy_timeout_ms,
        journal_mode=s.cache_journal_mode or s.journal_mode,
        synchronous=s.synchronous,
        wal_autocheckpoint=s.wal_autocheckpoint,
    )


def to_identity_db_config(config: AppConfig) -> SqliteDbConfig:
    """AppConfig.sqlite → infra SqliteDbConfig для identity DB.

    Только глобальные дефолты: нет per-DB override полей для identity.
    schema_retry_count не включён намеренно: identity DB не использует
    schema migration с retry (в отличие от vault DB).
    """
    s = config.sqlite
    return SqliteDbConfig(
        busy_timeout_ms=s.busy_timeout_ms,
        journal_mode=s.journal_mode,
        synchronous=s.synchronous,
        wal_autocheckpoint=s.wal_autocheckpoint,
    )


def to_vault_management_settings(config: AppConfig) -> VaultManagementSettings:
    """AppConfig.vault_management → typed settings для operational vault usecases."""
    vm = config.vault_management
    interval_cfg = vm.auto_rotate_interval
    return VaultManagementSettings(
        managed_env_file=vm.managed_env_file,
        require_admin_password_for_manual_ops=vm.require_admin_password_for_manual_ops,
        admin_password_hash_file=vm.admin_password_hash_file,
        admin_password_hash_env_var=vm.admin_password_hash_env_var,
        admin_password_env_var=vm.admin_password_env_var,
        auto_rotate_enabled=vm.auto_rotate_enabled,
        auto_rotate_on_error=vm.auto_rotate_on_error,
        auto_rotate_interval=VaultRotationInterval(
            hours=interval_cfg.hours,
            days=interval_cfg.days,
            months=interval_cfg.months,
            years=interval_cfg.years,
        ),
    )


__all__ = [
    "to_resolver_settings",
    "to_vault_rollout_policy_settings",
    "to_vault_rollout_thresholds",
    "to_match_batch_settings",
    "to_vault_db_config",
    "to_cache_db_config",
    "to_identity_db_config",
    "to_vault_management_settings",
]
