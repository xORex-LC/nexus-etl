"""
Назначение:
    Реестр операций DSL (общий для всех стадий).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

OperationFunc = Callable[..., Any]


@dataclass(frozen=True)
class Operation:
    """
    Назначение:
        Описание зарегистрированной операции.
    """

    name: str
    func: OperationFunc


class OperationRegistry:
    """
    Назначение/ответственность:
        Хранит операции DSL и выдаёт их по имени.
    """

    def __init__(self) -> None:
        self._ops: dict[str, Operation] = {}

    def register(self, name: str, func: OperationFunc, *, allow_override: bool = False) -> None:
        if not allow_override and name in self._ops:
            raise ValueError(f"Operation '{name}' already registered")
        self._ops[name] = Operation(name=name, func=func)

    def get(self, name: str) -> Operation | None:
        return self._ops.get(name)

    def require(self, name: str) -> Operation:
        op = self._ops.get(name)
        if op is None:
            raise KeyError(name)
        return op

    def apply(self, name: str, value: Any, **kwargs: Any) -> Any:
        op = self.require(name)
        return op.func(value, **kwargs)


def register_core_ops(registry: OperationRegistry) -> OperationRegistry:
    """
    Назначение:
        Зарегистрировать базовый набор операций DSL.
    """
    from connector.domain.dsl.ops import (
        op_trim,
        op_lower,
        op_upper,
        op_title,
        op_capitalize,
        op_to_int,
        op_to_float,
        op_to_bool,
        op_parse_bool,
        op_to_string,
        op_int_if_digits,
        op_uuid,
        op_default_uuid,
        op_default_prefixed_uuid,
        op_default_password,
        op_copy,
        op_const,
        op_coalesce,
        op_concat,
        op_build_delimited_key,
        op_first,
        op_last,
        op_at,
        op_compact,
        op_unique,
        op_count,
        op_map_each,
        op_extract_patterns,
        op_regex_extract,
        op_filter_regex,
        op_reject_regex,
        op_regex_replace,
        op_split_name,
        op_split,
        op_digits_only,
        op_format_mask,
        op_parse_kv_pairs,
        op_map_dict,
        op_build_link_keys,
        op_equals_path,
    )

    registry.register("trim", op_trim)
    registry.register("lower", op_lower)
    registry.register("upper", op_upper)
    registry.register("title", op_title)
    registry.register("capitalize", op_capitalize)
    registry.register("to_int", op_to_int)
    registry.register("to_float", op_to_float)
    registry.register("to_bool", op_to_bool)
    registry.register("parse_bool", op_parse_bool)
    registry.register("to_string", op_to_string)
    registry.register("int_if_digits", op_int_if_digits)
    registry.register("uuid", op_uuid)
    registry.register("default_uuid", op_default_uuid)
    registry.register("default_prefixed_uuid", op_default_prefixed_uuid)
    registry.register("default_password", op_default_password)
    registry.register("copy", op_copy)
    registry.register("const", op_const)
    registry.register("coalesce", op_coalesce)
    registry.register("concat", op_concat)
    registry.register("build_delimited_key", op_build_delimited_key)
    registry.register("first", op_first)
    registry.register("last", op_last)
    registry.register("at", op_at)
    registry.register("compact", op_compact)
    registry.register("unique", op_unique)
    registry.register("count", op_count)
    registry.register("map_each", op_map_each)
    registry.register("extract_patterns", op_extract_patterns)
    registry.register("split", op_split)
    registry.register("split_name", op_split_name)
    registry.register("regex_extract", op_regex_extract)
    registry.register("filter_regex", op_filter_regex)
    registry.register("reject_regex", op_reject_regex)
    registry.register("regex_replace", op_regex_replace)
    registry.register("digits_only", op_digits_only)
    registry.register("format_mask", op_format_mask)
    registry.register("parse_kv_pairs", op_parse_kv_pairs)
    registry.register("map_dict", op_map_dict)
    registry.register("build_link_keys", op_build_link_keys)
    registry.register("equals_path", op_equals_path)
    return registry
