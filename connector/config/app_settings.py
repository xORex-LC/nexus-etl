from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from connector.config.config import SettingsIssue, load_settings_model


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
class PendingSettings:
    pending_ttl_seconds: int
    pending_max_attempts: int
    pending_sweep_interval_seconds: int
    pending_on_expire: str
    pending_allow_partial: bool
    pending_retention_days: int


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
    pending: PendingSettings
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
    PendingSettings: {
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
        pending=_build_slice(PendingSettings, settings, _SLICE_FIELD_MAP[PendingSettings]),
        vault_rollout=_build_vault_rollout_settings(settings),
    )
    return LoadedAppSettings(
        app_settings=app_settings,
        sources_used=tuple(loaded.sources_used),
        source_trace=dict(loaded.source_trace),
        warnings=tuple(loaded.warnings),
    )
