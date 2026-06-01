"""
Назначение:
    Базовый набор операций DSL (стадии mapping/normalize/enrich).
"""

from __future__ import annotations

import re
import secrets
import uuid
from functools import lru_cache
from typing import Any, Iterable

from unidecode import unidecode


def _normalize_whitespace(value: object | None, *, empty_to_none: bool = False) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    if empty_to_none and normalized == "":
        return None
    return normalized


@lru_cache(maxsize=128)
def _compile_patterns(patterns: tuple[tuple[str, str], ...]) -> dict[str, re.Pattern[str]]:
    """
    Назначение:
        Кешированная компиляция regex patterns для hot-path операций.
    """
    return {name: re.compile(pattern) for name, pattern in patterns}


@lru_cache(maxsize=128)
def _normalize_mapping(mapping: tuple[tuple[str, Any], ...]) -> dict[str, Any]:
    """
    Назначение:
        Кешированная нормализация mapping (casefold keys) для hot-path операций.
    """
    return {k.casefold(): v for k, v in mapping}


def _normalize_mapping_safe(mapping: dict[str, Any]) -> dict[str, Any]:
    """
    Назначение:
        Нормализовать mapping в casefold-режиме с безопасным fallback для unhashable values.
    """
    try:
        return _normalize_mapping(tuple(sorted(mapping.items())))
    except TypeError:
        return {str(key).casefold(): value for key, value in mapping.items()}


def _as_sequence(value: Any) -> list[Any]:
    """
    Назначение:
        Нормализовать scalar/list/tuple вход в список для list-oriented операций.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _is_blank_scalar(value: Any) -> bool:
    """
    Назначение:
        Проверить, считается ли scalar пустым для tolerant list-операций.
    """
    if value is None:
        return True
    return isinstance(value, str) and value.strip() == ""


def _compile_regex(pattern: str, *, flags: int = 0) -> re.Pattern[str]:
    """
    Назначение:
        Скомпилировать regex с единым helper-контрактом для DSL-операций.
    """
    return re.compile(pattern, flags)


def _resolve_regex_flags(flags: list[str] | tuple[str, ...] | str | None) -> int:
    """
    Назначение:
        Преобразовать декларативные имена regex-флагов в значение для `re`.
    """
    if flags is None:
        return 0
    if isinstance(flags, str):
        names = [flags]
    else:
        names = list(flags)

    resolved = 0
    supported = {
        "ignorecase": re.IGNORECASE,
        "multiline": re.MULTILINE,
        "dotall": re.DOTALL,
        "ascii": re.ASCII,
    }
    for name in names:
        normalized = str(name).strip().lower()
        if normalized not in supported:
            raise ValueError(f"Unsupported regex flag: {name}")
        resolved |= supported[normalized]
    return resolved


def _normalize_bool_literals(values: Iterable[Any], *, casefold: bool, trim: bool) -> set[Any]:
    """
    Назначение:
        Нормализовать набор bool-литералов для декларативного parse_bool.
    """
    normalized: set[Any] = set()
    for value in values:
        current = value
        if isinstance(current, str):
            if trim:
                current = current.strip()
            if casefold:
                current = current.casefold()
        normalized.add(current)
    return normalized


def _coerce_nested_ops(raw_ops: Any) -> list[Any]:
    """
    Назначение:
        Преобразовать args.ops в список OperationCall для nested list-операций.

    Примечание:
        OperationCall валидируется здесь локально, потому что args хранится как dict[str, Any]
        и вложенные operation payload не проходят Pydantic-валидацию на границе spec-модели.
    """
    from connector.domain.dsl.specs import OperationCall

    if not isinstance(raw_ops, list):
        raise ValueError("ops must be a list")
    return [OperationCall.model_validate(item) for item in raw_ops]


def op_trim(value: Any, **_: Any) -> str | None:
    """
    Назначение:
        Нормализует пробелы и возвращает None для пустых строк.
    """

    return _normalize_whitespace(value, empty_to_none=True)


def op_lower(value: Any, **_: Any) -> str | None:
    """
    Назначение:
        Привести строку к нижнему регистру.
    """

    if value is None:
        return None
    text = str(value)
    return text.lower()


def op_title(value: Any, **_: Any) -> str | None:
    """
    Назначение:
        Привести каждое слово строки к title case.
    """
    if value is None:
        return None
    return str(value).title()


def op_capitalize(value: Any, **_: Any) -> str | None:
    """
    Назначение:
        Привести строку к capitalize-форме.
    """
    if value is None:
        return None
    return str(value).capitalize()


def op_transliterate(value: Any, **_: Any) -> str | None:
    """
    Назначение:
        Детерминированно преобразовать строку в ASCII-представление.

    Контракт:
        - `None -> None`
        - пустая строка сохраняется пустой строкой
        - ASCII-строка возвращается без изменений
        - non-ASCII строка преобразуется через `unidecode`
    """
    if value is None:
        return None
    text = str(value)
    if text == "":
        return ""
    if text.isascii():
        return text
    return unidecode(text)


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


def op_parse_bool(
    value: Any,
    *,
    true_values: list[Any],
    false_values: list[Any],
    casefold: bool = True,
    trim: bool = True,
) -> bool | None:
    """
    Назначение:
        Преобразовать декларативно заданные source-литералы в canonical bool.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value

    current = value
    if isinstance(current, str):
        if trim:
            current = current.strip()
        if current == "":
            return None
        if casefold:
            current = current.casefold()

    true_set = _normalize_bool_literals(true_values, casefold=casefold, trim=trim)
    false_set = _normalize_bool_literals(false_values, casefold=casefold, trim=trim)
    if true_set & false_set:
        raise ValueError("parse_bool true_values and false_values must not overlap")
    if current in true_set:
        return True
    if current in false_set:
        return False
    raise ValueError("Invalid boolean value")


