"""
Назначение:
    Pydantic-модели Dictionary DSL (registry/spec/manifest) для v1 runtime.

Граница ответственности:
    - Определяет декларативные контрактные схемы и валидирует инварианты границы данных.
    - НЕ читает файлы, НЕ выполняет lookup, НЕ импортирует infra/runtime backend.
    - Whitelist для `normalized_key.ops` живёт здесь как domain-правило (по ADR).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from connector.domain.dsl.specs._base import DslBaseModel, OperationCall


DICTIONARY_NORMALIZED_KEY_OPS_WHITELIST: frozenset[str] = frozenset(
    {
        "trim",
        "lower",
        "upper",
        "to_string",
        "regex_replace",
    }
)


def _require_non_blank(value: str, *, field_name: str) -> str:
    """Назначение:
        Отбраковать пустые/пробельные строковые поля DSL-моделей.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


class DictionaryRegistryItemSpec(DslBaseModel):
    """
    Назначение:
        Один элемент секции `dictionaries.items` в `datasets/registry.yml`.
    """

    spec: str
    enabled: bool = True

    @field_validator("spec", mode="after")
    @classmethod
    def _validate_spec_path(cls, value: str) -> str:
        return _require_non_blank(value, field_name="spec")


class DictionaryRegistrySpec(DslBaseModel):
    """
    Назначение:
        Реестр словарей (control plane) из секции `dictionaries`.

    Инварианты:
        - `version` фиксирован как `1`.
        - `items` может быть пустым (`items: {}` валиден).
    """

    version: Literal[1]
    manifest: str
    items: dict[str, DictionaryRegistryItemSpec] = Field(default_factory=dict)

    @field_validator("manifest", mode="after")
    @classmethod
    def _validate_manifest_path(cls, value: str) -> str:
        return _require_non_blank(value, field_name="manifest")

    @model_validator(mode="after")
    def _validate_items_keys(self) -> "DictionaryRegistrySpec":
        invalid_keys = [key for key in self.items if not isinstance(key, str) or not key.strip()]
        if invalid_keys:
            raise ValueError("dictionaries.items contains empty dictionary key")
        return self


class DictionarySourceCsvSpec(DslBaseModel):
    """
    Назначение:
        Параметры CSV-источника словаря v1.
    """

    delimiter: str = ","
    has_header: bool = True
    encoding: str = "utf-8"

    @field_validator("delimiter", "encoding", mode="after")
    @classmethod
    def _validate_non_blank(cls, value: str, info) -> str:
        return _require_non_blank(value, field_name=str(info.field_name))


class DictionarySourceSpec(DslBaseModel):
    """
    Назначение:
        Описание источника данных словаря.
    """

    format: Literal["csv"]
    location: str
    csv: DictionarySourceCsvSpec = Field(default_factory=DictionarySourceCsvSpec)

    @field_validator("location", mode="after")
    @classmethod
    def _validate_location(cls, value: str) -> str:
        return _require_non_blank(value, field_name="source.location")


class DictionaryNormalizedKeySpec(DslBaseModel):
    """
    Назначение:
        Декларативная цепочка нормализации lookup-ключа словаря.
    """

    ops: list[OperationCall] = Field(default_factory=list)

    @field_validator("ops", mode="after")
    @classmethod
    def _validate_ops_whitelist(cls, ops: list[OperationCall]) -> list[OperationCall]:
        invalid = {op.op for op in ops} - DICTIONARY_NORMALIZED_KEY_OPS_WHITELIST
        if invalid:
            raise ValueError(
                f"ops not allowed in normalized_key: {sorted(invalid)}. "
                f"Allowed: {sorted(DICTIONARY_NORMALIZED_KEY_OPS_WHITELIST)}"
            )
        return ops


class DictionarySchemaSpec(DslBaseModel):
    """
    Назначение:
        Lookup-схема словаря: key/value колонки и опциональная нормализация ключа.
    """

    key_column: str
    value_columns: list[str]
    normalized_key: DictionaryNormalizedKeySpec | None = None

    @model_validator(mode="after")
    def _validate_schema(self) -> "DictionarySchemaSpec":
        _require_non_blank(self.key_column, field_name="schema.key_column")
        if not self.value_columns:
            raise ValueError("schema.value_columns must not be empty")

        normalized_values: list[str] = []
        for idx, column in enumerate(self.value_columns):
            _require_non_blank(column, field_name=f"schema.value_columns[{idx}]")
            normalized_values.append(column)

        if self.key_column in normalized_values:
            raise ValueError("schema.key_column must not be present in schema.value_columns")
        return self


class DictionaryLookupSpec(DslBaseModel):
    """
    Назначение:
        Политика поведения lookup в runtime.
    """

    allow_duplicates: bool = False


class DictionarySpec(DslBaseModel):
    """
    Назначение:
        Каноническая Pydantic-модель одного словаря (файл `*.dictionary.yaml`).
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    dictionary: str
    source: DictionarySourceSpec
    data_schema: DictionarySchemaSpec = Field(alias="schema")
    lookup: DictionaryLookupSpec = Field(default_factory=DictionaryLookupSpec)

    @field_validator("dictionary", mode="after")
    @classmethod
    def _validate_dictionary_name(cls, value: str) -> str:
        return _require_non_blank(value, field_name="dictionary")


class DictionaryManifestItemSpec(DslBaseModel):
    """
    Назначение:
        Метаданные snapshot-файла словаря из manifest-файла, путь к которому
        объявлен в dictionary registry.
    """

    csv_path: str
    content_sha256: str
    schema_hash: str
    row_count: int = Field(ge=0)
    updated_at_utc: str
    owner: str

    @field_validator(
        "csv_path",
        "content_sha256",
        "schema_hash",
        "updated_at_utc",
        "owner",
        mode="after",
    )
    @classmethod
    def _validate_required_strings(cls, value: str, info) -> str:
        return _require_non_blank(value, field_name=str(info.field_name))


class DictionaryManifestSpec(DslBaseModel):
    """
    Назначение:
        Реестр fingerprint/version метаданных словарных CSV snapshot'ов.
    """

    version: Literal[1]
    items: dict[str, DictionaryManifestItemSpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_items_keys(self) -> "DictionaryManifestSpec":
        invalid_keys = [key for key in self.items if not isinstance(key, str) or not key.strip()]
        if invalid_keys:
            raise ValueError("dictionary manifest contains empty dictionary key")
        return self


__all__ = [
    "DICTIONARY_NORMALIZED_KEY_OPS_WHITELIST",
    "DictionaryLookupSpec",
    "DictionaryManifestItemSpec",
    "DictionaryManifestSpec",
    "DictionaryNormalizedKeySpec",
    "DictionaryRegistryItemSpec",
    "DictionaryRegistrySpec",
    "DictionarySchemaSpec",
    "DictionarySourceCsvSpec",
    "DictionarySourceSpec",
    "DictionarySpec",
]
