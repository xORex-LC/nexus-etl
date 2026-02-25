from __future__ import annotations

import pytest

pl = pytest.importorskip("polars")

from connector.domain.dictionary_dsl.specs import DictionaryManifestSpec, DictionarySpec
from connector.domain.dsl.issues import DslLoadError
from connector.infra.dictionaries.backends.polars_backend import PolarsDictionaryBackend
from connector.infra.dictionaries.dsl_runtime import build_dictionary_dsl_runtime
from connector.infra.dictionaries.versioning import build_dictionary_schema_hash


def _spec(*, allow_duplicates: bool = False) -> DictionarySpec:
    return DictionarySpec.model_validate(
        {
            "dictionary": "organizations",
            "source": {
                "format": "csv",
                "location": "dictionaries/organizations.csv",
                "csv": {"delimiter": ",", "has_header": True, "encoding": "utf-8"},
            },
            "schema": {
                "key_column": "code",
                "value_columns": ["name", "ouid"],
                "normalized_key": {
                    "ops": [
                        {"op": "trim"},
                        {"op": "lower"},
                    ]
                },
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


def test_polars_backend_lookup_contains_and_canonicalize_with_normalization() -> None:
    spec = _spec()
    backend = PolarsDictionaryBackend(bundle=_bundle(spec))
    frame = pl.DataFrame(
        {
            "code": [" Org-1 ", "ORG-2"],
            "name": ["Org One", "Org Two"],
            "ouid": ["100", "200"],
        }
    )

    backend.load_dictionary_frame(
        dict_name="organizations",
        frame=frame,
        content_sha256="a" * 64,
    )

    assert backend.contains("organizations", "org-1") is True
    assert backend.contains("organizations", "missing") is False

    rows = backend.lookup("organizations", " ORG-1 ", fields=("name",), limit=1)
    assert rows == [{"name": "Org One"}]

    canonical = backend.canonicalize("organizations", "org-2")
    assert canonical == [{"code": "ORG-2", "name": "Org Two", "ouid": "200"}]


def test_polars_backend_rejects_duplicate_keys_when_not_allowed() -> None:
    spec = _spec(allow_duplicates=False)
    backend = PolarsDictionaryBackend(bundle=_bundle(spec))
    frame = pl.DataFrame(
        {
            "code": ["ORG-1", " org-1 "],
            "name": ["One", "One duplicate"],
            "ouid": ["100", "101"],
        }
    )

    with pytest.raises(DslLoadError) as exc_info:
        backend.load_dictionary_frame(
            dict_name="organizations",
            frame=frame,
            content_sha256="a" * 64,
        )

    assert exc_info.value.code == "DICT_SCHEMA_INVALID"


def test_polars_backend_allows_duplicates_and_honors_limit() -> None:
    spec = _spec(allow_duplicates=True)
    backend = PolarsDictionaryBackend(bundle=_bundle(spec))
    frame = pl.DataFrame(
        {
            "code": ["ORG-1", "org-1"],
            "name": ["One", "One duplicate"],
            "ouid": ["100", "101"],
        }
    )
    backend.load_dictionary_frame(
        dict_name="organizations",
        frame=frame,
        content_sha256="a" * 64,
    )

    rows = backend.lookup("organizations", "ORG-1", limit=1)
    assert len(rows) == 1
    assert rows[0]["code"] in {"ORG-1", "org-1"}


def test_polars_backend_rejects_unknown_projection_fields() -> None:
    spec = _spec()
    backend = PolarsDictionaryBackend(bundle=_bundle(spec))
    frame = pl.DataFrame(
        {
            "code": ["ORG-1"],
            "name": ["One"],
            "ouid": ["100"],
        }
    )
    backend.load_dictionary_frame(
        dict_name="organizations",
        frame=frame,
        content_sha256="a" * 64,
    )

    with pytest.raises(DslLoadError) as exc_info:
        backend.lookup("organizations", "ORG-1", fields=("missing",))

    assert exc_info.value.code == "DICT_SCHEMA_INVALID"


def test_polars_backend_accepts_empty_dataframe_when_columns_exist() -> None:
    spec = _spec()
    backend = PolarsDictionaryBackend(bundle=_bundle(spec))
    frame = pl.DataFrame(
        schema={
            "code": pl.Utf8,
            "name": pl.Utf8,
            "ouid": pl.Utf8,
        }
    )

    backend.load_dictionary_frame(
        dict_name="organizations",
        frame=frame,
        content_sha256="a" * 64,
    )

    assert backend.lookup("organizations", "ORG-1") == []
    assert backend.get_version_info("organizations").row_count == 0


def test_polars_backend_lazy_loader_loads_on_first_access() -> None:
    spec = _spec()
    backend = PolarsDictionaryBackend(bundle=_bundle(spec))
    calls: list[str] = []

    def _lazy_loader(dict_name: str) -> None:
        calls.append(dict_name)
        backend.load_dictionary_frame(
            dict_name=dict_name,
            frame=pl.DataFrame(
                {
                    "code": ["ORG-1"],
                    "name": ["Org One"],
                    "ouid": ["100"],
                }
            ),
            content_sha256="a" * 64,
        )

    backend.set_lazy_loader(_lazy_loader)

    assert backend.get_loaded_dict_names() == ()
    assert backend.lookup("organizations", "org-1", fields=("name",)) == [{"name": "Org One"}]
    assert backend.lookup("organizations", "ORG-1", fields=("name",)) == [{"name": "Org One"}]
    assert calls == ["organizations"]
    assert backend.get_loaded_dict_names() == ("organizations",)


def test_polars_backend_empty_runtime_treats_lookup_family_as_miss() -> None:
    empty_manifest = DictionaryManifestSpec.model_validate({"version": 1, "items": {}})
    empty_bundle = build_dictionary_dsl_runtime(specs={}, manifest_spec=empty_manifest)
    backend = PolarsDictionaryBackend(bundle=empty_bundle)

    assert backend.is_empty_runtime() is True
    assert backend.lookup("missing", "key") == []
    assert backend.canonicalize("missing", "key") == []
    assert backend.contains("missing", "key") is False