def op_to_string(value: Any, **_: Any) -> str | None:
    """
    Назначение:
        Преобразовать значение в строку (trim), пустую строку -> None.
    """

    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def op_default_password(value: Any, **_: Any) -> Any:
    """
    Назначение:
        Вернуть случайный пароль, если значение пустое.

    Алгоритм:
        Генерирует строку вида <буква><uuid_hex>, которая гарантированно
        начинается с латинской буквы (a–f) — удовлетворяет политике
        startWithAlphabet при любом результате uuid4().
    """
    if value is not None and not (isinstance(value, str) and value.strip() == ""):
        return value
    prefix = secrets.choice("abcdef")
    return prefix + uuid.uuid4().hex


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


def op_pick_when_blank(
    values: Any,
    *,
    guard_index: int,
    value_index: int,
    else_value: Any | None = None,
) -> Any:
    """
    Назначение:
        Вернуть элемент `value_index`, только если guard-элемент пустой.

    Контракт:
        - вход трактуется как tolerant sequence;
        - blank guard (`None` или пустая строка) разрешает возврат целевого значения;
        - непустой guard возвращает `else_value` без ошибок.
    """
    sequence = _as_sequence(values)
    guard = sequence[guard_index] if 0 <= guard_index < len(sequence) else None
    if not _is_blank_scalar(guard):
        return else_value
    if 0 <= value_index < len(sequence):
        return sequence[value_index]
    return None


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


def op_first(value: Any, **_: Any) -> Any:
    """
    Назначение:
        Вернуть первый элемент последовательности или scalar как есть.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def op_last(value: Any, **_: Any) -> Any:
    """
    Назначение:
        Вернуть последний элемент последовательности или scalar как есть.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return value[-1] if value else None
    return value


