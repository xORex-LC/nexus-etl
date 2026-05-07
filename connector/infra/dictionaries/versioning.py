"""
Назначение:
    Versioning/fingerprint utilities для Dictionary runtime v1.

Граница ответственности:
    - Вычисляет детерминированные hash/id для dictionary spec и CSV snapshot content.
    - Не читает/валидирует DSL registry (это domain loader) и не выполняет lookup.
    - Не зависит от DI/delivery и не знает о pipeline stages.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from connector.domain.dictionary_dsl.specs import DictionarySpec


def _canonical_json(value: Any) -> str:
    """
    Назначение:
        Канонически сериализовать структуру в JSON для стабильного хэширования.
    """
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalized_key_ops_payload(spec: DictionarySpec) -> list[dict[str, Any]]:
    ops_spec = spec.data_schema.normalized_key
    if ops_spec is None:
        return []
    return [{"op": op.op, "args": dict(op.args)} for op in ops_spec.ops]


def build_dictionary_schema_hash(spec: DictionarySpec) -> str:
    """
    Назначение:
        Вычислить `schema_hash` словаря по ADR v1 (subset contract).

    Contract:
        В hash входят только поля, влияющие на lookup semantics и storage contract.
    """
    schema_subset = {
        "dictionary": spec.dictionary,
        "source": {
            "format": spec.source.format,
            "csv": {
                "null_values": list(spec.source.csv.null_values),
            },
        },
        "schema": {
            "key_column": {
                "name": spec.data_schema.key_column.name,
            },
            "value_columns": [
                {
                    "name": column.name,
                    "nullable": column.nullable,
                }
                for column in spec.data_schema.value_columns
            ],
            "normalized_key": {
                "ops": _normalized_key_ops_payload(spec),
            },
        },
        "lookup": {
            "allow_duplicates": spec.lookup.allow_duplicates,
        },
    }
    payload = _canonical_json(schema_subset).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_content_sha256_bytes(payload: bytes) -> str:
    """
    Назначение:
        Вычислить SHA-256 для сырого содержимого CSV snapshot.
    """
    return hashlib.sha256(payload).hexdigest()


def build_content_sha256_for_file(path: str | Path) -> str:
    """
    Назначение:
        Вычислить `content_sha256` для файла (без декодирования/нормализации).
    """
    path_obj = Path(path)
    data = path_obj.read_bytes()
    return build_content_sha256_bytes(data)


def build_dictionary_version_id(
    dict_name: str,
    *,
    schema_hash: str,
    content_sha256: str,
) -> str:
    """
    Назначение:
        Сформировать компактный `version_id` словаря по ADR v1.
    """
    return f"{dict_name}:{schema_hash[:12]}:{content_sha256[:12]}"


def _utc_now_iso() -> str:
    dt = datetime.now(timezone.utc).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DictionaryVersionInfo:
    """
    Назначение:
        Единый version contract словаря (v1/v2 forward-compatible shape).
    """

    dict_name: str
    version_id: str
    schema_hash: str
    row_count: int
    source_format: str
    loaded_at: str
    fingerprint_kind: str


def build_dictionary_version_info(
    *,
    dict_name: str,
    schema_hash: str,
    content_sha256: str,
    row_count: int,
    source_format: str = "csv",
    loaded_at: str | None = None,
) -> DictionaryVersionInfo:
    """
    Назначение:
        Построить `DictionaryVersionInfo` для загруженного словаря v1.
    """
    return DictionaryVersionInfo(
        dict_name=dict_name,
        version_id=build_dictionary_version_id(
            dict_name,
            schema_hash=schema_hash,
            content_sha256=content_sha256,
        ),
        schema_hash=schema_hash,
        row_count=row_count,
        source_format=source_format,
        loaded_at=loaded_at or _utc_now_iso(),
        fingerprint_kind="content_sha256",
    )


__all__ = [
    "DictionaryVersionInfo",
    "build_content_sha256_bytes",
    "build_content_sha256_for_file",
    "build_dictionary_schema_hash",
    "build_dictionary_version_id",
    "build_dictionary_version_info",
]
