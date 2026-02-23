"""
Назначение:
    CSV loader для Dictionary runtime v1 (`Polars + CSV`).

Граница ответственности:
    - Читает CSV snapshot-файлы, валидирует manifest fingerprints и загружает данные в backend.
    - Не реализует lookup/contains/canonicalize (это backend).
    - Не выполняет DI wiring и не принимает решения о составе runtime (это orchestration).
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import polars as pl

from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.loader._common import _repo_root
from connector.infra.dictionaries.backends.polars_backend import PolarsDictionaryBackend
from connector.infra.dictionaries.versioning import build_content_sha256_bytes


class CsvDictionaryLoader:
    """
    Назначение:
        Загрузчик CSV snapshot'ов словарей в `PolarsDictionaryBackend`.

    Контракт:
        - Работает только с уже скомпилированным runtime bundle внутри backend.
        - Валидирует `content_sha256` и row_count against manifest на этапе загрузки.
        - Ошибки IO/данных оборачивает в `DslLoadError`.
    """

    def __init__(self, *, datasets_root: str | Path | None = None) -> None:
        self._datasets_root = Path(datasets_root) if datasets_root is not None else _repo_root() / "datasets"

    def load_into(self, backend: PolarsDictionaryBackend) -> None:
        """
        Назначение:
            Прочитать все CSV snapshot'ы из runtime bundle и загрузить их в backend.

        Algorithm:
            1) Для каждого compiled dictionary читается raw bytes из `datasets_root/source.location`.
            2) Проверяется `content_sha256` (manifest -> факт).
            3) CSV декодируется с BOM-safe поведением и парсится в `polars.DataFrame`.
            4) Проверяется `row_count` against manifest.
            5) DataFrame передаётся в backend для schema/index/duplicate validation.
        """
        for dict_name, compiled in backend.bundle.specs.items():
            file_path = self._datasets_root / compiled.source_location
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

            backend.load_dictionary_frame(
                dict_name=dict_name,
                frame=frame,
                content_sha256=content_sha256,
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
        path: Path,
    ) -> pl.DataFrame:
        try:
            text = self._decode_text(raw_bytes, encoding=encoding)
            return pl.read_csv(
                StringIO(text),
                separator=delimiter,
                has_header=has_header,
            )
        except DslLoadError:
            raise
        except Exception as exc:
            raise DslLoadError(
                code="DICT_SOURCE_READ_FAILED",
                message=f"Failed to parse dictionary CSV for '{dict_name}': {exc}",
                details={"dict_name": dict_name, "path": str(path)},
            ) from exc

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


__all__ = ["CsvDictionaryLoader"]
