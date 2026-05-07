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

from dataclasses import dataclass
from pathlib import Path

from connector.common.runtime_paths import RuntimePathOverrides, detect_runtime_paths
from connector.config.models import AppConfig
from connector.domain.secrets.policy.rollout_metrics import VaultRolloutThresholds
from connector.domain.secrets.policy.rollout_policy import VaultRolloutPolicySettings
from connector.domain.transform.matcher.match_deps import MatchBatchSettings
from connector.domain.transform.resolver.resolve_deps import ResolverSettings
from connector.infra.sqlite.config import SqliteDbConfig
from connector.usecases.operations.vault_management_settings import VaultManagementSettings


@dataclass(frozen=True)
class OperationalPaths:
    cache_dir: str
    log_dir: str
    report_dir: str


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
    """AppConfig.vault_management → typed settings для operational vault usecases.

    Relative `admin_password_hash_file` is resolved against the active runtime root
    so manual vault-management commands do not depend on the current working directory.
    """
    vm = config.vault_management
    admin_password_hash_file = vm.admin_password_hash_file
    if admin_password_hash_file is not None:
        runtime_root = Path(config.runtime.runtime_root).expanduser()
        if not runtime_root.is_absolute():
            runtime_root = (Path.cwd() / runtime_root).resolve()
        hash_file_path = Path(admin_password_hash_file).expanduser()
        if hash_file_path.is_absolute():
            admin_password_hash_file = str(hash_file_path.resolve())
        else:
            admin_password_hash_file = str((runtime_root / hash_file_path).resolve())
    return VaultManagementSettings(
        require_admin_password_for_manual_ops=vm.require_admin_password_for_manual_ops,
        admin_password_hash_file=admin_password_hash_file,
        admin_password_hash_name=vm.admin_password_hash_name,
        admin_password_env_var=vm.admin_password_env_var,
    )


def to_dataset_registry_path(config: AppConfig) -> str | None:
    """Resolve explicit dataset registry override against runtime root.

    The override remains optional. When provided as a relative path in config,
    it is interpreted relative to `runtime.runtime_root` instead of the process
    working directory.
    """
    registry_path = config.dataset.registry_path
    if registry_path is None:
        return None

    runtime_root = Path(config.runtime.runtime_root).expanduser()
    if not runtime_root.is_absolute():
        runtime_root = (Path.cwd() / runtime_root).resolve()

    registry_path_obj = Path(registry_path).expanduser()
    if registry_path_obj.is_absolute():
        return str(registry_path_obj.resolve())
    return str((runtime_root / registry_path_obj).resolve())


def to_operational_paths(config: AppConfig) -> OperationalPaths:
    """Resolve cache/log/report directories against runtime root."""
    runtime_paths = detect_runtime_paths(overrides=to_runtime_path_overrides(config))
    return OperationalPaths(
        cache_dir=str(runtime_paths.cache_root),
        log_dir=str(runtime_paths.logs_root),
        report_dir=str(runtime_paths.reports_root),
    )


def to_runtime_path_overrides(config: AppConfig) -> RuntimePathOverrides:
    """AppConfig.runtime/paths → runtime resolver overrides."""
    runtime = config.runtime
    paths = config.paths
    return RuntimePathOverrides(
        runtime_root=runtime.runtime_root,
        config_root=runtime.config_root,
        datasets_root=runtime.datasets_root,
        dictionary_specs_root=runtime.dictionary_specs_root,
        dictionary_data_root=runtime.dictionary_data_root,
        source_data_root=runtime.source_data_root,
        source_projection_root=runtime.source_projection_root,
        target_projection_root=runtime.target_projection_root,
        cache_root=paths.cache_dir,
        logs_root=paths.log_dir,
        reports_root=paths.report_dir,
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
    "to_dataset_registry_path",
    "to_operational_paths",
    "to_runtime_path_overrides",
]
