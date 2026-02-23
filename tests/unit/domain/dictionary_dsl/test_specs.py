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
            },
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
    payload["schema"]["value_columns"] = ["code", "name"]

    with pytest.raises(ValidationError, match="schema.key_column must not be present"):
        DictionarySpec.model_validate(payload)


def test_dictionary_schema_requires_non_empty_value_columns() -> None:
    payload = _valid_dictionary_spec_payload()
    payload["schema"]["value_columns"] = []

    with pytest.raises(ValidationError, match="schema.value_columns must not be empty"):
        DictionarySpec.model_validate(payload)


def test_dictionary_registry_items_can_be_empty() -> None:
    spec = DictionaryRegistrySpec.model_validate(
        {
            "version": 1,
            "items": {},
        }
    )

    assert spec.items == {}


def test_dictionary_manifest_items_can_be_empty() -> None:
    spec = DictionaryManifestSpec.model_validate(
        {
            "version": 1,
            "items": {},
        }
    )

    assert spec.items == {}

