from __future__ import annotations

import pytest

pl = pytest.importorskip("polars")

from connector.domain.dictionary_dsl.specs import DictionaryManifestSpec, DictionarySpec
from connector.infra.dictionaries.backends.polars_backend import PolarsDictionaryBackend
from connector.infra.dictionaries.dsl_runtime import build_dictionary_dsl_runtime
from connector.infra.dictionaries.provider import PolarsDictionaryProvider
from connector.infra.dictionaries.telemetry import DictionaryTelemetry
from connector.infra.dictionaries.versioning import build_dictionary_schema_hash


def _spec(*, allow_duplicates: bool = False) -> DictionarySpec:
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
                "normalized_key": {"ops": [{"op": "trim"}, {"op": "lower"}]},
            },
            "lookup": {"allow_duplicates": allow_duplicates},
        }
    )


def _bundle(spec: DictionarySpec) -> object:
    manifest = DictionaryManifestSpec.model_validate(
        {
            "version": 1,
            "items": {
                "organizations": {
                    "csv_path": spec.source.location,
                    "content_sha256": "1" * 64,
                    "schema_hash": build_dictionary_schema_hash(spec),
                    "row_count": 0,
                    "updated_at_utc": "2026-02-23T12:00:00Z",
                    "owner": "dataset-employees",
                }
            },
        }
    )
    return build_dictionary_dsl_runtime(specs={"organizations": spec}, manifest_spec=manifest)


def _loaded_backend() -> PolarsDictionaryBackend:
    backend = PolarsDictionaryBackend(bundle=_bundle(_spec()))
    backend.load_dictionary_frame(
        dict_name="organizations",
        frame=pl.DataFrame(
            {
                "code": [" Org-1 ", "ORG-2"],
                "name": ["Org One", "Org Two"],
                "ouid": ["100", "200"],
            }
        ),
        content_sha256="a" * 64,
    )
    return backend


def test_provider_delegates_lookup_contains_canonicalize_and_updates_telemetry() -> None:
    telemetry = DictionaryTelemetry(
        fingerprint_salt="salt-v1",
        lookup_hit_sample_percent=0,
        lookup_miss_sample_percent=0,
    )
    provider = PolarsDictionaryProvider(backend=_loaded_backend(), telemetry=telemetry)

    lookup_rows = provider.lookup("organizations", " ORG-1 ", fields=("name",), limit=1)
    lookup_miss = provider.lookup("organizations", "missing")
    contains_hit = provider.contains("organizations", "org-2")
    contains_miss = provider.contains("organizations", "missing")
    canonical = provider.canonicalize("organizations", " org-1 ")

    assert lookup_rows == [{"name": "Org One"}]
    assert lookup_miss == []
    assert contains_hit is True
    assert contains_miss is False
    assert canonical == [{"code": " Org-1 ", "name": "Org One", "ouid": "100"}]

    snapshot = telemetry.snapshot()
    assert snapshot["aggregate"] == {
        "lookup_total": 5,
        "lookup_hit": 3,
        "lookup_miss": 2,
        "lookup_error": 0,
    }
    assert snapshot["dictionaries_detail"]["organizations"]["lookup_total"] == 5
    assert snapshot["dictionaries_detail"]["organizations"]["lookup_hit"] == 3
    assert snapshot["dictionaries_detail"]["organizations"]["lookup_miss"] == 2
    assert snapshot["dictionaries_detail"]["organizations"]["lookup_error"] == 0


def test_provider_error_path_increments_lookup_error_counter() -> None:
    telemetry = DictionaryTelemetry(
        fingerprint_salt="salt-v1",
        lookup_hit_sample_percent=0,
        lookup_miss_sample_percent=0,
    )
    provider = PolarsDictionaryProvider(backend=_loaded_backend(), telemetry=telemetry)

    with pytest.raises(KeyError):
        provider.lookup("missing_dictionary", "secret-key")

    snapshot = telemetry.snapshot()
    assert snapshot["aggregate"] == {
        "lookup_total": 1,
        "lookup_hit": 0,
        "lookup_miss": 0,
        "lookup_error": 1,
    }
    assert snapshot["dictionaries_detail"]["missing_dictionary"]["lookup_error"] == 1


def test_provider_empty_runtime_treats_unknown_dict_as_miss_not_error() -> None:
    empty_bundle = build_dictionary_dsl_runtime(
        specs={},
        manifest_spec=DictionaryManifestSpec.model_validate({"version": 1, "items": {}}),
    )
    backend = PolarsDictionaryBackend(bundle=empty_bundle)
    telemetry = DictionaryTelemetry(
        fingerprint_salt="salt-v1",
        lookup_hit_sample_percent=0,
        lookup_miss_sample_percent=0,
    )
    provider = PolarsDictionaryProvider(backend=backend, telemetry=telemetry)

    assert provider.lookup("unknown", "key") == []
    assert provider.canonicalize("unknown", "key") == []
    assert provider.contains("unknown", "key") is False

    snapshot = telemetry.snapshot()
    assert snapshot["aggregate"] == {
        "lookup_total": 3,
        "lookup_hit": 0,
        "lookup_miss": 3,
        "lookup_error": 0,
    }
    assert snapshot["dictionaries_detail"]["unknown"]["lookup_miss"] == 3
