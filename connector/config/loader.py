"""
Назначение:
    Unified loader конфигурации приложения: единственный production entrypoint
    загрузки user-facing настроек.

    load_app_config() объединяет чтение YAML, ENV-overrides и CLI-overrides
    в один merge-цикл с per-field source trace, затем валидирует через Pydantic.

Граница ответственности:
    - Owns: merge-логика (CLI > ENV > YAML > defaults), source trace, Pydantic validation.
    - Does NOT: бизнес-логику, lifecycle, DI-wiring, projection в domain/infra типы.
    - Заменяет: load_settings_model() + load_app_settings() (будут удалены в Этапе 3).

Инварианты:
    - Единственный путь загрузки user-facing config в production.
    - ENV naming: ANKEY_{SECTION}__{FIELD} (двойное подчёркивание — разделитель уровней).
    - CLI overrides: dotted-path dict {"api.host": value}.
    - Пустые ENV-значения игнорируются (env_ignore_empty semantics).
    - ValidationError → SettingsLoadError с list[SettingsIssue].
    - Отсутствующий config-файл → SettingsSourceError с code settings.source.config_read_failed.

Связанные ADR:
    - CONFIG-DEC-002: migration to Pydantic BaseModel + unified loader
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from connector.config.config import (
    SettingsIssue,
    SettingsLoadError,
    SettingsSourceError,
    read_yaml_config,
)
from connector.config.models import AppConfig

# ENV prefix и разделитель уровней: ANKEY_API__HOST → section=api, field=host
_ENV_PREFIX = "ANKEY_"
_LEVEL_SEP = "__"
_ENV_OVERRIDE_DENIED_SECTIONS = frozenset({"vault_management", "runtime"})
_ENV_OVERRIDE_DENIED_FIELDS = frozenset(
    {
        "paths.cache_dir",
        "paths.log_dir",
        "paths.report_dir",
        "paths.plans_dir",
        "dataset.registry_path",
        "sqlite.vault_db_path",
        "sqlite.cache_db_path",
        "sqlite.identity_db_path",
    }
)


@dataclass(frozen=True)
class LoadedAppConfig:
    """Результат загрузки конфигурации с диагностикой.

    source_trace: per-field map вида "api.host" → "config"|"env"|"cli"|"default".
    warnings: предупреждения (всегда пустой список — с extra="forbid" нет warn-режима).
    """

    app_config: AppConfig
    source_trace: dict[str, str]
    warnings: list[SettingsIssue] = field(default_factory=list)


def load_app_config(
    config_path: str | None = None,
    cli_overrides: dict[str, object] | None = None,
) -> LoadedAppConfig:
    """Единственный production entrypoint загрузки конфигурации.

    Приоритет: CLI > ENV > config-file > defaults.

    Args:
        config_path: Путь к YAML config-файлу (nested формат). None — только ENV/defaults.
        cli_overrides: Dotted-path dict {"api.host": "x", "api.port": 443}.
                       None-значения пропускаются (флаг «не задан»).

    Returns:
        LoadedAppConfig с валидным AppConfig, source_trace и пустым warnings.

    Raises:
        SettingsSourceError: config-файл не существует или нечитаем.
        SettingsLoadError: Pydantic ValidationError (unknown key, range, literal и т.д.).
    """
    # 1. Читаем YAML
    yaml_data: dict[str, Any] = {}
    if config_path:
        yaml_data = _read_config(config_path)

    # 2. Собираем ENV overrides: ANKEY_{SECTION}__{FIELD} → nested dict
    env_data = _collect_env_overrides()

    # 3. CLI overrides: dotted-path → nested dict, None-значения выброшены
    cli_data = _dotted_to_nested(cli_overrides or {})

    # 4. Merge: yaml → env → cli (каждый последующий имеет более высокий приоритет)
    merged: dict[str, Any] = {}
    trace: dict[str, str] = {}
    _deep_merge(merged, trace, yaml_data, source="config")
    _deep_merge(merged, trace, env_data, source="env")
    _deep_merge(merged, trace, cli_data, source="cli")

    # 5. Pydantic validation
    try:
        app_config = AppConfig.model_validate(merged)
    except ValidationError as exc:
        issues = _pydantic_error_to_issues(exc)
        raise SettingsLoadError("Invalid settings configuration", issues) from exc

    # 6. Заполняем "default" для всех полей, не затронутых источниками
    _fill_default_trace(app_config, trace)

    return LoadedAppConfig(
        app_config=app_config,
        source_trace=trace,
        warnings=[],
    )


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────


def _read_config(config_path: str) -> dict[str, Any]:
    """Читает YAML config-файл; при ошибке бросает SettingsSourceError."""
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
            hint="Check the config path and YAML syntax.",
        )
        raise SettingsSourceError("Failed to read settings config source", [issue]) from exc


def _collect_env_overrides() -> dict[str, Any]:
    """Собирает ENV vars вида ANKEY_{SECTION}__{FIELD} в nested dict.

    Пустые значения (после strip) пропускаются — env_ignore_empty semantics.
    """
    result: dict[str, Any] = {}
    prefix_len = len(_ENV_PREFIX)
    for name, value in os.environ.items():
        if not name.startswith(_ENV_PREFIX):
            continue
        tail = name[prefix_len:]
        if _LEVEL_SEP not in tail:
            # Нет разделителя уровней — не наш формат (или legacy ANKEY_HOST)
            continue
        section_raw, _, field_raw = tail.partition(_LEVEL_SEP)
        stripped = value.strip()
        if not stripped:
            # Пустая строка — env_ignore_empty: не перетираем дефолт
            continue
        section = section_raw.lower()
        if section in _ENV_OVERRIDE_DENIED_SECTIONS:
            # Security-sensitive sections must come from explicit config/CLI only.
            # In particular, vault-management admin gate settings must not be
            # disabled or redirected by process environment variables.
            continue
        field_parts = [part.lower() for part in field_raw.split(_LEVEL_SEP) if part]
        if not field_parts:
            continue
        dotted_key = ".".join([section, *field_parts])
        if dotted_key in _ENV_OVERRIDE_DENIED_FIELDS:
            continue
        if section not in result:
            result[section] = {}
        cursor = result[section]
        for part in field_parts[:-1]:
            current = cursor.get(part)
            if not isinstance(current, dict):
                current = {}
                cursor[part] = current
            cursor = current
        cursor[field_parts[-1]] = stripped
    return result


def _dotted_to_nested(overrides: dict[str, object]) -> dict[str, Any]:
    """Конвертирует dotted-path dict в nested dict.

    "api.host" → {"api": {"host": value}}
    None-значения пропускаются (CLI-флаг не задан).
    """
    result: dict[str, Any] = {}
    for key, value in overrides.items():
        if value is None:
            continue
        parts = key.split(".")
        cursor = result
        for part in parts[:-1]:
            current = cursor.get(part)
            if not isinstance(current, dict):
                current = {}
                cursor[part] = current
            cursor = current
        cursor[parts[-1]] = value
    return result


def _deep_merge(
    target: dict[str, Any],
    trace: dict[str, str],
    source_data: dict[str, Any],
    source: str,
    prefix: str = "",
) -> None:
    """Рекурсивно мержит source_data в target, обновляя trace.

    Leaf-значения (не dict) всегда перезаписывают target, если не None.
    Dict-значения мержатся рекурсивно.
    """
    for key, value in source_data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
            _deep_merge(target[key], trace, value, source, full_key)
        else:
            # None как явное значение пропускаем: означает «не задано в этом источнике»
            if value is None:
                continue
            target[key] = value
            trace[full_key] = source


def _fill_default_trace(app_config: AppConfig, trace: dict[str, str]) -> None:
    """Добавляет 'default' для всех leaf-полей AppConfig, не найденных в trace."""
    _fill_model_default_trace(app_config, trace, prefix="")


def _fill_model_default_trace(model: Any, trace: dict[str, str], *, prefix: str) -> None:
    for field_name in type(model).model_fields:
        value = getattr(model, field_name)
        full_key = f"{prefix}.{field_name}" if prefix else field_name
        if hasattr(type(value), "model_fields"):
            _fill_model_default_trace(value, trace, prefix=full_key)
            continue
        if full_key not in trace:
            trace[full_key] = "default"


def _pydantic_error_to_issues(exc: ValidationError) -> list[SettingsIssue]:
    """Конвертирует pydantic.ValidationError в list[SettingsIssue]."""
    issues: list[SettingsIssue] = []
    for error in exc.errors():
        loc_parts = [str(p) for p in error["loc"] if p != "__root__"]
        loc = ".".join(loc_parts) if loc_parts else "<root>"
        error_type = error.get("type", "")
        code = _error_type_to_code(error_type)
        raw_input = error.get("input")
        issues.append(
            SettingsIssue(
                code=code,
                field_path=loc,
                source="validation",
                raw_value=raw_input,
                message=error["msg"],
                hint=f"Check the value of '{loc}' in your config.",
            )
        )
    return issues


def _error_type_to_code(error_type: str) -> str:
    """Маппинг Pydantic error type → settings error code."""
    if "extra_forbidden" in error_type:
        return "settings.unknown_key"
    if "literal_error" in error_type:
        return "settings.validation.enum"
    if any(
        t in error_type
        for t in (
            "greater_than",
            "less_than",
            "greater_than_equal",
            "less_than_equal",
        )
    ):
        return "settings.validation.range"
    return "settings.parse.invalid_value"


__all__ = ["LoadedAppConfig", "load_app_config"]
