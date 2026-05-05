from __future__ import annotations

import pytest
from pydantic import ValidationError

from connector.domain.dictionary_dsl.specs import (
    DictionaryManifestSpec,
    DictionaryRegistrySpec,
    DictionarySpec,
)


def _valid_dictionary_spec_payload() -> dict:
    return {
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
                {"name": "ouid", "nullable": False},
                {"name": "name", "nullable": False},
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


def test_dictionary_spec_rejects_unknown_fields() -> None:
    payload = _valid_dictionary_spec_payload()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        DictionarySpec.model_validate(payload)


def test_dictionary_normalized_key_ops_whitelist_rejects_unknown_op() -> None:
    payload = _valid_dictionary_spec_payload()
    payload["schema"]["normalized_key"]["ops"] = [{"op": "to_int"}]

    with pytest.raises(ValidationError, match="ops not allowed in normalized_key"):
        DictionarySpec.model_validate(payload)


def test_dictionary_schema_rejects_key_column_conflict() -> None:
    payload = _valid_dictionary_spec_payload()
    payload["schema"]["value_columns"] = [
        {"name": "code", "nullable": False},
        {"name": "name", "nullable": False},
    ]

    with pytest.raises(ValidationError, match="schema.key_column must not be present"):
        DictionarySpec.model_validate(payload)


def test_dictionary_schema_requires_non_empty_value_columns() -> None:
    payload = _valid_dictionary_spec_payload()
    payload["schema"]["value_columns"] = []

    with pytest.raises(ValidationError, match="schema.value_columns must not be empty"):
        DictionarySpec.model_validate(payload)


def test_dictionary_source_csv_defaults_null_marker_to_null_literal() -> None:
    payload = _valid_dictionary_spec_payload()
    payload["source"]["csv"].pop("null_values")

    spec = DictionarySpec.model_validate(payload)

    assert spec.source.csv.null_values == ["NULL"]


def test_dictionary_schema_allows_nullable_value_column() -> None:
    payload = _valid_dictionary_spec_payload()
    payload["schema"]["value_columns"] = [
        {"name": "id", "nullable": False},
        {"name": "parent_id", "nullable": True},
    ]

    spec = DictionarySpec.model_validate(payload)

    assert spec.data_schema.value_columns[1].nullable is True


def test_dictionary_schema_rejects_duplicate_value_columns() -> None:
    payload = _valid_dictionary_spec_payload()
    payload["schema"]["value_columns"] = [
        {"name": "name", "nullable": False},
        {"name": "name", "nullable": True},
    ]

    with pytest.raises(ValidationError, match="duplicate column"):
        DictionarySpec.model_validate(payload)


def test_dictionary_registry_items_can_be_empty() -> None:
    spec = DictionaryRegistrySpec.model_validate(
        {
            "version": 1,
            "manifest": "dictionaries/manifest.custom.yaml",
            "items": {},
        }
    )

    assert spec.items == {}
    assert spec.manifest == "dictionaries/manifest.custom.yaml"


def test_dictionary_manifest_items_can_be_empty() -> None:
    spec = DictionaryManifestSpec.model_validate(
        {
            "version": 1,
            "items": {},
        }
    )

    assert spec.items == {}
