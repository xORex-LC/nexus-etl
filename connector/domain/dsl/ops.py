"""
Назначение:
    Базовый набор операций DSL (стадии mapping/normalize/enrich).
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Iterable

from connector.domain.transform.common import normalize_text


def op_trim(value: Any, **_: Any) -> str | None:
    """
    Назначение:
        Нормализует пробелы и возвращает None для пустых строк.
    """

    return normalize_text(value, empty_to_none=True)


def op_lower(value: Any, **_: Any) -> str | None:
    """
    Назначение:
        Привести строку к нижнему регистру.
    """

    if value is None:
        return None
    text = str(value)
    return text.lower()


def op_upper(value: Any, **_: Any) -> str | None:
    """
    Назначение:
        Привести строку к верхнему регистру.
    """

    if value is None:
        return None
    text = str(value)
    return text.upper()


def op_to_int(value: Any, **_: Any) -> int | None:
    """
    Назначение:
        Преобразовать значение в int (строго).
    """

    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean is not an int")
    if isinstance(value, int):
        return value
    raw = str(value).strip()
    if raw == "":
        raise ValueError("Empty int value")
    return int(raw)


def op_to_float(value: Any, **_: Any) -> float | None:
    """
    Назначение:
        Преобразовать значение в float (строго).
    """

    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean is not a float")
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip()
    if raw == "":
        raise ValueError("Empty float value")
    return float(raw)


def op_to_bool(value: Any, **_: Any) -> bool | None:
    """
    Назначение:
        Преобразовать значение в bool (строго: true/false).
    """

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError("Invalid boolean value")


def op_int_if_digits(value: Any, **_: Any) -> int | str | None:
    """
    Назначение:
        Преобразовать строку в int, если это число; иначе вернуть строку.
    """

    if value is None:
        return None
    if isinstance(value, int):
        return value
    raw = str(value).strip()
    if raw == "":
        return None
    if raw.isdigit():
        return int(raw)
    return raw


def op_uuid(_: Any, **kwargs: Any) -> str:
    """
    Назначение:
        Сгенерировать UUID.
    """
    _ = kwargs
    return str(uuid.uuid4())


def op_default_uuid(value: Any, **_: Any) -> Any:
    """
    Назначение:
        Вернуть UUID, если значение пустое.
    """

    if value is None:
        return op_uuid(None)
    if isinstance(value, str) and value.strip() == "":
        return op_uuid(None)
    return value


def op_default_prefixed_uuid(value: Any, *, prefix: str = "") -> Any:
    """
    Назначение:
        Вернуть префикс+UUID, если значение пустое.
    """

    if value is None or (isinstance(value, str) and value.strip() == ""):
        return f"{prefix}{uuid.uuid4().hex[:8]}"
    return value


def op_copy(value: Any, **_: Any) -> Any:
    """
    Назначение:
        Возвращает значение без изменений.
    """

    return value


def op_const(_: Any, *, value: Any) -> Any:
    """
    Назначение:
        Возвращает константу, заданную в аргументах.
    """

    return value


def op_coalesce(values: Any, *, default: Any | None = None) -> Any:
    """
    Назначение:
        Возвращает первое непустое значение из списка.
    """

    candidates: Iterable[Any]
    if isinstance(values, (list, tuple)):
        candidates = values
    else:
        candidates = [values]
    for value in candidates:
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        return value
    return default


def op_concat(values: Any, *, sep: str = "") -> str | None:
    """
    Назначение:
        Склеивает список значений в строку.
    """

    if values is None:
        return None
    if not isinstance(values, (list, tuple)):
        values = [values]
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        parts.append(str(value))
    if not parts:
        return None
    return sep.join(parts)


def op_split(value: Any, *, sep: str = ",") -> list[str] | None:
    """
    Назначение:
        Делит строку по разделителю.
    """

    if value is None:
        return None
    return [part for part in str(value).split(sep)]


def op_split_name(
    value: Any,
    *,
    fields: list[str],
    separator: str = " ",
    allow_comma_format: bool = False,
    max_parts: int | None = None,
) -> dict[str, str | None] | None:
    """
    Назначение:
        Универсально разбить составное поле на части и разложить по fields.
    """

    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts: list[str]
    if allow_comma_format and "," in raw:
        left, rest = raw.split(",", 1)
        parts = [left.strip()]
        rest_parts = [p for p in rest.strip().split(separator) if p]
        parts.extend(rest_parts)
    else:
        parts = [p for p in raw.split(separator) if p]
    if max_parts is not None:
        parts = parts[:max_parts]
    result: dict[str, str | None] = {}
    for idx, field in enumerate(fields):
        result[field] = parts[idx] if idx < len(parts) else None
    return result


def op_extract_patterns(
    values: Any,
    *,
    patterns: dict[str, str],
    split_pattern: str = r"[;|,]",
    keyed_prefixes: dict[str, str] | None = None,
) -> dict[str, str | None] | None:
    """
    Назначение:
        Извлечь значения по regex-паттернам из набора строк.
    """

    if values is None:
        return None
    if not isinstance(values, (list, tuple)):
        candidates = [values]
    else:
        candidates = list(values)
    result: dict[str, str | None] = {name: None for name in patterns}
    keyed_prefixes = keyed_prefixes or {}
    compiled = {name: re.compile(pattern) for name, pattern in patterns.items()}
    for candidate in candidates:
        if not candidate:
            continue
        for token in re.split(split_pattern, str(candidate)):
            token = token.strip()
            if not token:
                continue
            lower = token.lower()
            for name, prefix in keyed_prefixes.items():
                if lower.startswith(prefix.lower()):
                    _, value = token.split("=", 1) if "=" in token else (prefix, token[len(prefix):])
                    match = compiled[name].search(value)
                    if match:
                        result[name] = match.group(0)
                    break
            for name, pattern in compiled.items():
                if result.get(name):
                    continue
                match = pattern.search(token)
                if match:
                    result[name] = match.group(0)
    return result


def op_regex_extract(value: Any, *, pattern: str, group: int = 0) -> str | None:
    """
    Назначение:
        Извлекает группу регулярного выражения.
    """

    if value is None:
        return None
    match = re.search(pattern, str(value))
    if not match:
        return None
    try:
        return match.group(group)
    except IndexError:
        return None


def op_regex_replace(value: Any, *, pattern: str, repl: str) -> str | None:
    """
    Назначение:
        Заменяет совпадения регулярного выражения.
    """

    if value is None:
        return None
    return re.sub(pattern, repl, str(value))


def op_parse_kv_pairs(
    value: Any,
    *,
    sep: str = ";",
    kv_sep: str = "=",
    keys: dict[str, str],
) -> dict[str, str | None] | None:
    """
    Назначение:
        Разобрать строку key=value;key2=value2 и вернуть dict по mapping keys.
    """

    if value is None:
        return None
    raw = str(value)
    if not raw:
        return None
    pairs: dict[str, str] = {}
    for token in raw.split(sep):
        if kv_sep not in token:
            continue
        key, val = token.split(kv_sep, 1)
        key = key.strip().lower()
        val = val.strip()
        if key:
            pairs[key] = val
    if not pairs:
        return None
    result: dict[str, str | None] = {}
    for target, source_key in keys.items():
        result[target] = pairs.get(source_key)
    return result


def op_map_dict(value: Any, *, mapping: dict[str, Any], casefold: bool = False) -> Any:
    """
    Назначение:
        Преобразовать значение через словарь.
    """

    if value is None:
        return None
    key = str(value)
    if casefold:
        key = key.casefold()
        mapping = {k.casefold(): v for k, v in mapping.items()}
    return mapping.get(key)


def op_build_link_keys(
    value: Any,
    *,
    field: str,
    link_type: str = "match_key",
) -> dict[str, dict[str, str]] | None:
    """
    Назначение:
        Построить link_keys для дальнейших lookup-операций.
    """

    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if link_type == "match_key":
        return {field: {"match_key": raw}}
    return {field: {link_type: raw}}


def _read_path(value: Any, path: str) -> Any:
    """
    Назначение:
        Прочитать вложенное поле по пути "a.b.c" из dict/объекта.
    """

    current = value
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def op_equals_path(value: Any, *, left: str, right: str) -> bool:
    """
    Назначение:
        Сравнить два значения по путям в контексте.
    """

    return _read_path(value, left) == _read_path(value, right)
