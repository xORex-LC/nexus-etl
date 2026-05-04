"""
Интеграционные тесты lifecycle для DictionaryContainer.

Проверяют:
1. `init_resources()` на корректных dictionary DSL/CSV данных создаёт backend Resource.
2. `provider()` имеет singleton semantics и работает как `DictionaryProviderPort` adapter.
3. broken fingerprint → fail-fast `DslLoadError`.
4. `shutdown_resources()` завершается без ошибок (teardown backend = no-op).
5. Отсутствие секции `dictionaries` в registry -> graceful disabled mode.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytest.importorskip("polars")

from connector.config.models import DictionaryConfig
from connector.delivery.cli.dictionaries_container import DictionaryContainer
from connector.domain.dsl.loader import configure_registry_path
from connector.domain.dictionary_dsl.specs import DictionarySpec
from connector.domain.dsl.issues import DslLoadError
from connector.infra.dictionaries.backends.polars_backend import PolarsDictionaryBackend
from connector.infra.dictionaries.versioning import (
    build_content_sha256_bytes,
    build_dictionary_schema_hash,
)


def _dictionary_spec_payload() -> dict[str, Any]:
    return {
        "dictionary": "organizations",
        "source": {
            "format": "csv",
            "location": "dictionaries/organizations.csv",
            "csv": {"delimiter": ",", "has_header": True, "encoding": "utf-8"},
        },
        "schema": {
            "key_column": "code",
            "value_columns": ["name", "ouid"],
            "normalized_key": {"ops": [{"op": "trim"}, {"op": "lower"}]},
        },
        "lookup": {"allow_duplicates": False},
    }


def _write_datasets_fixture(
    tmp_path: Path,
    *,
    include_dictionaries_section: bool = True,
    empty_dictionary_items: bool = False,
    fingerprint_mismatch: bool = False,
    empty_csv: bool = False,
) -> Path:
    datasets_root = tmp_path / "datasets"
    dictionaries_dir = datasets_root / "dictionaries"
    dictionaries_dir.mkdir(parents=True, exist_ok=True)

    spec_payload = _dictionary_spec_payload()
    spec_model = DictionarySpec.model_validate(spec_payload)

    csv_bytes = (
        b"code,name,ouid\n"
        if empty_csv
        else b"code,name,ouid\n ORG-1 ,Org One,100\nORG-2,Org Two,200\n"
    )
    (dictionaries_dir / "organizations.csv").write_bytes(csv_bytes)
    (dictionaries_dir / "organizations.dictionary.yaml").write_text(
        yaml.safe_dump(spec_payload, sort_keys=False),
        encoding="utf-8",
    )

    registry_payload: dict[str, Any]
    if include_dictionaries_section:
        registry_payload = {
            "version": 1,
            "datasets": {},
            "dictionaries": {
                "version": 1,
                "manifest": "dictionaries/manifest.custom.yaml",
                "items": (
                    {}
                    if empty_dictionary_items
                    else {
                        "organizations": {
                            "spec": "dictionaries/organizations.dictionary.yaml",
                            "enabled": True,
                        }
                    }
                ),
            },
        }
    else:
        registry_payload = {
            "version": 1,
            "datasets": {},
        }
    (datasets_root / "registry.yml").write_text(
        yaml.safe_dump(registry_payload, sort_keys=False),
        encoding="utf-8",
    )

    if include_dictionaries_section:
        manifest_payload = {
            "version": 1,
            "items": (
                {}
                if empty_dictionary_items
                else {
                    "organizations": {
                        "csv_path": "dictionaries/organizations.csv",
                        "content_sha256": (
                            "f" * 64
                            if fingerprint_mismatch
                            else build_content_sha256_bytes(csv_bytes)
                        ),
                        "schema_hash": build_dictionary_schema_hash(spec_model),
                        "row_count": 0 if empty_csv else 2,
                        "updated_at_utc": "2026-02-23T12:00:00Z",
                        "owner": "tests",
                    }
                }
            ),
        }
        (dictionaries_dir / "manifest.custom.yaml").write_text(
            yaml.safe_dump(manifest_payload, sort_keys=False),
            encoding="utf-8",
        )

    return datasets_root


def _make_container(
    tmp_path: Path,
    *,
    include_dictionaries_section: bool = True,
    empty_dictionary_items: bool = False,
    fingerprint_mismatch: bool = False,
    empty_csv: bool = False,
    load_strategy: str = "eager",
) -> DictionaryContainer:
    datasets_root = _write_datasets_fixture(
        tmp_path,
        include_dictionaries_section=include_dictionaries_section,
        empty_dictionary_items=empty_dictionary_items,
        fingerprint_mismatch=fingerprint_mismatch,
        empty_csv=empty_csv,
    )
    container = DictionaryContainer()
    container.settings.override(
        DictionaryConfig(
            load_strategy=load_strategy,
            fingerprint_salt="test-salt",
            lookup_hit_sample_percent=0,
            lookup_miss_sample_percent=0,
        )
    )
    container.datasets_root.override(datasets_root)
    return container


def test_dictionary_container_init_resources_and_provider_singleton(tmp_path: Path) -> None:
    container = _make_container(tmp_path)
    try:
        container.init_resources()

        backend = container.backend()
        provider_a = container.provider()
        provider_b = container.provider()

        assert isinstance(backend, PolarsDictionaryBackend)
        assert provider_a is not None
        assert provider_a is provider_b
        assert provider_a.contains("organizations", "org-1") is True
        assert provider_a.lookup("organizations", "org-2", fields=("name",), limit=1) == [{"name": "Org Two"}]
    finally:
        container.shutdown_resources()


def test_dictionary_container_fails_fast_on_fingerprint_mismatch(tmp_path: Path) -> None:
    container = _make_container(tmp_path, fingerprint_mismatch=True)
    try:
        with pytest.raises(DslLoadError) as exc_info:
            container.init_resources()
        assert exc_info.value.code == "DICT_SOURCE_FINGERPRINT_MISMATCH"
    finally:
        container.shutdown_resources()


def test_dictionary_container_shutdown_resources_noop_teardown(tmp_path: Path) -> None:
    container = _make_container(tmp_path)
    container.init_resources()
    container.shutdown_resources()


def test_dictionary_container_disabled_mode_when_registry_has_no_dictionaries_section(tmp_path: Path) -> None:
    container = _make_container(tmp_path, include_dictionaries_section=False)
    try:
        container.init_resources()
        assert container.backend() is None
        assert container.provider() is None
    finally:
        container.shutdown_resources()


def test_dictionary_container_empty_items_registry_is_valid_empty_runtime(tmp_path: Path) -> None:
    container = _make_container(tmp_path, empty_dictionary_items=True)
    try:
        container.init_resources()
        backend = container.backend()
        provider = container.provider()
        assert isinstance(backend, PolarsDictionaryBackend)
        assert backend.get_loaded_dict_names() == ()
        assert provider is not None
    finally:
        container.shutdown_resources()


def test_dictionary_container_bootstrap_from_active_registry_path_init_success(tmp_path: Path) -> None:
    datasets_root = _write_datasets_fixture(tmp_path)
    container = DictionaryContainer()
    container.settings.override(
        DictionaryConfig(
            fingerprint_salt="repo-fixture-test",
            lookup_hit_sample_percent=0,
            lookup_miss_sample_percent=0,
        )
    )
    container.datasets_root.override(None)
    try:
        configure_registry_path(datasets_root / "registry.yml")
        container.init_resources()
        backend = container.backend()
        provider = container.provider()
        assert isinstance(backend, PolarsDictionaryBackend)
        assert provider is not None
        assert backend.get_loaded_dict_names() == backend.get_declared_dict_names()
        assert backend.get_loaded_dict_names()
    finally:
        configure_registry_path(None)
        container.shutdown_resources()


def test_dictionary_container_lazy_mode_loads_on_first_access(tmp_path: Path) -> None:
    container = _make_container(tmp_path, load_strategy="lazy")
    try:
        container.init_resources()
        backend = container.backend()
        provider = container.provider()
        assert isinstance(backend, PolarsDictionaryBackend)
        assert provider is not None
        assert backend.get_loaded_dict_names() == ()

        assert provider.contains("organizations", "org-1") is True
        assert backend.get_loaded_dict_names() == ("organizations",)

        snapshot = container.telemetry().snapshot()
        assert snapshot["summary"]["load_strategy"] == "lazy"
        assert snapshot["summary"]["loaded_count"] == 1
        assert snapshot["dictionaries_detail"]["organizations"]["row_count"] == 2
    finally:
        container.shutdown_resources()


def test_dictionary_container_lazy_mode_defers_fingerprint_error_until_first_access(tmp_path: Path) -> None:
    container = _make_container(tmp_path, fingerprint_mismatch=True, load_strategy="lazy")
    try:
        container.init_resources()
        provider = container.provider()
        assert provider is not None
        with pytest.raises(DslLoadError) as exc_info:
            provider.lookup("organizations", "org-1")
        assert exc_info.value.code == "DICT_SOURCE_FINGERPRINT_MISMATCH"
    finally:
        container.shutdown_resources()


def test_dictionary_container_empty_csv_records_warning_in_telemetry_snapshot(tmp_path: Path) -> None:
    container = _make_container(tmp_path, empty_csv=True)
    try:
        container.init_resources()
        snapshot = container.telemetry().snapshot()
        assert snapshot["summary"]["warnings_count"] == 1
        assert snapshot["anomalies"][0]["code"] == "DICT_SOURCE_EMPTY"
        assert snapshot["dictionaries_detail"]["organizations"]["row_count"] == 0
        assert snapshot["dictionaries_detail"]["organizations"]["fingerprint_kind"] == "content_sha256"
    finally:
        container.shutdown_resources()
