from __future__ import annotations

from connector.domain.dictionary_dsl.specs import DictionarySpec
from connector.infra.dictionaries.versioning import (
    build_content_sha256_bytes,
    build_dictionary_schema_hash,
    build_dictionary_version_id,
    build_dictionary_version_info,
)


def _spec() -> DictionarySpec:
    return DictionarySpec.model_validate(
        {
            "dictionary": "organizations",
            "source": {
                "format": "csv",
                "location": "dictionaries/organizations.csv",
            },
            "schema": {
                "key_column": "code",
                "value_columns": ["ouid", "name"],
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


def test_schema_hash_is_deterministic_for_same_spec() -> None:
    spec = _spec()

    assert build_dictionary_schema_hash(spec) == build_dictionary_schema_hash(spec)


def test_schema_hash_changes_when_lookup_semantics_change() -> None:
    spec_a = _spec()
    spec_b = DictionarySpec.model_validate(
        {
            **_spec().model_dump(),
            "lookup": {"allow_duplicates": True},
        }
    )

    assert build_dictionary_schema_hash(spec_a) != build_dictionary_schema_hash(spec_b)


def test_content_sha256_bytes_is_deterministic() -> None:
    payload = b"code,name\nORG,Org name\n"

    assert build_content_sha256_bytes(payload) == build_content_sha256_bytes(payload)


def test_version_id_uses_short_hash_prefixes() -> None:
    version_id = build_dictionary_version_id(
        "organizations",
        schema_hash="a" * 64,
        content_sha256="b" * 64,
    )

    assert version_id == "organizations:aaaaaaaaaaaa:bbbbbbbbbbbb"


def test_build_dictionary_version_info_sets_v1_defaults() -> None:
    info = build_dictionary_version_info(
        dict_name="organizations",
        schema_hash="a" * 64,
        content_sha256="b" * 64,
        row_count=3,
        loaded_at="2026-02-23T12:00:00Z",
    )

    assert info.dict_name == "organizations"
    assert info.row_count == 3
    assert info.fingerprint_kind == "content_sha256"
    assert info.source_format == "csv"
    assert info.loaded_at == "2026-02-23T12:00:00Z"

