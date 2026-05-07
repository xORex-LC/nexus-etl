"""
Назначение:
    CSV loader для Dictionary runtime v1 (`Polars + CSV`).

Граница ответственности:
    - Читает CSV snapshot-файлы, валидирует manifest fingerprints и загружает данные в backend.
    - Не реализует lookup/contains/canonicalize (это backend).
    - Не выполняет DI wiring и не принимает решения о составе runtime (это orchestration).
"""

from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Callable

import polars as pl

from connector.common.runtime_paths import get_runtime_paths
from connector.domain.dsl.issues import DslLoadError
from connector.infra.dictionaries.backends.polars_backend import PolarsDictionaryBackend
from connector.infra.dictionaries.dsl_runtime import CompiledDictionarySpec
from connector.infra.dictionaries.versioning import DictionaryVersionInfo
from connector.infra.dictionaries.versioning import build_content_sha256_bytes


@dataclass(frozen=True)
class DictionaryCsvLoadEvent:
    """
    Назначение:
        Metadata о фактической загрузке одного dictionary CSV в backend.

    Граница:
        - Содержит observability/runtime metadata без plaintext lookup keys.
        - Может быть использован telemetry-слоем через callback.
    """

    dict_name: str
    path: str
    row_count: int
    content_sha256: str
    source_empty: bool
    version_info: DictionaryVersionInfo


DictionaryCsvLoadCallback = Callable[[DictionaryCsvLoadEvent], None]


