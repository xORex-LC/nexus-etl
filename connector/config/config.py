from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, get_args, get_type_hints
import os
import yaml


UNSET = object()


@dataclass(frozen=True)
class Settings:
    """
    Назначение:
        Консолидированные настройки приложения после мерджа:
        CLI > ENV > config > defaults.
    """

    host: str | None = None
    port: int | None = None
    api_username: str | None = None
    api_password: str | None = None

    cache_dir: str = "./cache"
    log_dir: str = "./logs"
    report_dir: str = "./reports"

    tls_skip_verify: bool = False
    ca_file: str | None = None

    log_level: str = "INFO"
    log_json: bool = False
    report_format: str = "json"

    # API/cache refresh tuning (Stage 5)
    page_size: int = 200
    max_pages: int | None = None
    timeout_seconds: float = 20.0
    retries: int = 3
    retry_backoff_seconds: float = 0.5
    include_deleted: bool = False
    dataset_name: str = "employees"
    report_items_limit: int = 200
    report_include_skipped: bool = True
    resource_exists_retries: int = 3
    csv_has_header: bool = False
    stop_on_first_error: bool = False
    max_actions: int | None = None
    dry_run: bool = False
    diagnostics_strict: bool = False

    # Match/resolve runtime micro-batching
    match_batch_size: int = 500
    match_flush_interval_ms: int = 500
    resolve_batch_size: int = 500
    resolve_flush_interval_ms: int = 500

    # Resolver pending/identity tuning
    pending_ttl_seconds: int = 120
    pending_max_attempts: int = 5
    pending_sweep_interval_seconds: int = 60
    pending_on_expire: str = "error"
    pending_allow_partial: bool = False
    # Срок хранения обработанных pending-записей (в днях). 0 = не чистить.
    pending_retention_days: int = 14

    # Vault rollout/operations
    vault_rollout_mode: str = "full"
    vault_canary_percent: int = 100
    vault_canary_datasets: str = ""
    vault_canary_seed: str = "vault-rollout-v1"
    vault_row_failure_rate_threshold_pct: float = 5.0
    vault_error_rate_threshold_pct: float = 5.0
    vault_latency_regression_threshold_pct: float = 15.0
    vault_busy_timeout_rate_threshold_pct: float = 0.0
    vault_schema_changed_rate_threshold_pct: float = 0.0


@dataclass(frozen=True)
class SettingsIssue:
    """
    Унифицированный payload ошибки/предупреждения конфигурации.
    """

    code: str
    field_path: str
    source: str
    raw_value: Any
    message: str
    hint: str


class SettingsLoadError(RuntimeError):
    """
    Базовая типизированная ошибка загрузки настроек.
    """

    def __init__(self, message: str, issues: list[SettingsIssue]) -> None:
        super().__init__(message)
        self.issues = issues


class SettingsSourceError(SettingsLoadError):
    """Ошибка чтения источника config/env/cli."""


class SettingsParseError(SettingsLoadError):
    """Ошибка приведения типа/формата."""


class SettingsValidationError(SettingsLoadError):
    """Ошибка инвариантов/валидации после merge."""


class SettingsConflictError(SettingsLoadError):
    """Ошибка конфликтующих параметров."""


@dataclass(frozen=True)
class LoadedSettings:
    """
    Назначение:
        Результат загрузки настроек с информацией об источниках.
    """

    settings: Settings
    sources_used: list[str]
    source_trace: dict[str, str] = field(default_factory=dict)
    warnings: list[SettingsIssue] = field(default_factory=list)


@dataclass(frozen=True)
class _FieldSpec:
    name: str
    base_type: type[Any]
    optional: bool
    env_name: str


