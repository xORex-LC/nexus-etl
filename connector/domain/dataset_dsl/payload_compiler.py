"""
Назначение:
    SinkSpec-driven payload builder — generic payload compilation из SinkSpec field metadata.

Граница ответственности:
    - Owns: валидация required полей, field name mapping, orchestration output serialization, defaults.
    - Does NOT: секреты (hydration — ответственность OperationApplyAdapter).
"""

from __future__ import annotations

from typing import Any

from connector.domain.dataset_dsl.field_serialization import serialize_sink_field_value
from connector.domain.transform_dsl.specs import SinkSpec


class SinkDrivenPayloadBuilder:
    """
    Назначение:
        Generic payload builder, использующий SinkSpec field metadata.

    Контракт:
        - Для каждого SinkFieldSpec из sink_spec.sink.fields:
          - field.name → ключ в source dict
          - field.target or field.name → ключ в payload
          - field.type + field.serialize → delegated field serialization
          - field.required (кроме conditional_fields) → validate non-empty
        - conditional_fields → skip field если value is None/empty
        - defaults → inject constant values в payload
        - system_fields → skip (generated, не в payload)

    Реализует PayloadBuilder = Callable[[dict[str, Any]], dict[str, Any]].
    """

    def __init__(
        self,
        sink_spec: SinkSpec,
        defaults: dict[str, Any] | None = None,
        conditional_fields: list[str] | None = None,
    ) -> None:
        self._defaults = defaults or {}
        self._conditional = set(conditional_fields or [])
        # Fields whose target key is overridden by defaults — skip entirely
        self._default_targets = set(self._defaults)
        self._fields = [
            f for f in sink_spec.sink.fields
            if (f.target or f.name) not in self._default_targets
        ]

    def __call__(self, source: dict[str, Any]) -> dict[str, Any]:
        self._validate_required(source)
        payload = self._build_payload(source)
        for key, value in self._defaults.items():
            payload[key] = value
        return payload

    def _validate_required(self, source: dict[str, Any]) -> None:
        missing = [
            f.name
            for f in self._fields
            if f.required
            and not f.nullable
            and f.name not in self._conditional
            and source.get(f.name) in (None, "")
        ]
        if missing:
            raise ValueError(
                f"Missing required fields for payload: {', '.join(missing)}"
            )

    def _build_payload(self, source: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for field in self._fields:
            value = source.get(field.name)

            if field.name in self._conditional:
                if value in (None, ""):
                    continue

            target_key = field.target or field.name

            if value is None and field.nullable:
                payload[target_key] = None
            else:
                payload[target_key] = serialize_sink_field_value(field, value)

        return payload
