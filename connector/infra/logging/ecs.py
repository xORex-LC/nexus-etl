"""ECS transform — финальный processor JSON-формы для структурных логов.

Модуль владеет преобразованием внутренних structlog event dictionaries в JSON-поля,
совместимые с Elastic Common Schema. Это единственное runtime-место, где короткие
observability aliases превращаются в dotted ECS или project-specific keys.

Границы ответственности:
    - Нормализовать structlog event dictionaries в ECS-совместимые JSON dictionaries.
    - Резолвить короткие field aliases через machine-readable taxonomy.
    - Удерживать неизвестные бизнес-поля под `labels.*`.

Вне ответственности:
    - Redaction секретов перед rendering.
    - Выбор момента, когда бизнес-компонент должен эмитить log event.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

import yaml

ECS_VERSION = "8.11"
SERVICE_NAME = "nexus-etl"

STRUCTURAL_ROOTS = frozenset(
    {
        "@timestamp",
        "component",
        "ecs",
        "error",
        "event",
        "exception",
        "file",
        "host",
        "http",
        "labels",
        "log",
        "message",
        "nexus",
        "process",
        "service",
        "span",
        "tags",
        "trace",
        "url",
    }
)

_TAXONOMY_FIELDS_ROOT = (
    Path(__file__).resolve().parents[2]
    / "common"
    / "observability"
    / "taxonomy"
    / "fields"
)
_LABEL_KEY_RE = re.compile(r"[^A-Za-z0-9_]+")
_CANONICAL_FIELD_KEYS: frozenset[str] | None = None
_FIELD_ALIASES: dict[str, str] | None = None


def ecs_transform(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Отрендерить один structlog event dictionary в проектный ECS JSON profile."""
    aliases = field_aliases()
    known_keys = canonical_field_keys()
    rendered: dict[str, Any] = {
        "ecs.version": ECS_VERSION,
        "service.name": SERVICE_NAME,
    }
    pending_error: dict[str, Any] = {}

    for raw_key, value in event_dict.items():
        if value is None:
            continue
        if raw_key == "timestamp":
            rendered["@timestamp"] = value
            continue
        if raw_key == "event":
            rendered["message"] = value
            continue
        if raw_key == "level":
            rendered["log.level"] = str(value).lower()
            continue
        if raw_key == "logger":
            rendered["log.logger"] = value
            continue
        if raw_key == "exception":
            pending_error.update(_exception_error_fields(value))
            continue

        canonical_key = aliases.get(raw_key)
        if canonical_key is not None:
            rendered[canonical_key] = value
            continue

        if raw_key in known_keys:
            rendered[raw_key] = value
            continue

        if raw_key in {"exc_info", "stack_info"}:
            continue

        _put_label(rendered, raw_key, value)

    _merge_error_fields(rendered, pending_error)
    rendered.setdefault("message", "")
    rendered.setdefault("log.level", "info")
    rendered.setdefault("log.logger", _logger_name(_logger))
    return rendered


def field_aliases() -> dict[str, str]:
    """Вернуть маппинг коротких aliases, загруженный из field taxonomy."""
    global _FIELD_ALIASES
    if _FIELD_ALIASES is None:
        _FIELD_ALIASES = _load_field_registry()[1]
    return dict(_FIELD_ALIASES)


def canonical_field_keys() -> frozenset[str]:
    """Вернуть канонические dotted field keys, загруженные из field taxonomy."""
    global _CANONICAL_FIELD_KEYS
    if _CANONICAL_FIELD_KEYS is None:
        _CANONICAL_FIELD_KEYS = _load_field_registry()[0]
    return _CANONICAL_FIELD_KEYS


def validate_field_name_for_event_contract(key: str) -> None:
    """Отклонить ECS structural roots и dotted keys в `ObservabilityEvent.fields`."""
    if "." in key:
        raise ValueError(
            f"ObservabilityEvent field keys must be aliases, not dotted keys: {key}"
        )
    if key in STRUCTURAL_ROOTS:
        raise ValueError(
            f"ObservabilityEvent field key uses reserved structural root: {key}"
        )


def _load_field_registry() -> tuple[frozenset[str], dict[str, str]]:
    canonical_keys: set[str] = set()
    aliases: dict[str, str] = {}
    for path in sorted(_TAXONOMY_FIELDS_ROOT.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for entry in raw.get("fields") or ():
            canonical_key = str(entry["key"])
            canonical_keys.add(canonical_key)
            for alias in entry.get("aliases") or ():
                alias_key = str(alias)
                previous = aliases.setdefault(alias_key, canonical_key)
                if previous != canonical_key:
                    raise ValueError(
                        f"Field alias '{alias_key}' maps to both '{previous}' and "
                        f"'{canonical_key}'"
                    )
    return frozenset(canonical_keys), aliases


def _merge_error_fields(
    rendered: dict[str, Any], exception_fields: Mapping[str, Any]
) -> None:
    manual_code = rendered.get("error.code")
    for key, value in exception_fields.items():
        if value is not None:
            rendered[key] = value
    if manual_code is not None:
        rendered["error.code"] = manual_code


def _exception_error_fields(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"error.stack_trace": value}
    if isinstance(value, Mapping):
        return _exception_mapping_fields(value)
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, Mapping):
            fields = _exception_mapping_fields(first)
            stack_trace = _stack_trace_from_exception_list(value)
            if stack_trace:
                fields["error.stack_trace"] = stack_trace
            return fields
    return {"error.stack_trace": _coerce_label_value(value)}


def _exception_mapping_fields(value: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    exc_type = value.get("type") or value.get("exc_type")
    exc_message = value.get("value") or value.get("message") or value.get("exc_value")
    if exc_type is not None:
        fields["error.type"] = str(exc_type)
    if exc_message is not None:
        fields["error.message"] = str(exc_message)
    stack_trace = value.get("stack") or value.get("traceback")
    if stack_trace is not None:
        fields["error.stack_trace"] = _coerce_label_value(stack_trace)
    return fields


def _stack_trace_from_exception_list(value: list[Any]) -> str | None:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _put_label(rendered: dict[str, Any], key: str, value: Any) -> None:
    label_key = f"labels.{_label_suffix(key)}"
    rendered[label_key] = _coerce_label_value(value)


def _label_suffix(key: str) -> str:
    normalized = _LABEL_KEY_RE.sub("_", key.strip().replace(".", "_")).strip("_")
    return normalized or "field"


def _coerce_label_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, list) and all(
        isinstance(item, (str, int, float, bool)) or item is None for item in value
    ):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _logger_name(logger: Any) -> str:
    name = getattr(logger, "name", None)
    if isinstance(name, str) and name:
        return name
    return "unknown"


__all__ = [
    "ECS_VERSION",
    "STRUCTURAL_ROOTS",
    "canonical_field_keys",
    "ecs_transform",
    "field_aliases",
    "validate_field_name_for_event_contract",
]
