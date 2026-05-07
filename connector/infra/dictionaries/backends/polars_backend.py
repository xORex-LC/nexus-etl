"""
Назначение:
    In-memory backend словарей на базе `polars` для Dictionary runtime v1.

Граница ответственности:
    - Хранит загруженные DataFrame и выполняет lookup/contains/canonicalize.
    - Строит in-memory индекс по (возможно нормализованному) ключу.
    - Не читает CSV и не валидирует manifest/fingerprint (это `loader_csv.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import polars as pl

from connector.domain.dsl.issues import DslLoadError
from connector.infra.dictionaries.dsl_runtime import CompiledDictionarySpec, DictionaryDslRuntimeBundle
from connector.infra.dictionaries.versioning import (
    DictionaryVersionInfo,
    build_dictionary_version_info,
)


@dataclass(frozen=True)
class _LoadedDictionaryData:
    """
    Назначение:
        Runtime-состояние одного загруженного словаря (данные + индекс + version info).
    """

    compiled: CompiledDictionarySpec
    frame: pl.DataFrame
    rows: tuple[dict[str, Any], ...]
    key_index: dict[str, tuple[int, ...]]
    version_info: DictionaryVersionInfo


class PolarsDictionaryBackend:
    """
    Назначение:
        In-memory lookup backend словарей поверх `polars.DataFrame`.

    Контракт:
        - Требует `DictionaryDslRuntimeBundle` (скомпилированный DSL без IO).
        - Данные загружаются отдельно через `CsvDictionaryLoader.load_into(self)`.
        - Поддерживает lazy first-load через callback, если настроен orchestration-слоем.
        - Unknown dict в non-empty runtime -> `KeyError`.
        - Empty runtime (`items:{}`) трактуется как miss (lookup=[] / contains=False).
    """

    def __init__(
        self,
        *,
        bundle: DictionaryDslRuntimeBundle,
        lazy_loader: Callable[[str], None] | None = None,
    ) -> None:
        self.bundle = bundle
        self._lazy_loader = lazy_loader
        self._loaded: dict[str, _LoadedDictionaryData] = {}
        self._loading_in_progress: set[str] = set()

    def load_dictionary_frame(
        self,
        *,
        dict_name: str,
        frame: pl.DataFrame,
        content_sha256: str,
    ) -> DictionaryVersionInfo:
        """
        Назначение:
            Загрузить/заменить данные словаря из готового `polars.DataFrame`.

        Contract:
            - Проверяет наличие обязательных колонок и duplicate policy.
            - Строит key-index по нормализованному ключу.
            - Пустой DataFrame с корректными колонками допустим.
        """
        compiled = self.bundle.get(dict_name)
        self._validate_columns(compiled=compiled, frame=frame)

        rows = tuple(frame.iter_rows(named=True))
        key_index = self._build_key_index(compiled=compiled, rows=rows)

        if not compiled.allow_duplicates:
            duplicates = [key for key, indexes in key_index.items() if len(indexes) > 1]
            if duplicates:
                raise DslLoadError(
                    code="DICT_SCHEMA_INVALID",
                    message=(
                        f"Duplicate dictionary keys are not allowed for '{dict_name}' "
                        f"(allow_duplicates=false)"
                    ),
                    details={
                        "dict_name": dict_name,
                        "duplicates_count": len(duplicates),
                        "sample_duplicate_keys": duplicates[:5],
                    },
                )

        version_info = build_dictionary_version_info(
            dict_name=dict_name,
            schema_hash=compiled.schema_hash,
            content_sha256=content_sha256,
            row_count=frame.height,
            source_format=compiled.spec.source.format,
        )

        self._loaded[dict_name] = _LoadedDictionaryData(
            compiled=compiled,
            frame=frame,
            rows=rows,
            key_index=key_index,
            version_info=version_info,
        )
        return version_info

    def set_lazy_loader(self, lazy_loader: Callable[[str], None] | None) -> None:
        """
        Назначение:
            Настроить lazy loader callback (per-dictionary first access load).

        Граница:
            - Callback поставляется orchestration/DI слоем.
            - Backend не знает о CSV loader/DI напрямую.
        """
        self._lazy_loader = lazy_loader

    def lookup(
        self,
        dict_name: str,
        key: str,
        *,
        at: Any | None = None,
        fields: tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Назначение:
            Найти записи словаря по ключу с projection/limit.
        """
        _ = at
        if self.is_empty_runtime():
            return []
        loaded = self._require_loaded(dict_name)
        projection = self._resolve_projection(loaded.compiled, fields)
        indexes = self._lookup_indexes(loaded, key)
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be > 0")
            indexes = indexes[:limit]
        return [self._project_row(loaded.rows[idx], projection) for idx in indexes]

    def contains(
        self,
        dict_name: str,
        value: str,
        *,
        at: Any | None = None,
    ) -> bool:
        """
        Назначение:
            Быстрый membership-check по словарю (через in-memory key index).
        """
        _ = at
        if self.is_empty_runtime():
            return False
        loaded = self._require_loaded(dict_name)
        normalized = self._normalize_lookup_key(loaded.compiled, value)
        return self._index_key(normalized) in loaded.key_index

    def canonicalize(
        self,
        dict_name: str,
        value: str,
        *,
        at: Any | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Назначение:
            Канонизация через тот же lookup pipeline (симметрия с `lookup`).
        """
        return self.lookup(dict_name, value, at=at, fields=None, limit=limit)

    def get_version_info(self, dict_name: str) -> DictionaryVersionInfo:
        """Назначение:
        Получить version info для уже загруженного словаря.
        """
        return self._require_loaded(dict_name).version_info

    def get_loaded_dict_names(self) -> tuple[str, ...]:
        """Назначение:
        Вернуть имена словарей, загруженных в backend.
        """
        return tuple(sorted(self._loaded.keys()))

    def get_declared_dict_names(self) -> tuple[str, ...]:
        """Назначение:
        Вернуть имена словарей, объявленных в runtime bundle (loaded + unloaded).
        """
        return tuple(sorted(self.bundle.specs.keys()))

    def has_declared_dictionary(self, dict_name: str) -> bool:
        """Назначение:
        Проверить, объявлен ли словарь в runtime bundle.
        """
        return dict_name in self.bundle.specs

    def is_loaded(self, dict_name: str) -> bool:
        """Назначение:
        Проверить, загружен ли словарь в runtime data store.
        """
        return dict_name in self._loaded

    def is_empty_runtime(self) -> bool:
        """Назначение:
        Пустой runtime (`items:{}` / all disabled) — без объявленных словарей.
        """
        return not self.bundle.specs

    def _require_loaded(self, dict_name: str) -> _LoadedDictionaryData:
        loaded = self._loaded.get(dict_name)
        if loaded is None and dict_name in self.bundle.specs:
            self._load_dictionary_lazy_if_needed(dict_name)
            loaded = self._loaded.get(dict_name)
        if loaded is None:
            raise KeyError(dict_name)
        return loaded

    def _load_dictionary_lazy_if_needed(self, dict_name: str) -> None:
        """
        Назначение:
            Подгрузить один словарь по первому обращению в lazy режиме.

        Contract:
            - Если lazy loader не задан, метод no-op.
            - Повторная загрузка не выполняется.
            - Ошибки callback не подавляются (fail-fast).
        """
        if dict_name in self._loaded:
            return
        if self._lazy_loader is None:
            return
        if dict_name in self._loading_in_progress:
            raise RuntimeError(f"Recursive lazy dictionary load detected for '{dict_name}'")

        self._loading_in_progress.add(dict_name)
        try:
            self._lazy_loader(dict_name)
        finally:
            self._loading_in_progress.discard(dict_name)

    def _validate_columns(self, *, compiled: CompiledDictionarySpec, frame: pl.DataFrame) -> None:
        required_columns = set(compiled.allowed_columns)
        actual_columns = set(frame.columns)
        missing = sorted(required_columns - actual_columns)
        if missing:
            raise DslLoadError(
                code="DICT_SCHEMA_INVALID",
                message=f"Dictionary CSV is missing required columns for '{compiled.dict_name}'",
                details={
                    "dict_name": compiled.dict_name,
                    "missing_columns": missing,
                    "actual_columns": sorted(actual_columns),
                },
            )

    def _build_key_index(
        self,
        *,
        compiled: CompiledDictionarySpec,
        rows: tuple[dict[str, Any], ...],
    ) -> dict[str, tuple[int, ...]]:
        """
        Назначение:
            Построить key-index по нормализованному lookup-ключу.
        """
        buckets: dict[str, list[int]] = {}
        for idx, row in enumerate(rows):
            raw_key = row.get(compiled.key_column)
            normalized = self._normalize_lookup_key(compiled, raw_key)
            key = self._index_key(normalized)
            buckets.setdefault(key, []).append(idx)
        return {key: tuple(indexes) for key, indexes in buckets.items()}

    def _lookup_indexes(self, loaded: _LoadedDictionaryData, key: Any) -> tuple[int, ...]:
        normalized = self._normalize_lookup_key(loaded.compiled, key)
        return loaded.key_index.get(self._index_key(normalized), ())

    def _normalize_lookup_key(self, compiled: CompiledDictionarySpec, value: Any) -> Any:
        return compiled.normalize_key(value)

    def _index_key(self, value: Any) -> str:
        """
        Назначение:
            Нормализовать ключ словаря к hashable/string форме для index dict.
        """
        if value is None:
            return "__none__"
        return f"v:{value}"

    def _resolve_projection(
        self,
        compiled: CompiledDictionarySpec,
        fields: tuple[str, ...] | None,
    ) -> tuple[str, ...]:
        if fields is None:
            return compiled.allowed_columns

        allowed = set(compiled.allowed_columns)
        invalid = [field for field in fields if field not in allowed]
        if invalid:
            raise DslLoadError(
                code="DICT_SCHEMA_INVALID",
                message=f"Unknown projection fields for dictionary '{compiled.dict_name}'",
                details={
                    "dict_name": compiled.dict_name,
                    "invalid_fields": invalid,
                    "allowed_fields": sorted(allowed),
                },
            )
        return tuple(fields)

    @staticmethod
    def _project_row(row: dict[str, Any], projection: tuple[str, ...]) -> dict[str, Any]:
        return {field: row.get(field) for field in projection}


__all__ = ["PolarsDictionaryBackend"]