def op_at(value: Any, *, index: int) -> Any:
    """
    Назначение:
        Вернуть элемент последовательности по индексу.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        try:
            return value[index]
        except IndexError:
            return None
    return value if index == 0 else None


def op_substring(value: Any, *, start: int, length: int | None = None) -> str | None:
    """
    Назначение:
        Универсально извлечь подстроку из строкового значения.

    Контракт:
        - `None -> None`
        - если `length` не задан, возвращается остаток строки от `start`
        - выход за диапазон не считается ошибкой
    """
    if value is None:
        return None
    text = str(value)
    if length is None:
        return text[start:]
    if length < 0:
        raise ValueError("length must be >= 0")
    return text[start : start + length]


def op_compact(value: Any, **_: Any) -> list[Any]:
    """
    Назначение:
        Удалить из последовательности пустые/None значения.
    """
    return [item for item in _as_sequence(value) if not _is_blank_scalar(item)]


def op_unique(value: Any, **_: Any) -> list[Any]:
    """
    Назначение:
        Вернуть значения без дублей с сохранением исходного порядка.
    """
    result: list[Any] = []
    seen: list[Any] = []
    for item in _as_sequence(value):
        if item in seen:
            continue
        seen.append(item)
        result.append(item)
    return result


def op_count(value: Any, **_: Any) -> int:
    """
    Назначение:
        Вернуть количество элементов в tolerant list-контракте.
    """
    if value is None:
        return 0
    if isinstance(value, (list, tuple)):
        return len(value)
    return 1


def op_map_each(value: Any, *, ops: list[Any]) -> list[Any] | None:
    """
    Назначение:
        Применить вложенную цепочку DSL-операций к каждому элементу последовательности.
    """
    if value is None:
        return None

    from connector.domain.dsl.engine import TransformationEngine

    nested_ops = _coerce_nested_ops(ops)
    engine = TransformationEngine.with_core_ops()
    result: list[Any] = []
    for item in _as_sequence(value):
        nested = engine.apply(item, nested_ops)
        if nested.issues:
            first_issue = nested.issues[0]
            raise ValueError(first_issue.message)
        result.append(nested.value)
    return result


def op_filter_regex(
    value: Any,
    *,
    pattern: str,
    flags: list[str] | tuple[str, ...] | str | None = None,
    match_mode: str = "search",
) -> list[Any]:
    """
    Назначение:
        Оставить только элементы, совпавшие с заданным regex.
    """
    compiled = _compile_regex(pattern, flags=_resolve_regex_flags(flags))
    if match_mode not in {"search", "fullmatch"}:
        raise ValueError("match_mode must be 'search' or 'fullmatch'")
    matcher = compiled.search if match_mode == "search" else compiled.fullmatch
    return [item for item in _as_sequence(value) if matcher(str(item))]


def op_contains_non_ascii(value: Any, **_: Any) -> bool | None:
    """
    Назначение:
        Проверить, содержит ли строковое значение хотя бы один non-ASCII символ.

    Контракт:
        - `None -> None`
        - результат используется как predicate и не меняет само значение
    """
    if value is None:
        return None
    return not str(value).isascii()


def op_is_blank(value: Any, **_: Any) -> bool:
    """
    Назначение:
        Проверить, считается ли значение пустым в tolerant DSL-контракте.

    Контракт:
        - `None` и пустые/пробельные строки считаются blank;
        - bool/числа сами по себе blank не считаются.
    """
    return _is_blank_scalar(value)


def op_reject_regex(
    value: Any,
    *,
    pattern: str,
    flags: list[str] | tuple[str, ...] | str | None = None,
    match_mode: str = "search",
) -> list[Any]:
    """
    Назначение:
        Исключить элементы, совпавшие с заданным regex.
    """
    compiled = _compile_regex(pattern, flags=_resolve_regex_flags(flags))
    if match_mode not in {"search", "fullmatch"}:
        raise ValueError("match_mode must be 'search' or 'fullmatch'")
    matcher = compiled.search if match_mode == "search" else compiled.fullmatch
    return [item for item in _as_sequence(value) if not matcher(str(item))]


def op_build_delimited_key(
    values: Any,
    *,
    sep: str = "|",
    strict: bool = True,
) -> str | None:
    """
    Назначение:
        Собрать составной ключ из списка значений с фиксированным разделителем.

    Поведение:
        - strict=True: пустые/None значения запрещены.
        - strict=False: пустые элементы пропускаются.
    """

    if values is None:
        if strict:
            raise ValueError("build_delimited_key requires non-empty values")
        return None
    if not isinstance(values, (list, tuple)):
        values = [values]

    parts: list[str] = []
    for value in values:
        if value is None:
            if strict:
                raise ValueError("build_delimited_key contains None value")
            continue
        part = str(value).strip()
        if part == "":
            if strict:
                raise ValueError("build_delimited_key contains empty value")
            continue
        parts.append(part)

    if not parts:
        if strict:
            raise ValueError("build_delimited_key produced empty result")
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


def op_digits_only(value: Any, **_: Any) -> str | None:
    """
    Назначение:
        Оставить в строковом значении только цифры.
    """
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits or None


def op_strip_non_alnum(value: Any, **_: Any) -> str | None:
    """
    Назначение:
        Удалить из строкового значения все символы, кроме ASCII-букв и цифр.
    """
    if value is None:
        return None
    return "".join(ch for ch in str(value) if ch.isascii() and ch.isalnum())


def op_random_digits(_: Any, *, length: int) -> str:
    """
    Назначение:
        Сгенерировать случайную строку из цифр заданной длины.

    Контракт:
        - входное значение не участвует в генерации
        - результат состоит только из цифр
        - длина результата строго совпадает с `length`
    """
    if length <= 0:
        raise ValueError("length must be > 0")
    return "".join(secrets.choice("0123456789") for _ in range(length))


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
    # Use cached compilation for hot-path performance
    compiled = _compile_patterns(tuple(sorted(patterns.items())))
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


def op_format_mask(value: Any, *, mask: str, placeholder: str = "#") -> str | None:
    """
    Назначение:
        Отформатировать последовательность символов по declarative mask.

    Контракт:
        - количество входных символов должно совпадать с количеством placeholder в mask;
        - операция ожидает уже канонизированное значение и не извлекает доменные символы сама.
    """
    if value is None:
        return None
    raw = str(value)
    if raw == "":
        return None
    placeholder_count = mask.count(placeholder)
    if placeholder_count == 0:
        raise ValueError("mask must contain at least one placeholder")
    if len(raw) != placeholder_count:
        raise ValueError(
            f"mask expects {placeholder_count} characters, got {len(raw)}"
        )

    chars = iter(raw)
    result: list[str] = []
    for char in mask:
        if char == placeholder:
            result.append(next(chars))
        else:
            result.append(char)
    return "".join(result)


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
        mapping = _normalize_mapping_safe(mapping)
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
