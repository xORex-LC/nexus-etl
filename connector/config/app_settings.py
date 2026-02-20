from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from connector.config.config import SettingsIssue, load_settings_model
from connector.domain.transform.resolver.resolve_deps import ResolverSettings
from connector.infra.sqlite.config import SqliteDbConfig


@dataclass(frozen=True)
class ApiSettings:
    host: str | None
    port: int | None
    username: str | None
    password: str | None
    tls_skip_verify: bool
    ca_file: str | None
    timeout_seconds: float
    retries: int
    retry_backoff_seconds: float
    resource_exists_retries: int


@dataclass(frozen=True)
class PathsSettings:
    cache_dir: str
    log_dir: str
    report_dir: str


@dataclass(frozen=True)
class ObservabilitySettings:
    log_level: str
    log_json: bool
    report_format: str
    report_items_limit: int
    report_include_skipped: bool
    diagnostics_strict: bool


@dataclass(frozen=True)
class DatasetSettings:
    dataset_name: str
    csv_has_header: bool
    include_deleted: bool


@dataclass(frozen=True)
class ExecutionSettings:
    stop_on_first_error: bool
    max_actions: int | None
    dry_run: bool


@dataclass(frozen=True)
class RefreshSettings:
    page_size: int
    max_pages: int | None


@dataclass(frozen=True)
class MatchingRuntimeSettings:
    match_batch_size: int
    match_flush_interval_ms: int
    resolve_batch_size: int
    resolve_flush_interval_ms: int


@dataclass(frozen=True)
class VaultRolloutSettings:
    """Назначение:
        Runtime feature-flag политика для staged rollout vault-контура.
    """

    mode: str
    canary_percent: int
    canary_datasets: tuple[str, ...]
    canary_seed: str
    row_failure_rate_threshold_pct: float
    vault_error_rate_threshold_pct: float
    latency_regression_threshold_pct: float
    busy_timeout_rate_threshold_pct: float
    schema_changed_rate_threshold_pct: float


def _default_vault_rollout_settings() -> VaultRolloutSettings:
    return VaultRolloutSettings(
        mode="full",
        canary_percent=100,
        canary_datasets=(),
        canary_seed="vault-rollout-v1",
        row_failure_rate_threshold_pct=5.0,
        vault_error_rate_threshold_pct=5.0,
        latency_regression_threshold_pct=15.0,
        busy_timeout_rate_threshold_pct=0.0,
        schema_changed_rate_threshold_pct=0.0,
    )


@dataclass(frozen=True)
class AppSettings:
    api: ApiSettings
    paths: PathsSettings
    observability: ObservabilitySettings
    dataset: DatasetSettings
    execution: ExecutionSettings
    refresh: RefreshSettings
    matching_runtime: MatchingRuntimeSettings
    resolver: ResolverSettings
    vault_rollout: VaultRolloutSettings = field(default_factory=_default_vault_rollout_settings)

@dataclass(frozen=True)
class LoadedAppSettings:
    app_settings: AppSettings
    sources_used: tuple[str, ...]
    source_trace: dict[str, str]
    warnings: tuple[SettingsIssue, ...]


