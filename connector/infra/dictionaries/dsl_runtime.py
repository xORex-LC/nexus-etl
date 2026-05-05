"""
Назначение:
    Компиляция Dictionary DSL в runtime bundle (без IO).

Граница ответственности:
    - Принимает уже валидированные `DictionarySpec` и `DictionaryManifestSpec`.
    - Резолвит `normalized_key.ops` через `OperationRegistry` в callable chain.
    - Не читает CSV, не выполняет lookup, не выбирает runtime lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from connector.domain.dictionary_dsl.specs import (
    DictionaryManifestItemSpec,
    DictionaryManifestSpec,
    DictionarySpec,
)
from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.registry import OperationRegistry, register_core_ops
from connector.infra.dictionaries.versioning import build_dictionary_schema_hash


NormalizerFunc = Callable[[Any], Any]


@dataclass(frozen=True)
class CompiledDictionaryOperation:
    """
    Назначение:
        Скомпилированная операция нормализации ключа словаря.
    """

    name: str
    func: Callable[..., Any]
    args: dict[str, Any]

    def apply(self, value: Any) -> Any:
        """
        Назначение:
            Применить одну DSL-операцию к значению ключа.
        """
        return self.func(value, **self.args)


@dataclass(frozen=True)
class CompiledDictionarySpec:
    """
    Назначение:
        Скомпилированное runtime-описание одного словаря (без загруженных данных).

    Граница:
        - Содержит DSL spec, manifest metadata и compiled normalization chain.
        - Не содержит IO objects, DataFrame и runtime counters.
    """

    dict_name: str
    spec: DictionarySpec
    manifest_item: DictionaryManifestItemSpec
    schema_hash: str
    normalized_key_ops: tuple[CompiledDictionaryOperation, ...]

    @property
    def key_column(self) -> str:
        return self.spec.data_schema.key_column.name

    @property
    def value_columns(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.spec.data_schema.value_columns)

    @property
    def nullable_value_columns(self) -> frozenset[str]:
        return frozenset(
            column.name
            for column in self.spec.data_schema.value_columns
            if column.nullable
        )

    @property
    def allowed_columns(self) -> tuple[str, ...]:
        return (self.key_column, *self.value_columns)

    @property
    def allow_duplicates(self) -> bool:
        return self.spec.lookup.allow_duplicates

    @property
    def source_location(self) -> str:
        return self.spec.source.location

    @property
    def csv_delimiter(self) -> str:
        return self.spec.source.csv.delimiter

    @property
    def csv_has_header(self) -> bool:
        return self.spec.source.csv.has_header

    @property
    def csv_encoding(self) -> str:
        return self.spec.source.csv.encoding

    @property
    def csv_null_values(self) -> tuple[str, ...]:
        return tuple(self.spec.source.csv.null_values)

    def normalize_key(self, value: Any) -> Any:
        """
        Назначение:
            Применить compiled chain `normalized_key.ops` к значению ключа.

        Contract:
            - При отсутствии ops возвращает значение как есть.
            - Исключения операций не подавляются (fail-fast runtime semantics).
        """
        current = value
        for op in self.normalized_key_ops:
            current = op.apply(current)
        return current


@dataclass(frozen=True)
class DictionaryDslRuntimeBundle:
    """
    Назначение:
        Полный runtime bundle dictionary DSL (specs + manifest + compiled metadata).
    """

    specs: dict[str, CompiledDictionarySpec]
    manifest_spec: DictionaryManifestSpec

    def get(self, dict_name: str) -> CompiledDictionarySpec:
        spec = self.specs.get(dict_name)
        if spec is None:
            raise KeyError(dict_name)
        return spec


def build_dictionary_dsl_runtime(
    *,
    specs: dict[str, DictionarySpec],
    manifest_spec: DictionaryManifestSpec,
    operation_registry: OperationRegistry | None = None,
) -> DictionaryDslRuntimeBundle:
    """
    Назначение:
        Скомпилировать dictionary DSL specs + manifest в runtime bundle (без IO).

    Contract:
        - Каждый словарь должен иметь entry в manifest.
        - `manifest.csv_path` должен совпадать с `spec.source.location`.
        - `manifest.schema_hash` должен совпадать с вычисленным `schema_hash`.
    """
    registry = operation_registry or register_core_ops(OperationRegistry())
    compiled_specs: dict[str, CompiledDictionarySpec] = {}

    for dict_name, spec in specs.items():
        manifest_item = manifest_spec.items.get(dict_name)
        if manifest_item is None:
            raise DslLoadError(
                code="DICT_SOURCE_MANIFEST_INVALID",
                message=f"Dictionary manifest entry is missing for '{dict_name}'",
                details={"dict_name": dict_name},
            )

        if _normalize_rel_path(manifest_item.csv_path) != _normalize_rel_path(spec.source.location):
            raise DslLoadError(
                code="DICT_SOURCE_MANIFEST_INVALID",
                message=(
                    f"Dictionary manifest csv_path mismatch for '{dict_name}': "
                    f"manifest '{manifest_item.csv_path}' != spec.source.location '{spec.source.location}'"
                ),
                details={
                    "dict_name": dict_name,
                    "manifest_csv_path": manifest_item.csv_path,
                    "source_location": spec.source.location,
                },
            )

        schema_hash = build_dictionary_schema_hash(spec)
        if manifest_item.schema_hash != schema_hash:
            raise DslLoadError(
                code="DICT_SOURCE_FINGERPRINT_MISMATCH",
                message=f"Dictionary schema hash mismatch for '{dict_name}'",
                details={
                    "dict_name": dict_name,
                    "expected_schema_hash": schema_hash,
                    "manifest_schema_hash": manifest_item.schema_hash,
                },
            )

        compiled_ops = _compile_normalized_key_ops(dict_name=dict_name, spec=spec, registry=registry)
        compiled_specs[dict_name] = CompiledDictionarySpec(
            dict_name=dict_name,
            spec=spec,
            manifest_item=manifest_item,
            schema_hash=schema_hash,
            normalized_key_ops=compiled_ops,
        )

    return DictionaryDslRuntimeBundle(
        specs=compiled_specs,
        manifest_spec=manifest_spec,
    )


def _compile_normalized_key_ops(
    *,
    dict_name: str,
    spec: DictionarySpec,
    registry: OperationRegistry,
) -> tuple[CompiledDictionaryOperation, ...]:
    """
    Назначение:
        Скомпилировать декларативный список `normalized_key.ops` в callable chain.
    """
    normalized_key_spec = spec.data_schema.normalized_key
    if normalized_key_spec is None or not normalized_key_spec.ops:
        return ()

    compiled: list[CompiledDictionaryOperation] = []
    for op_call in normalized_key_spec.ops:
        op = registry.get(op_call.op)
        if op is None:
            raise DslLoadError(
                code="DICT_DSL_SPEC_INVALID",
                message=f"Unknown normalized_key op '{op_call.op}' for dictionary '{dict_name}'",
                details={"dict_name": dict_name, "op": op_call.op},
            )
        compiled.append(
            CompiledDictionaryOperation(
                name=op.name,
                func=op.func,
                args=dict(op_call.args),
            )
        )
    return tuple(compiled)


def _normalize_rel_path(value: str) -> str:
    """
    Назначение:
        Нормализовать относительный путь для сравнения manifest/spec.
    """
    return Path(value).as_posix().lstrip("./")


__all__ = [
    "CompiledDictionaryOperation",
    "CompiledDictionarySpec",
    "DictionaryDslRuntimeBundle",
    "NormalizerFunc",
    "build_dictionary_dsl_runtime",
]
