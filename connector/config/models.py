"""
Назначение:
    Канонические Pydantic-модели конфигурации приложения (config-layer).

    AppConfig — единственный внутренний контракт приложения для доставки
    user-facing настроек. Все секции заморожены и запрещают лишние ключи.

Граница ответственности:
    - Хранит структуру и дефолты user-facing параметров.
    - Декларативная валидация через типы (Literal, Field constraints).
    - Не выполняет IO, не знает об источниках (CLI/ENV/YAML).
    - Не управляет lifecycle: создание через load_app_config() в loader.py.

Инварианты:
    - frozen=True: AppConfig иммутабелен после создания.
    - extra="forbid": неизвестные YAML-ключи обнаруживаются при загрузке.
    - Дефолты совпадают с текущими Settings / AppSettings (регрессионная защита).

Связанные ADR:
    - CONFIG-DEC-002: migration to Pydantic BaseModel + unified loader
    - CONFIG-DEC-003: settings taxonomy and boundary adapters
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiConfig(BaseModel):
    """Параметры подключения к целевому API."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str | None = None
    port: int | None = Field(default=None, gt=0, le=65535)
    username: str | None = None
    password: str | None = None
    tls_skip_verify: bool = False
    ca_file: str | None = None
    timeout_seconds: float = Field(default=20.0, gt=0)
    retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_seconds: float = Field(default=0.5, ge=0.0, le=60.0)
    resource_exists_retries: int = Field(default=3, ge=0)


class PathsConfig(BaseModel):
    """Пути к рабочим директориям."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cache_dir: str = "./cache"
    log_dir: str = "./logs"
    report_dir: str = "./reports"


class ObservabilityConfig(BaseModel):
    """Параметры логирования, отчётности и диагностики."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = False
    report_format: Literal["json", "text"] = "json"
    report_items_limit: int = Field(default=200, gt=0)
    report_include_skipped: bool = True
    diagnostics_strict: bool = False


class DatasetConfig(BaseModel):
    """Параметры источника данных (датасет, формат входных данных)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_name: str = "employees"
    csv_has_header: bool = False
    include_deleted: bool = False


class ExecutionConfig(BaseModel):
    """Параметры управления выполнением команды."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stop_on_first_error: bool = False
    max_actions: int | None = Field(default=None, gt=0)
    dry_run: bool = False


class RefreshConfig(BaseModel):
    """Параметры пагинации при чтении из API."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_size: int = Field(default=200, gt=0)
    max_pages: int | None = Field(default=None, gt=0)


class MatchingRuntimeConfig(BaseModel):
    """Параметры micro-batching для MatchStage.

    Resolve batch-параметры перенесены в ResolverConfig:
    нет отдельного domain-порта IResolveBatchSettings —
    они доставляются через DI-wiring напрямую.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    match_batch_size: int = Field(default=500, gt=0)
    match_flush_interval_ms: int = Field(default=500, gt=0)


class ResolverConfig(BaseModel):
    """Config-layer модель для resolver/pending механики.

    Projection в domain ResolverSettings через to_resolver_settings().
    Дефолты совпадают с текущими Settings (pending_max_attempts=5, ttl=120).

    resolve_batch_size / resolve_flush_interval_ms перенесены сюда из
    MatchingRuntimeConfig: нет отдельного domain-порта — доставка через
    DI-wiring (app_config.resolver.resolve_batch_size).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pending_ttl_seconds: int = Field(default=120, gt=0)
    pending_max_attempts: int = Field(default=5, ge=0)
    pending_sweep_interval_seconds: int = Field(default=60, gt=0)
    pending_on_expire: Literal["error", "report_only", "skip"] = "error"
    pending_allow_partial: bool = False
    pending_retention_days: int = Field(default=14, ge=0)
    # Resolve micro-batching (перенесены из MatchingRuntimeSettings)
    resolve_batch_size: int = Field(default=500, gt=0)
    resolve_flush_interval_ms: int = Field(default=500, gt=0)


class VaultRolloutConfig(BaseModel):
    """Runtime feature-flag политика для staged rollout vault-контура.

    Дефолты выровнены по текущим доменным VaultRolloutThresholds
    (regression-safe): row=5.0, latency=15.0, busy=0.0, schema=0.0.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # "staging_dry_run" обязателен: поддерживается evaluate_vault_rollout()
    mode: Literal["full", "canary", "staging_dry_run", "off"] = "full"
    canary_percent: int = Field(default=100, ge=0, le=100)
    # tuple[str, ...]: Pydantic v2 автоматически coerce-ит YAML-list → tuple
    canary_datasets: tuple[str, ...] = ()
    # дефолт совпадает с доменным VaultRolloutPolicySettings.canary_seed
    canary_seed: str = "vault-rollout-v1"
    # дефолты выровнены по текущим VaultRolloutThresholds (regression guard)
    row_failure_rate_threshold_pct: float = Field(default=5.0, ge=0, le=100)
    # поле переименовано: убран префикс vault_ (был несогласован в legacy)
    error_rate_threshold_pct: float = Field(default=5.0, ge=0, le=100)
    latency_regression_threshold_pct: float = Field(default=15.0, ge=0, le=100)
    busy_timeout_rate_threshold_pct: float = Field(default=0.0, ge=0, le=100)
    schema_changed_rate_threshold_pct: float = Field(default=0.0, ge=0, le=100)