# Settings field → slice field mapping. Keys are Settings field names,
# values are slice constructor kwarg names.
_SLICE_FIELD_MAP: dict[type, dict[str, str]] = {
    ApiSettings: {
        "host": "host",
        "port": "port",
        "api_username": "username",
        "api_password": "password",
        "tls_skip_verify": "tls_skip_verify",
        "ca_file": "ca_file",
        "timeout_seconds": "timeout_seconds",
        "retries": "retries",
        "retry_backoff_seconds": "retry_backoff_seconds",
        "resource_exists_retries": "resource_exists_retries",
    },
    PathsSettings: {
        "cache_dir": "cache_dir",
        "log_dir": "log_dir",
        "report_dir": "report_dir",
    },
    ObservabilitySettings: {
        "log_level": "log_level",
        "log_json": "log_json",
        "report_format": "report_format",
        "report_items_limit": "report_items_limit",
        "report_include_skipped": "report_include_skipped",
        "diagnostics_strict": "diagnostics_strict",
    },
    DatasetSettings: {
        "dataset_name": "dataset_name",
        "csv_has_header": "csv_has_header",
        "include_deleted": "include_deleted",
    },
    ExecutionSettings: {
        "stop_on_first_error": "stop_on_first_error",
        "max_actions": "max_actions",
        "dry_run": "dry_run",
    },
    RefreshSettings: {
        "page_size": "page_size",
        "max_pages": "max_pages",
    },
    MatchingRuntimeSettings: {
        "match_batch_size": "match_batch_size",
        "match_flush_interval_ms": "match_flush_interval_ms",
        "resolve_batch_size": "resolve_batch_size",
        "resolve_flush_interval_ms": "resolve_flush_interval_ms",
    },
    ResolverSettings: {
        "pending_ttl_seconds": "pending_ttl_seconds",
        "pending_max_attempts": "pending_max_attempts",
        "pending_sweep_interval_seconds": "pending_sweep_interval_seconds",
        "pending_on_expire": "pending_on_expire",
        "pending_allow_partial": "pending_allow_partial",
        "pending_retention_days": "pending_retention_days",
    },
    VaultRolloutSettings: {
        "vault_rollout_mode": "mode",
        "vault_canary_percent": "canary_percent",
        "vault_canary_datasets": "canary_datasets",
        "vault_canary_seed": "canary_seed",
        "vault_row_failure_rate_threshold_pct": "row_failure_rate_threshold_pct",
        "vault_error_rate_threshold_pct": "vault_error_rate_threshold_pct",
        "vault_latency_regression_threshold_pct": "latency_regression_threshold_pct",
        "vault_busy_timeout_rate_threshold_pct": "busy_timeout_rate_threshold_pct",
        "vault_schema_changed_rate_threshold_pct": "schema_changed_rate_threshold_pct",
    },
}


def _build_slice(cls: type, settings: Any, field_map: dict[str, str]) -> Any:
    return cls(**{slice_f: getattr(settings, settings_f) for settings_f, slice_f in field_map.items()})