def read_yaml_config(path: Path) -> dict:
    """
    Назначение:
        Читает YAML конфиг, возвращает словарь настроек.
    """
    if not path.exists():
        raise FileNotFoundError(f"Config file does not exist: {path}")
    if not path.is_file():
        raise IsADirectoryError(f"Config path is not a file: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("Top-level YAML structure must be a mapping/object")
    return data


def env_get(name: str) -> str | None:
    """
    Назначение:
        Получает переменную окружения и нормализует значение.
    """
    v = os.getenv(name)
    if v is None:
        return None
    vv = v.strip()
    if vv == "":
        return None
    return vv


def load_settings_model(config_path: str | None, cli_overrides: dict[str, Any]) -> LoadedSettings:
    """
    Назначение:
        Внутренний загрузчик плоской settings-модели, применяющий приоритет:
        CLI > ENV > config > defaults.

    Фаза 2:
        - централизованный parse/normalize по типам;
        - явная UNSET-семантика;
        - field-level source trace.

    Фаза 3:
        - типизированные ошибки загрузки;
        - агрегированная выдача field-level parse ошибок;
        - unknown-keys policy: warn (default) / error (strict).
    """
    defaults = Settings()
    specs = _build_field_specs()
    specs_by_name = {spec.name: spec for spec in specs}

    cfg: dict[str, Any] = {}
    if config_path:
        cfg = _load_config_source(config_path)

    env_raw = {spec.name: env_get(spec.env_name) for spec in specs}
    cli_raw = dict(cli_overrides or {})

    strict_unknown = _resolve_strict_unknown(defaults=defaults, cfg=cfg, env_raw=env_raw, cli_raw=cli_raw)
    unknown_issues = _collect_unknown_key_issues(cfg=cfg, cli_raw=cli_raw, specs_by_name=specs_by_name)
    if strict_unknown and unknown_issues:
        raise SettingsValidationError(
            "Unknown configuration keys are not allowed in strict mode",
            unknown_issues,
        )
    warnings = [] if strict_unknown else unknown_issues

    merged = asdict(defaults)
    source_trace = {spec.name: "default" for spec in specs}
    parse_issues: list[SettingsIssue] = []

    _apply_source(
        source_name="config",
        raw_values=cfg,
        merged=merged,
        source_trace=source_trace,
        specs_by_name=specs_by_name,
        skip_none=False,
        issues=parse_issues,
    )
    _apply_source(
        source_name="env",
        raw_values=env_raw,
        merged=merged,
        source_trace=source_trace,
        specs_by_name=specs_by_name,
        skip_none=True,
        issues=parse_issues,
    )
    _apply_source(
        source_name="cli",
        raw_values=cli_raw,
        merged=merged,
        source_trace=source_trace,
        specs_by_name=specs_by_name,
        skip_none=True,
        issues=parse_issues,
    )

    if parse_issues:
        raise SettingsParseError("Settings contain invalid values", parse_issues)

    settings = Settings(**merged)

    validation_issues = _validate_settings(settings)
    if validation_issues:
        conflict_codes = {"settings.conflict.api_credentials"}
        if any(issue.code in conflict_codes for issue in validation_issues):
            raise SettingsConflictError("Settings contain conflicting values", validation_issues)
        raise SettingsValidationError("Settings validation failed", validation_issues)

    sources_used = _sources_used(cfg=cfg, env_raw=env_raw, cli_raw=cli_raw)
    return LoadedSettings(
        settings=settings,
        sources_used=sources_used,
        source_trace=source_trace,
        warnings=warnings,
    )


def _load_config_source(config_path: str) -> dict[str, Any]:
    path = Path(config_path)
    try:
        return read_yaml_config(path)
    except Exception as exc:  # noqa: BLE001
        issue = SettingsIssue(
            code="settings.source.config_read_failed",
            field_path="config_path",
            source="config",
            raw_value=str(path),
            message=f"Unable to read config: {exc}",
            hint="Проверьте путь к config.yml и корректность YAML.",
        )
        raise SettingsSourceError("Failed to read settings config source", [issue]) from exc


def _resolve_strict_unknown(
    *,
    defaults: Settings,
    cfg: dict[str, Any],
    env_raw: dict[str, Any],
    cli_raw: dict[str, Any],
) -> bool:
    # defaults -> config -> env -> cli
    candidate: Any = defaults.diagnostics_strict
    if "diagnostics_strict" in cfg:
        candidate = cfg.get("diagnostics_strict")
    if env_raw.get("diagnostics_strict") is not None:
        candidate = env_raw.get("diagnostics_strict")
    if cli_raw.get("diagnostics_strict") is not None:
        candidate = cli_raw.get("diagnostics_strict")

    try:
        return bool(_parse_bool(candidate, source="policy", field_name="diagnostics_strict", optional=False))
    except ValueError:
        # Не ломаем политику unknown keys, если сам флаг невалиден:
        # это будет поймано parse-этапом как обычная field-ошибка.
        return bool(defaults.diagnostics_strict)


def _collect_unknown_key_issues(
    *,
    cfg: dict[str, Any],
    cli_raw: dict[str, Any],
    specs_by_name: dict[str, _FieldSpec],
) -> list[SettingsIssue]:
    issues: list[SettingsIssue] = []
    for key, raw in cfg.items():
        if key not in specs_by_name:
            issues.append(
                SettingsIssue(
                    code="settings.unknown_key",
                    field_path=key,
                    source="config",
                    raw_value=raw,
                    message=f"Unknown config key: '{key}'",
                    hint="Удалите ключ или добавьте его в модель Settings.",
                )
            )
    for key, raw in cli_raw.items():
        if raw is None:
            continue
        if key not in specs_by_name:
            issues.append(
                SettingsIssue(
                    code="settings.unknown_key",
                    field_path=key,
                    source="cli",
                    raw_value=raw,
                    message=f"Unknown CLI override key: '{key}'",
                    hint="Проверьте маппинг CLI overrides в app callback.",
                )
            )
    return issues


def _sources_used(*, cfg: dict[str, Any], env_raw: dict[str, Any], cli_raw: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    if cfg:
        sources.append("config")
    if any(v is not None for v in env_raw.values()):
        sources.append("env")
    if any(v is not None for v in cli_raw.values()):
        sources.append("cli")
    return sources


def _apply_source(
    *,
    source_name: str,
    raw_values: dict[str, Any],
    merged: dict[str, Any],
    source_trace: dict[str, str],
    specs_by_name: dict[str, _FieldSpec],
    skip_none: bool,
    issues: list[SettingsIssue],
) -> None:
    for key, raw in raw_values.items():
        spec = specs_by_name.get(key)
        if spec is None:
            continue
        if skip_none and raw is None:
            continue
        try:
            parsed = _parse_by_spec(spec, raw, source_name)
        except ValueError as exc:
            issues.append(
                SettingsIssue(
                    code="settings.parse.invalid_value",
                    field_path=spec.name,
                    source=source_name,
                    raw_value=raw,
                    message=str(exc),
                    hint=f"Проверьте значение '{spec.name}' и его тип ({spec.base_type.__name__}).",
                )
            )
            continue
        if parsed is UNSET:
            continue
        merged[key] = parsed
        source_trace[key] = source_name


def _field_to_env_name(name: str) -> str:
    return f"ANKEY_{name.upper()}"


def _build_field_specs() -> list[_FieldSpec]:
    hints = get_type_hints(Settings)
    specs: list[_FieldSpec] = []
    for f in fields(Settings):
        hint = hints[f.name]
        optional, base_type = _resolve_optional(hint)
        if base_type not in (str, int, float, bool):
            raise ValueError(f"Unsupported settings field type for '{f.name}': {hint}")
        specs.append(
            _FieldSpec(
                name=f.name,
                base_type=base_type,
                optional=optional,
                env_name=_field_to_env_name(f.name),
            )
        )
    return specs


def _resolve_optional(annotation: Any) -> tuple[bool, type[Any]]:
    args = get_args(annotation)
    if args and type(None) in args and len(args) == 2:  # noqa: E721
        filtered = [a for a in args if a is not type(None)]  # noqa: E721
        return True, filtered[0]
    return False, annotation


def _parse_by_spec(spec: _FieldSpec, raw: Any, source_name: str) -> Any:
    if spec.base_type is str:
        return _parse_str(raw, source_name, spec.name, optional=spec.optional)
    if spec.base_type is int:
        return _parse_int(raw, source_name, spec.name, optional=spec.optional)
    if spec.base_type is float:
        return _parse_float(raw, source_name, spec.name, optional=spec.optional)
    if spec.base_type is bool:
        return _parse_bool(raw, source_name, spec.name, optional=spec.optional)
    raise ValueError(f"Unsupported field type for '{spec.name}'")


def _parse_str(value: Any, source: str, field_name: str, *, optional: bool) -> Any:
    if value is None:
        return None if optional else UNSET
    if isinstance(value, str):
        return value
    raise ValueError(f"[{source}] Invalid string for '{field_name}': {value!r}")


def _parse_int(value: Any, source: str, field_name: str, *, optional: bool) -> Any:
    if value is None:
        return None if optional else UNSET
    if isinstance(value, bool):
        raise ValueError(f"[{source}] Invalid int for '{field_name}': {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        vv = value.strip()
        if vv == "":
            return None if optional else UNSET
        return int(vv)
    raise ValueError(f"[{source}] Invalid int for '{field_name}': {value!r}")


def _parse_float(value: Any, source: str, field_name: str, *, optional: bool) -> Any:
    if value is None:
        return None if optional else UNSET
    if isinstance(value, bool):
        raise ValueError(f"[{source}] Invalid float for '{field_name}': {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        vv = value.strip()
        if vv == "":
            return None if optional else UNSET
        return float(vv)
    raise ValueError(f"[{source}] Invalid float for '{field_name}': {value!r}")


def _parse_bool(value: Any, source: str, field_name: str, *, optional: bool) -> Any:
    if value is None:
        return None if optional else UNSET
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        raise ValueError(f"[{source}] Invalid bool for '{field_name}': {value!r}")
    if isinstance(value, str):
        vv = value.strip().lower()
        if vv == "":
            return None if optional else UNSET
        if vv in ("1", "true", "yes", "y"):
            return True
        if vv in ("0", "false", "no", "n"):
            return False
    raise ValueError(f"[{source}] Invalid bool for '{field_name}': {value!r}")


_RANGE_RULES: list[tuple[str, str, str, str]] = [
    ("page_size", ">0", "page_size must be greater than 0", "Укажите положительное значение page_size."),
    ("retries", ">=0", "retries must be >= 0", "Укажите retries >= 0."),
    ("match_batch_size", ">0", "match_batch_size must be greater than 0", "Укажите положительное значение match_batch_size."),
    ("resolve_batch_size", ">0", "resolve_batch_size must be greater than 0", "Укажите положительное значение resolve_batch_size."),
    ("pending_ttl_seconds", ">0", "pending_ttl_seconds must be greater than 0", "Укажите положительное значение pending_ttl_seconds."),
    (
        "vault_row_failure_rate_threshold_pct",
        ">=0",
        "vault_row_failure_rate_threshold_pct must be >= 0",
        "Укажите vault_row_failure_rate_threshold_pct >= 0.",
    ),
    (
        "vault_error_rate_threshold_pct",
        ">=0",
        "vault_error_rate_threshold_pct must be >= 0",
        "Укажите vault_error_rate_threshold_pct >= 0.",
    ),
    (
        "vault_latency_regression_threshold_pct",
        ">=0",
        "vault_latency_regression_threshold_pct must be >= 0",
        "Укажите vault_latency_regression_threshold_pct >= 0.",
    ),
    (
        "vault_busy_timeout_rate_threshold_pct",
        ">=0",
        "vault_busy_timeout_rate_threshold_pct must be >= 0",
        "Укажите vault_busy_timeout_rate_threshold_pct >= 0.",
    ),
    (
        "vault_schema_changed_rate_threshold_pct",
        ">=0",
        "vault_schema_changed_rate_threshold_pct must be >= 0",
        "Укажите vault_schema_changed_rate_threshold_pct >= 0.",
    ),
]

_ENUM_RULES: list[tuple[str, frozenset[str], str, str]] = [
    (
        "pending_on_expire",
        frozenset({"error", "report_only", "skip"}),
        "pending_on_expire must be one of: error, report_only, skip",
        "Используйте значение error, report_only или skip.",
    ),
    (
        "vault_rollout_mode",
        frozenset({"off", "staging_dry_run", "canary", "full"}),
        "vault_rollout_mode must be one of: off, staging_dry_run, canary, full",
        "Используйте rollout mode: off, staging_dry_run, canary или full.",
    ),
]


def _check_range(value: int | float, op: str) -> bool:
    if op == ">0":
        return value > 0
    if op == ">=0":
        return value >= 0
    raise ValueError(f"Unknown range operator: {op}")


def _validate_settings(settings: Settings) -> list[SettingsIssue]:
    issues: list[SettingsIssue] = []

    for field_name, op, message, hint in _RANGE_RULES:
        value = getattr(settings, field_name)
        if not _check_range(value, op):
            issues.append(SettingsIssue(
                code="settings.validation.range",
                field_path=field_name,
                source="validation",
                raw_value=value,
                message=message,
                hint=hint,
            ))

    for field_name, allowed, message, hint in _ENUM_RULES:
        value = getattr(settings, field_name)
        if value not in allowed:
            issues.append(SettingsIssue(
                code="settings.validation.enum",
                field_path=field_name,
                source="validation",
                raw_value=value,
                message=message,
                hint=hint,
            ))

    if settings.vault_canary_percent < 0 or settings.vault_canary_percent > 100:
        issues.append(
            SettingsIssue(
                code="settings.validation.range",
                field_path="vault_canary_percent",
                source="validation",
                raw_value=settings.vault_canary_percent,
                message="vault_canary_percent must be in range 0..100",
                hint="Укажите целое значение от 0 до 100.",
            )
        )

    if (settings.host is None) != (settings.port is None):
        issues.append(SettingsIssue(
            code="settings.conflict.api_credentials",
            field_path="host/port",
            source="validation",
            raw_value={"host": settings.host, "port": settings.port},
            message="host and port must be provided together",
            hint="Либо укажите оба поля host и port, либо не указывайте оба.",
        ))

    return issues