class SqliteConfig(BaseModel):
    """Конфигурация SQLite-соединений: глобальные дефолты + per-DB overrides.

    None в per-DB полях означает «использовать глобальный дефолт».
    Пути к файлам БД (vault_db_path и т.д.) используются DI-контейнером
    для открытия соединения; они не передаются в SqliteDbConfig.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Глобальные дефолты (применяются ко всем DB при отсутствии per-DB override)
    journal_mode: Literal["WAL", "DELETE", "MEMORY", "TRUNCATE", "PERSIST", "OFF"] = "WAL"
    synchronous: Literal["OFF", "NORMAL", "FULL", "EXTRA"] = "NORMAL"
    busy_timeout_ms: int = Field(default=5000, ge=0)
    wal_autocheckpoint: int = Field(default=1000, ge=0)

    # Vault overrides (None = использовать global)
    vault_db_path: str | None = None
    vault_transaction_mode: Literal["deferred", "immediate", "exclusive"] = "immediate"
    vault_journal_mode: Literal["WAL", "DELETE", "MEMORY", "TRUNCATE", "PERSIST", "OFF"] | None = None
    vault_busy_timeout_ms: int | None = Field(default=None, ge=0)
    vault_schema_retry_count: int = Field(default=2, ge=0, le=10)

    # Cache overrides (None = использовать global)
    cache_db_path: str | None = None
    cache_transaction_mode: Literal["deferred", "immediate", "exclusive"] = "deferred"
    cache_journal_mode: Literal["WAL", "DELETE", "MEMORY", "TRUNCATE", "PERSIST", "OFF"] | None = None
    cache_busy_timeout_ms: int | None = Field(default=None, ge=0)

    # Identity (только global дефолты; нет per-DB override полей)
    identity_db_path: str | None = None


class DictionaryConfig(BaseModel):
    """Runtime-конфигурация Dictionary layer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    load_strategy: Literal["eager", "lazy"] = "eager"
    fingerprint_salt: str = "dictionary-runtime-v1"
    fingerprint_salt_version: str = "v1"
    lookup_hit_sample_percent: int = Field(default=1, ge=0, le=100)
    lookup_miss_sample_percent: int = Field(default=10, ge=0, le=100)


class AppConfig(BaseModel):
    """Каноническая модель конфигурации приложения.

    Единственный внутренний контракт для доставки user-facing настроек.
    Все параметры проходят путь: CLI/ENV/YAML/defaults → load_app_config() → AppConfig.

    Граница ответственности:
        - Owns: структура, дефолты, декларативная валидация.
        - Does NOT: IO, lifecycle, DI-wiring, projection в domain/infra типы.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    api: ApiConfig = ApiConfig()
    paths: PathsConfig = PathsConfig()
    observability: ObservabilityConfig = ObservabilityConfig()
    dataset: DatasetConfig = DatasetConfig()
    execution: ExecutionConfig = ExecutionConfig()
    refresh: RefreshConfig = RefreshConfig()
    matching_runtime: MatchingRuntimeConfig = MatchingRuntimeConfig()
    resolver: ResolverConfig = ResolverConfig()
    sqlite: SqliteConfig = SqliteConfig()
    dictionary: DictionaryConfig = DictionaryConfig()
    vault_rollout: VaultRolloutConfig = VaultRolloutConfig()


__all__ = [
    "ApiConfig",
    "PathsConfig",
    "ObservabilityConfig",
    "DatasetConfig",
    "ExecutionConfig",
    "RefreshConfig",
    "MatchingRuntimeConfig",
    "ResolverConfig",
    "VaultRolloutConfig",
    "SqliteConfig",
    "DictionaryConfig",
    "AppConfig",
]