def _parse_canary_datasets(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    items: list[str] = []
    for chunk in raw.split(","):
        value = chunk.strip()
        if not value:
            continue
        items.append(value)
    return tuple(items)


def _build_vault_rollout_settings(settings: Any) -> VaultRolloutSettings:
    return VaultRolloutSettings(
        mode=settings.vault_rollout_mode,
        canary_percent=settings.vault_canary_percent,
        canary_datasets=_parse_canary_datasets(settings.vault_canary_datasets),
        canary_seed=settings.vault_canary_seed,
        row_failure_rate_threshold_pct=settings.vault_row_failure_rate_threshold_pct,
        vault_error_rate_threshold_pct=settings.vault_error_rate_threshold_pct,
        latency_regression_threshold_pct=settings.vault_latency_regression_threshold_pct,
        busy_timeout_rate_threshold_pct=settings.vault_busy_timeout_rate_threshold_pct,
        schema_changed_rate_threshold_pct=settings.vault_schema_changed_rate_threshold_pct,
    )


# ──────────────────────────────────────────────────────────────────────────────
# SQLite configuration (Pydantic BaseSettings — независимо от плоского Settings)
# ──────────────────────────────────────────────────────────────────────────────


class SqliteSettings(BaseSettings):
    """
    Назначение:
        Конфигурация всех SQLite-соединений проекта (cache, vault, identity).
        Читается из env vars с префиксом ANKEY_.

    Граница ответственности:
        - Самостоятельная Pydantic BaseSettings; поля в плоский Settings (config.py) не добавляются.
        - Хранит глобальные дефолты и per-DB overrides (None = взять global).
        - CLI-overrides прокидываются при инстанциировании:
          SqliteSettings(vault_sqlite_busy_timeout_ms=cli_value).

    Инварианты:
        - env_ignore_empty=True: пустая строка не перетирает дефолт.
        - Все int | None поля: None означает «использовать глобальный дефолт».
    """

    model_config = SettingsConfigDict(env_prefix="ANKEY_", env_ignore_empty=True)

    # Глобальные дефолты (применяются ко всем DB при отсутствии per-DB override)
    sqlite_journal_mode: str = "WAL"
    sqlite_synchronous: str = "NORMAL"
    sqlite_busy_timeout_ms: int = 5000
    sqlite_wal_autocheckpoint: int = 1000

    # Vault overrides (None = использовать global)
    vault_db_path: str | None = None
    vault_sqlite_transaction_mode: str = "immediate"
    vault_sqlite_journal_mode: str | None = None
    vault_sqlite_busy_timeout_ms: int | None = None
    vault_sqlite_schema_retry_count: int = 2

    # Cache overrides (None = использовать global)
    cache_sqlite_transaction_mode: str = "deferred"
    cache_sqlite_journal_mode: str | None = None
    cache_sqlite_busy_timeout_ms: int | None = None

    # Identity
    identity_db_path: str | None = None  # None → {cache_dir}/identity.sqlite3


def build_vault_db_config(s: SqliteSettings) -> SqliteDbConfig:
    """Собрать SqliteDbConfig для vault DB из SqliteSettings с override chain."""
    return SqliteDbConfig(
        transaction_mode=s.vault_sqlite_transaction_mode,  # type: ignore[arg-type]
        busy_timeout_ms=s.vault_sqlite_busy_timeout_ms or s.sqlite_busy_timeout_ms,
        journal_mode=s.vault_sqlite_journal_mode or s.sqlite_journal_mode,
        synchronous=s.sqlite_synchronous,
        wal_autocheckpoint=s.sqlite_wal_autocheckpoint,
        schema_retry_count=s.vault_sqlite_schema_retry_count,
    )


def build_cache_db_config(s: SqliteSettings) -> SqliteDbConfig:
    """Собрать SqliteDbConfig для cache DB из SqliteSettings с override chain."""
    return SqliteDbConfig(
        transaction_mode=s.cache_sqlite_transaction_mode,  # type: ignore[arg-type]
        busy_timeout_ms=s.cache_sqlite_busy_timeout_ms or s.sqlite_busy_timeout_ms,
        journal_mode=s.cache_sqlite_journal_mode or s.sqlite_journal_mode,
        synchronous=s.sqlite_synchronous,
        wal_autocheckpoint=s.sqlite_wal_autocheckpoint,
    )


def build_identity_db_config(s: SqliteSettings) -> SqliteDbConfig:
    """Собрать SqliteDbConfig для identity DB из SqliteSettings (только global дефолты)."""
    return SqliteDbConfig(
        transaction_mode="deferred",
        busy_timeout_ms=s.sqlite_busy_timeout_ms,
        journal_mode=s.sqlite_journal_mode,
        synchronous=s.sqlite_synchronous,
        wal_autocheckpoint=s.sqlite_wal_autocheckpoint,
    )


def load_app_settings(config_path: str | None, cli_overrides: dict[str, Any]) -> LoadedAppSettings:
    """
    Назначение:
        Каноническая загрузка настроек приложения в срезанную модель AppSettings.
    """
    loaded = load_settings_model(config_path=config_path, cli_overrides=cli_overrides)
    settings = loaded.settings
    app_settings = AppSettings(
        api=_build_slice(ApiSettings, settings, _SLICE_FIELD_MAP[ApiSettings]),
        paths=_build_slice(PathsSettings, settings, _SLICE_FIELD_MAP[PathsSettings]),
        observability=_build_slice(ObservabilitySettings, settings, _SLICE_FIELD_MAP[ObservabilitySettings]),
        dataset=_build_slice(DatasetSettings, settings, _SLICE_FIELD_MAP[DatasetSettings]),
        execution=_build_slice(ExecutionSettings, settings, _SLICE_FIELD_MAP[ExecutionSettings]),
        refresh=_build_slice(RefreshSettings, settings, _SLICE_FIELD_MAP[RefreshSettings]),
        matching_runtime=_build_slice(MatchingRuntimeSettings, settings, _SLICE_FIELD_MAP[MatchingRuntimeSettings]),
        resolver=_build_slice(ResolverSettings, settings, _SLICE_FIELD_MAP[ResolverSettings]),
        vault_rollout=_build_vault_rollout_settings(settings),
    )
    return LoadedAppSettings(
        app_settings=app_settings,
        sources_used=tuple(loaded.sources_used),
        source_trace=dict(loaded.source_trace),
        warnings=tuple(loaded.warnings),
    )
