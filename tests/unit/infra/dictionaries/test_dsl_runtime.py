from __future__ import annotations

import pytest

from connector.domain.dictionary_dsl.specs import (
    DictionaryManifestSpec,
    DictionarySpec,
)
from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.registry import OperationRegistry
from connector.infra.dictionaries.dsl_runtime import build_dictionary_dsl_runtime
from connector.infra.dictionaries.versioning import build_dictionary_schema_hash


def _dictionary_spec() -> DictionarySpec:
    return DictionarySpec.model_validate(
        {
            "dictionary": "organizations",
            "source": {
                "format": "csv",
                "location": "dictionaries/organizations.csv",
                "csv": {
                    "delimiter": ",",
                    "has_header": True,
                    "encoding": "utf-8",
                    "null_values": ["NULL"],
                },
            },
            "schema": {
                "key_column": {"name": "code"},
                "value_columns": [
                    {"name": "name", "nullable": False},
                    {"name": "ouid", "nullable": False},
                ],
                "normalized_key": {
                    "ops": [
                        {"op": "trim"},
                        {"op": "lower"},
                    ]
                },
            },
            "lookup": {"allow_duplicates": False},
        }
    )


def _manifest_for(spec: DictionarySpec, *, schema_hash: str | None = None, csv_path: str | None = None) -> DictionaryManifestSpec:
    return DictionaryManifestSpec.model_validate(
        {
            "version": 1,
            "items": {
                spec.dictionary: {
                    "csv_path": csv_path or spec.source.location,
                    "content_sha256": "0" * 64,
                    "schema_hash": schema_hash or build_dictionary_schema_hash(spec),
                    "row_count": 1,
                    "updated_at_utc": "2026-02-23T12:00:00Z",
                    "owner": "dataset-employees",
                }
            },
        }
    )


def test_build_dictionary_dsl_runtime_compiles_normalized_key_ops() -> None:
    spec = _dictionary_spec()
    bundle = build_dictionary_dsl_runtime(
        specs={"organizations": spec},
        manifest_spec=_manifest_for(spec),
    )

    compiled = bundle.specs["organizations"]
    assert compiled.schema_hash == build_dictionary_schema_hash(spec)
    assert [op.name for op in compiled.normalized_key_ops] == ["trim", "lower"]
    assert compiled.normalize_key(" ORG-1 ") == "org-1"
    assert compiled.key_column == "code"
    assert compiled.value_columns == ("name", "ouid")
    assert compiled.csv_null_values == ("NULL",)


def test_build_dictionary_dsl_runtime_raises_on_manifest_missing_entry() -> None:
    spec = _dictionary_spec()
    manifest = DictionaryManifestSpec.model_validate({"version": 1, "items": {}})

    with pytest.raises(DslLoadError) as exc_info:
        build_dictionary_dsl_runtime(specs={"organizations": spec}, manifest_spec=manifest)

    assert exc_info.value.code == "DICT_SOURCE_MANIFEST_INVALID"


def test_build_dictionary_dsl_runtime_raises_on_manifest_csv_path_mismatch() -> None:
    spec = _dictionary_spec()
    manifest = _manifest_for(spec, csv_path="dictionaries/other.csv")

    with pytest.raises(DslLoadError) as exc_info:
        build_dictionary_dsl_runtime(specs={"organizations": spec}, manifest_spec=manifest)

    assert exc_info.value.code == "DICT_SOURCE_MANIFEST_INVALID"


def test_build_dictionary_dsl_runtime_raises_on_schema_hash_mismatch() -> None:
    spec = _dictionary_spec()
    manifest = _manifest_for(spec, schema_hash="f" * 64)

    with pytest.raises(DslLoadError) as exc_info:
        build_dictionary_dsl_runtime(specs={"organizations": spec}, manifest_spec=manifest)

    assert exc_info.value.code == "DICT_SOURCE_FINGERPRINT_MISMATCH"


def test_build_dictionary_dsl_runtime_raises_on_unresolved_op_in_registry() -> None:
    spec = _dictionary_spec()
    manifest = _manifest_for(spec)

    with pytest.raises(DslLoadError) as exc_info:
        build_dictionary_dsl_runtime(
            specs={"organizations": spec},
            manifest_spec=manifest,
            operation_registry=OperationRegistry(),
        )

    assert exc_info.value.code == "DICT_DSL_SPEC_INVALID"
