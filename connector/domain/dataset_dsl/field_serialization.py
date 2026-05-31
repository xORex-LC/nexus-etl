"""
Назначение:
    Sink field output serialization поверх canonical/cast значений payload boundary.

Граница ответственности:
    - Owns: target-side field serialization, описанную в SinkFieldSpec.serialize.
    - Does NOT: required/nullable validation, defaults injection, field iteration, secret hydration.
"""

from __future__ import annotations

from typing import Any, Callable

from connector.domain.dataset_dsl.coercions import (
    to_bool,
    to_float_or_none,
    to_int_or_none,
)
from connector.domain.transform_dsl.specs import SinkFieldSpec

_COERCIONS: dict[str, Callable[[Any], Any]] = {
    "string": lambda v: v,
    "bool": to_bool,
    "int": to_int_or_none,
    "float": to_float_or_none,
    "object": lambda v: v,
    "list": lambda v: v,
}


def serialize_sink_field_value(field: SinkFieldSpec, value: Any) -> Any:
    """
    Назначение:
        Преобразовать значение поля в payload-ready representation по sink metadata.

    Контракт:
        - Сначала применяется canonical field coercion по `field.type`.
        - Затем применяется output serialization по `field.serialize`, если она объявлена.
        - `nullable` и required-check остаются за вызывающим orchestration layer.
    """
    coerce = _COERCIONS.get(field.type, lambda v: v)
    canonical = coerce(value)
    return _apply_output_serialization(field, canonical)


def _apply_output_serialization(field: SinkFieldSpec, canonical: Any) -> Any:
    serialize = field.serialize
    if serialize is None or serialize.as_mode == "native":
        return canonical
    if field.type != "bool":
        raise ValueError(f"serialize is not supported for sink type {field.type!r}")
    if canonical is None:
        return None
    if not isinstance(canonical, bool):
        raise ValueError(
            f"serialize requires canonical bool value for field {field.name!r}, "
            f"got {type(canonical).__name__}"
        )
    mapping = serialize.map
    if mapping is None:
        raise ValueError("serialize.map is required for as=literal_map")
    return mapping.true if canonical else mapping.false
