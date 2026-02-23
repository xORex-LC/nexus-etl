from __future__ import annotations

from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

from connector.domain.dictionary_dsl.specs import DictionaryManifestSpec, DictionarySpec
from connector.domain.dsl.issues import DslLoadError
from connector.infra.dictionaries.backends.polars_backend import PolarsDictionaryBackend
from connector.infra.dictionaries.dsl_runtime import build_dictionary_dsl_runtime
from connector.infra.dictionaries.loader_csv import CsvDictionaryLoader
from connector.infra.dictionaries.versioning import (
    build_content_sha256_bytes,
    build_dictionary_schema_hash,
)


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _spec(*, encoding: str = "utf-8") -> DictionarySpec:
    return DictionarySpec.model_validate(
        {
            "dictionary": "organizations",
            "source": {
                "format": "csv",
                "location": "dictionaries/organizations.csv",
                "csv": {"delimiter": ",", "has_header": True, "encoding": encoding},
            },
            "schema": {
                "key_column": "code",
                "value_columns": ["name", "ouid"],
                "normalized_key": {"ops": [{"op": "trim"}, {"op": "lower"}]},
            },
            "lookup": {"allow_duplicates": False},
        }
    )


def _backend_for(
    *,
    spec: DictionarySpec,
    content_sha256: str,
    row_count: int,
) -> PolarsDictionaryBackend:
    manifest = DictionaryManifestSpec.model_validate(
        {
            "version": 1,
            "items": {
                "organizations": {
                    "csv_path": spec.source.location,
                    "content_sha256": content_sha256,
                    "schema_hash": build_dictionary_schema_hash(spec),
                    "row_count": row_count,
                    "updated_at_utc": "2026-02-23T12:00:00Z",
                    "owner": "dataset-employees",
                }
            },
        }
    )
    bundle = build_dictionary_dsl_runtime(specs={"organizations": spec}, manifest_spec=manifest)
    return PolarsDictionaryBackend(bundle=bundle)


def test_csv_loader_supports_utf8_bom_and_loads_into_backend(tmp_path: Path) -> None:
    spec = _spec(encoding="utf-8")
    raw = ("\ufeffcode,name,ouid\n ORG-1 ,Org One,100\n").encode("utf-8")
    _write_bytes(tmp_path / "datasets" / "dictionaries" / "organizations.csv", raw)

    backend = _backend_for(
        spec=spec,
        content_sha256=build_content_sha256_bytes(raw),
        row_count=1,
    )
    loader = CsvDictionaryLoader(datasets_root=tmp_path / "datasets")

    loader.load_into(backend)

    assert backend.lookup("organizations", "org-1", fields=("name",)) == [{"name": "Org One"}]


def test_csv_loader_raises_on_content_hash_mismatch(tmp_path: Path) -> None:
    spec = _spec()
    raw = b"code,name,ouid\nORG-1,Org One,100\n"
    _write_bytes(tmp_path / "datasets" / "dictionaries" / "organizations.csv", raw)

    backend = _backend_for(spec=spec, content_sha256="f" * 64, row_count=1)
    loader = CsvDictionaryLoader(datasets_root=tmp_path / "datasets")

    with pytest.raises(DslLoadError) as exc_info:
        loader.load_into(backend)

    assert exc_info.value.code == "DICT_SOURCE_FINGERPRINT_MISMATCH"


def test_csv_loader_raises_on_row_count_mismatch(tmp_path: Path) -> None:
    spec = _spec()
    raw = b"code,name,ouid\nORG-1,Org One,100\n"
    _write_bytes(tmp_path / "datasets" / "dictionaries" / "organizations.csv", raw)

    backend = _backend_for(
        spec=spec,
        content_sha256=build_content_sha256_bytes(raw),
        row_count=2,
    )
    loader = CsvDictionaryLoader(datasets_root=tmp_path / "datasets")

    with pytest.raises(DslLoadError) as exc_info:
        loader.load_into(backend)

    assert exc_info.value.code == "DICT_SOURCE_FINGERPRINT_MISMATCH"


def test_csv_loader_raises_on_missing_file(tmp_path: Path) -> None:
    spec = _spec()
    backend = _backend_for(spec=spec, content_sha256="a" * 64, row_count=1)
    loader = CsvDictionaryLoader(datasets_root=tmp_path / "datasets")

    with pytest.raises(DslLoadError) as exc_info:
        loader.load_into(backend)

    assert exc_info.value.code == "DICT_SOURCE_READ_FAILED"


def test_csv_loader_reports_schema_error_from_backend(tmp_path: Path) -> None:
    spec = _spec()
    raw = b"code,name\nORG-1,Org One\n"
    _write_bytes(tmp_path / "datasets" / "dictionaries" / "organizations.csv", raw)

    backend = _backend_for(
        spec=spec,
        content_sha256=build_content_sha256_bytes(raw),
        row_count=1,
    )
    loader = CsvDictionaryLoader(datasets_root=tmp_path / "datasets")

    with pytest.raises(DslLoadError) as exc_info:
        loader.load_into(backend)

    assert exc_info.value.code == "DICT_SCHEMA_INVALID"


def test_csv_loader_emits_source_empty_load_event_for_empty_csv(tmp_path: Path) -> None:
    spec = _spec()
    raw = b"code,name,ouid\n"
    _write_bytes(tmp_path / "datasets" / "dictionaries" / "organizations.csv", raw)

    backend = _backend_for(
        spec=spec,
        content_sha256=build_content_sha256_bytes(raw),
        row_count=0,
    )
    events = []
    loader = CsvDictionaryLoader(
        datasets_root=tmp_path / "datasets",
        on_dictionary_loaded=events.append,
    )

    loader.load_dictionary_into(backend, dict_name="organizations")

    assert backend.lookup("organizations", "ORG-1") == []
    assert len(events) == 1
    event = events[0]
    assert event.dict_name == "organizations"
    assert event.row_count == 0
    assert event.source_empty is True
    assert event.version_info.row_count == 0
