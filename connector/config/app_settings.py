from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from connector.config.config import SettingsIssue, _load_settings_model


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
class AppSettings:
    api: ApiSettings
    paths: PathsSettings
    observability: ObservabilitySettings
    dataset: DatasetSettings
    execution: ExecutionSettings
    refresh: RefreshSettings
    matching_runtime: MatchingRuntimeSettings
    pending: PendingSettings

@dataclass(frozen=True)
class LoadedAppSettings:
    app_settings: AppSettings
    sources_used: tuple[str, ...]
    source_trace: dict[str, str]
    warnings: tuple[SettingsIssue, ...]

def loadAppSettings(config_path: str | None, cli_overrides: dict[str, Any]) -> LoadedAppSettings:
    """
    Назначение:
        Каноническая загрузка настроек приложения в срезанную модель AppSettings.
    """
    loaded = _load_settings_model(config_path=config_path, cli_overrides=cli_overrides)
    settings = loaded.settings
    app_settings = AppSettings(
        api=ApiSettings(
            host=settings.host,
            port=settings.port,
            username=settings.api_username,
            password=settings.api_password,
            tls_skip_verify=settings.tls_skip_verify,
            ca_file=settings.ca_file,
            timeout_seconds=settings.timeout_seconds,
            retries=settings.retries,
            retry_backoff_seconds=settings.retry_backoff_seconds,
            resource_exists_retries=settings.resource_exists_retries,
        ),
        paths=PathsSettings(
            cache_dir=settings.cache_dir,
            log_dir=settings.log_dir,
            report_dir=settings.report_dir,
        ),
        observability=ObservabilitySettings(
            log_level=settings.log_level,
            log_json=settings.log_json,
            report_format=settings.report_format,
            report_items_limit=settings.report_items_limit,
            report_include_skipped=settings.report_include_skipped,
            diagnostics_strict=settings.diagnostics_strict,
        ),
        dataset=DatasetSettings(
            dataset_name=settings.dataset_name,
            csv_has_header=settings.csv_has_header,
            include_deleted=settings.include_deleted,
        ),
        execution=ExecutionSettings(
            stop_on_first_error=settings.stop_on_first_error,
            max_actions=settings.max_actions,
            dry_run=settings.dry_run,
        ),
        refresh=RefreshSettings(
            page_size=settings.page_size,
            max_pages=settings.max_pages,
        ),
        matching_runtime=MatchingRuntimeSettings(
            match_batch_size=settings.match_batch_size,
            match_flush_interval_ms=settings.match_flush_interval_ms,
            resolve_batch_size=settings.resolve_batch_size,
            resolve_flush_interval_ms=settings.resolve_flush_interval_ms,
        ),
        pending=PendingSettings(
            pending_ttl_seconds=settings.pending_ttl_seconds,
            pending_max_attempts=settings.pending_max_attempts,
            pending_sweep_interval_seconds=settings.pending_sweep_interval_seconds,
            pending_on_expire=settings.pending_on_expire,
            pending_allow_partial=settings.pending_allow_partial,
            pending_retention_days=settings.pending_retention_days,
        ),
    )
    return LoadedAppSettings(
        app_settings=app_settings,
        sources_used=tuple(loaded.sources_used),
        source_trace=dict(loaded.source_trace),
        warnings=tuple(loaded.warnings),
    )
