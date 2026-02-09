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

    def register(self, name: str, func: OperationFunc) -> None:
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
        op_to_int,
        op_to_float,
        op_to_bool,
        op_int_if_digits,
        op_uuid,
        op_default_uuid,
        op_default_prefixed_uuid,
        op_copy,
        op_const,
        op_coalesce,
        op_concat,
        op_extract_patterns,
        op_regex_extract,
        op_regex_replace,
        op_split_name,
        op_split,
        op_parse_kv_pairs,
        op_map_dict,
        op_build_link_keys,
        op_equals_path,
    )

    registry.register("trim", op_trim)
    registry.register("lower", op_lower)
    registry.register("upper", op_upper)
    registry.register("to_int", op_to_int)
    registry.register("to_float", op_to_float)
    registry.register("to_bool", op_to_bool)
    registry.register("int_if_digits", op_int_if_digits)
    registry.register("uuid", op_uuid)
    registry.register("default_uuid", op_default_uuid)
    registry.register("default_prefixed_uuid", op_default_prefixed_uuid)
    registry.register("copy", op_copy)
    registry.register("const", op_const)
    registry.register("coalesce", op_coalesce)
    registry.register("concat", op_concat)
    registry.register("extract_patterns", op_extract_patterns)
    registry.register("split", op_split)
    registry.register("split_name", op_split_name)
    registry.register("regex_extract", op_regex_extract)
    registry.register("regex_replace", op_regex_replace)
    registry.register("parse_kv_pairs", op_parse_kv_pairs)
    registry.register("map_dict", op_map_dict)
    registry.register("build_link_keys", op_build_link_keys)
    registry.register("equals_path", op_equals_path)
    return registry