class CsvDictionaryLoader:
    """
    Назначение:
        Загрузчик CSV snapshot'ов словарей в `PolarsDictionaryBackend`.

    Контракт:
        - Работает только с уже скомпилированным runtime bundle внутри backend.
        - Валидирует `content_sha256` и row_count against manifest на этапе загрузки.
        - Ошибки IO/данных оборачивает в `DslLoadError`.
    """

    def __init__(
        self,
        *,
        dictionary_data_root: str | Path | None = None,
        on_dictionary_loaded: DictionaryCsvLoadCallback | None = None,
    ) -> None:
        if dictionary_data_root is None:
            self._dictionary_data_root = get_runtime_paths().dictionary_data_root
        else:
            self._dictionary_data_root = Path(dictionary_data_root).expanduser().resolve()
        self._on_dictionary_loaded = on_dictionary_loaded

    def load_into(self, backend: PolarsDictionaryBackend) -> None:
        """
        Назначение:
            Прочитать все CSV snapshot'ы из runtime bundle и загрузить их в backend.

        Algorithm:
            1) Для каждого compiled dictionary читается raw bytes из
               `dictionary_data_root/source.location`.
            2) Проверяется `content_sha256` (manifest -> факт).
            3) CSV декодируется с BOM-safe поведением и парсится в `polars.DataFrame`.
            4) Проверяется `row_count` against manifest.
            5) DataFrame передаётся в backend для schema/index/duplicate validation.
        """
        for dict_name in backend.get_declared_dict_names():
            self.load_dictionary_into(backend, dict_name=dict_name)

    def load_dictionary_into(self, backend: PolarsDictionaryBackend, *, dict_name: str) -> None:
        """
        Назначение:
            Загрузить один словарь по имени в backend (используется eager и lazy режимами).

        Contract:
            - Повторная загрузка уже загруженного словаря не выполняется (startup-only policy).
            - Unknown dict_name трактуется как ошибка runtime wiring/call-site (`KeyError` от bundle.get()).
        """
        if backend.is_loaded(dict_name):
            return

        compiled = backend.bundle.get(dict_name)
        file_path = (self._dictionary_data_root / compiled.source_data_ref).resolve()
        raw_bytes = self._read_file_bytes_or_raise(file_path, dict_name=dict_name)

        content_sha256 = build_content_sha256_bytes(raw_bytes)
        if content_sha256 != compiled.manifest_item.content_sha256:
            raise DslLoadError(
                code="DICT_SOURCE_FINGERPRINT_MISMATCH",
                message=f"Dictionary content fingerprint mismatch for '{dict_name}'",
                details={
                    "dict_name": dict_name,
                    "path": str(file_path),
                    "expected_content_sha256": compiled.manifest_item.content_sha256,
                    "actual_content_sha256": content_sha256,
                },
            )

        frame = self._parse_csv_or_raise(
            raw_bytes=raw_bytes,
            dict_name=dict_name,
            delimiter=compiled.csv_delimiter,
            has_header=compiled.csv_has_header,
            encoding=compiled.csv_encoding,
            null_values=compiled.csv_null_values,
            path=file_path,
        )

        if frame.height != compiled.manifest_item.row_count:
            raise DslLoadError(
                code="DICT_SOURCE_FINGERPRINT_MISMATCH",
                message=f"Dictionary row_count mismatch for '{dict_name}'",
                details={
                    "dict_name": dict_name,
                    "path": str(file_path),
                    "expected_row_count": compiled.manifest_item.row_count,
                    "actual_row_count": frame.height,
                },
            )

        self._validate_frame_nullability_or_raise(
            compiled=compiled,
            frame=frame,
            path=file_path,
        )

        version_info = backend.load_dictionary_frame(
            dict_name=dict_name,
            frame=frame,
            content_sha256=content_sha256,
        )
        self._emit_load_event(
            dict_name=dict_name,
            path=file_path,
            row_count=frame.height,
            content_sha256=content_sha256,
            version_info=version_info,
        )

    def _read_file_bytes_or_raise(self, path: Path, *, dict_name: str) -> bytes:
        try:
            return path.read_bytes()
        except Exception as exc:
            raise DslLoadError(
                code="DICT_SOURCE_READ_FAILED",
                message=f"Failed to read dictionary CSV for '{dict_name}': {exc}",
                details={"dict_name": dict_name, "path": str(path)},
            ) from exc

    def _parse_csv_or_raise(
        self,
        *,
        raw_bytes: bytes,
        dict_name: str,
        delimiter: str,
        has_header: bool,
        encoding: str,
        null_values: tuple[str, ...],
        path: Path,
    ) -> pl.DataFrame:
        try:
            text = self._decode_text(raw_bytes, encoding=encoding)
            return pl.read_csv(
                StringIO(text),
                separator=delimiter,
                has_header=has_header,
                null_values=list(null_values),
            )
        except DslLoadError:
            raise
        except Exception as exc:
            raise DslLoadError(
                code="DICT_SOURCE_READ_FAILED",
                message=f"Failed to parse dictionary CSV for '{dict_name}': {exc}",
                details={"dict_name": dict_name, "path": str(path)},
            ) from exc

    def _validate_frame_nullability_or_raise(
        self,
        *,
        compiled: CompiledDictionarySpec,
        frame: pl.DataFrame,
        path: Path,
    ) -> None:
        """
        Назначение:
            Проверить nullable-контракт dictionary schema после CSV parsing.

        Граница:
            - Работает уже с parsed `DataFrame`, где null-маркеры преобразованы в `None`.
            - Не строит backend index и не валидирует lookup semantics.
        """
        if compiled.key_column in frame.columns:
            key_nulls = int(frame.select(pl.col(compiled.key_column).is_null().sum()).item())
        else:
            key_nulls = 0
        if key_nulls > 0:
            raise DslLoadError(
                code="DICT_SOURCE_NULLABILITY_INVALID",
                message=f"Dictionary key column contains nulls for '{compiled.dict_name}'",
                details={
                    "dict_name": compiled.dict_name,
                    "path": str(path),
                    "column": compiled.key_column,
                    "null_count": key_nulls,
                    "column_role": "key",
                },
            )

        non_nullable_value_columns = [
            column
            for column in compiled.value_columns
            if column not in compiled.nullable_value_columns
        ]
        for column in non_nullable_value_columns:
            if column not in frame.columns:
                continue
            null_count = int(frame.select(pl.col(column).is_null().sum()).item())
            if null_count <= 0:
                continue
            raise DslLoadError(
                code="DICT_SOURCE_NULLABILITY_INVALID",
                message=(
                    f"Dictionary non-nullable value column contains nulls "
                    f"for '{compiled.dict_name}'"
                ),
                details={
                    "dict_name": compiled.dict_name,
                    "path": str(path),
                    "column": column,
                    "null_count": null_count,
                    "column_role": "value",
                },
            )

    def _emit_load_event(
        self,
        *,
        dict_name: str,
        path: Path,
        row_count: int,
        content_sha256: str,
        version_info: DictionaryVersionInfo,
    ) -> None:
        callback = self._on_dictionary_loaded
        if callback is None:
            return
        callback(
            DictionaryCsvLoadEvent(
                dict_name=dict_name,
                path=str(path),
                row_count=row_count,
                content_sha256=content_sha256,
                source_empty=(row_count == 0),
                version_info=version_info,
            )
        )

    @staticmethod
    def _decode_text(raw_bytes: bytes, *, encoding: str) -> str:
        """
        Назначение:
            Декодировать CSV bytes в text с BOM-safe поведением для UTF-8.
        """
        normalized = encoding.strip().lower().replace("_", "-")
        if normalized in {"utf-8", "utf8"}:
            return raw_bytes.decode("utf-8-sig")
        return raw_bytes.decode(encoding)


__all__ = ["CsvDictionaryLoader", "DictionaryCsvLoadEvent"]
