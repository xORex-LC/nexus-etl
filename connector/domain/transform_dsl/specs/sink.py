"""
Назначение:
    Transform DSL: спецификации sink-модели.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from connector.domain.dsl.specs._base import DslBaseModel


class SinkBoolLiteralMapSpec(DslBaseModel):
    """
    Назначение:
        Явное соответствие canonical bool -> target literal.

    Контракт:
        - Оба значения обязательны.
        - Ключи `true`/`false` нормализуются из YAML, даже если парсер вернул bool-ключи.
    """

    true: Any
    false: Any

    @model_validator(mode="before")
    @classmethod
    def _normalize_bool_keys(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if True in normalized and "true" not in normalized:
            normalized["true"] = normalized.pop(True)
        if False in normalized and "false" not in normalized:
            normalized["false"] = normalized.pop(False)
        return normalized


class SinkFieldSerializeSpec(DslBaseModel):
    """
    Назначение:
        Декларативное описание output-serialization для payload field.

    Контракт:
        - `as: native` оставляет canonical value без доп. сериализации.
        - `as: literal_map` требует map для target-specific literal представления.
    """

    as_mode: Literal["native", "literal_map"] = Field(alias="as")
    map: SinkBoolLiteralMapSpec | None = None

    model_config = {"extra": "forbid", "populate_by_name": True}

    @model_validator(mode="after")
    def _validate_mode_contract(self) -> "SinkFieldSerializeSpec":
        if self.as_mode == "native":
            if self.map is not None:
                raise ValueError("serialize.map is not allowed for as=native")
            return self
        if self.map is None:
            raise ValueError("serialize.map is required for as=literal_map")
        return self


class SinkFieldSpec(DslBaseModel):
    """
    Назначение:
        Декларативное описание поля sink-модели.
    """

    name: str
    type: Literal["string", "int", "float", "bool", "object", "list"]
    required: bool = False
    nullable: bool = False
    target: str | None = None
    generated: bool = False
    serialize: SinkFieldSerializeSpec | None = None

    @model_validator(mode="after")
    def _validate_serialize_contract(self) -> "SinkFieldSpec":
        if self.serialize is None:
            return self
        if self.type != "bool":
            raise ValueError("serialize is currently supported only for bool fields")
        return self


class SinkBlock(DslBaseModel):
    """
    Назначение:
        Корневая секция sink-модели.
    """

    fields: list[SinkFieldSpec] = Field(default_factory=list)
    system_fields: list[SinkFieldSpec] = Field(default_factory=list)
    allow_extra: bool = True

    @model_validator(mode="before")
    @classmethod
    def _reject_system_field_serialize_in_raw_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        for field in value.get("system_fields") or []:
            if isinstance(field, dict) and field.get("serialize") is not None:
                name = field.get("name") or "<unknown>"
                raise ValueError(
                    f"system field '{name}' must not declare serialize metadata"
                )
        return value

    @model_validator(mode="after")
    def _validate_system_fields(self) -> "SinkBlock":
        for field in self.system_fields:
            if field.serialize is not None:
                raise ValueError(
                    f"system field '{field.name}' must not declare serialize metadata"
                )
        return self


class SinkSpec(DslBaseModel):
    """
    Назначение:
        Декларативная sink-модель для датасета.
    """

    dataset: str
    sink: SinkBlock
