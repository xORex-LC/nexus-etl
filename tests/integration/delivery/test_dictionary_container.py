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

from connector.common.runtime_paths import RuntimePathOverrides
from connector.config.models import AppConfig, DictionaryConfig
from connector.delivery.cli.containers import AppContainer
from connector.delivery.cli.dictionaries_container import DictionaryContainer
from connector.domain.dsl.loader import configure_registry_path, configure_runtime_paths
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
            "location": "organizations.csv",
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
        "lookup": {"allow_duplicates": False},
    }


def _write_datasets_fixture(
    tmp_path: Path,
    *,
    include_dictionaries_section: bool = True,
    empty_dictionary_items: bool = False,
    fingerprint_mismatch: bool = False,
    empty_csv: bool = False,
) -> tuple[Path, Path, Path]:
    datasets_root = tmp_path / "datasets"
    dictionary_specs_root = tmp_path / "dictionary-specs"
    dictionary_data_root = tmp_path / "dictionaries"
    datasets_root.mkdir(parents=True, exist_ok=True)
    dictionary_specs_root.mkdir(parents=True, exist_ok=True)
    dictionary_data_root.mkdir(parents=True, exist_ok=True)

    spec_payload = _dictionary_spec_payload()
    spec_model = DictionarySpec.model_validate(spec_payload)

    csv_bytes = (
        b"code,name,ouid\n"
        if empty_csv
        else b"code,name,ouid\n ORG-1 ,Org One,100\nORG-2,Org Two,200\n"
    )
    (dictionary_data_root / "organizations.csv").write_bytes(csv_bytes)
    (dictionary_specs_root / "organizations.dictionary.yaml").write_text(
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
                "manifest": "manifest.custom.yaml",
                "items": (
                    {}
                    if empty_dictionary_items
                    else {
                        "organizations": {
                            "spec": "organizations.dictionary.yaml",
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
    (datasets_root / "registry.yaml").write_text(
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
                        "csv_path": "organizations.csv",
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
        (dictionary_specs_root / "manifest.custom.yaml").write_text(
            yaml.safe_dump(manifest_payload, sort_keys=False),
            encoding="utf-8",
        )

    return datasets_root, dictionary_specs_root, dictionary_data_root


def _make_container(
    tmp_path: Path,
    *,
    include_dictionaries_section: bool = True,
    empty_dictionary_items: bool = False,
    fingerprint_mismatch: bool = False,
    empty_csv: bool = False,
    load_strategy: str = "eager",
) -> DictionaryContainer:
    datasets_root, dictionary_specs_root, dictionary_data_root = _write_datasets_fixture(
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
    container.registry_path.override(datasets_root / "registry.yaml")
    container.dictionary_specs_root.override(dictionary_specs_root)
    container.dictionary_data_root.override(dictionary_data_root)
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
    datasets_root, dictionary_specs_root, dictionary_data_root = _write_datasets_fixture(tmp_path)
    container = DictionaryContainer()
    container.settings.override(
        DictionaryConfig(
            fingerprint_salt="repo-fixture-test",
            lookup_hit_sample_percent=0,
            lookup_miss_sample_percent=0,
        )
    )
    container.registry_path.override(None)
    container.dictionary_specs_root.override(dictionary_specs_root)
    container.dictionary_data_root.override(dictionary_data_root)
    try:
        configure_registry_path(datasets_root / "registry.yaml")
        configure_runtime_paths(
            RuntimePathOverrides(
                dictionary_specs_root=dictionary_specs_root,
                dictionary_data_root=dictionary_data_root,
            )
        )
        container.init_resources()
        backend = container.backend()
        provider = container.provider()
        assert isinstance(backend, PolarsDictionaryBackend)
        assert provider is not None
        assert backend.get_loaded_dict_names() == backend.get_declared_dict_names()
        assert backend.get_loaded_dict_names()
    finally:
        configure_registry_path(None)
        configure_runtime_paths(None)
        container.shutdown_resources()


def test_app_container_resolves_dictionary_roots_against_runtime_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    datasets_root, dictionary_specs_root, dictionary_data_root = _write_datasets_fixture(tmp_path)
    outside_cwd = tmp_path / "outside-cwd"
    outside_cwd.mkdir(parents=True, exist_ok=True)

    app_config = AppConfig.model_validate(
        {
            "runtime": {
                "runtime_root": str(tmp_path),
                "datasets_root": "./datasets",
                "dictionary_specs_root": "./dictionary-specs",
                "dictionary_data_root": "./dictionaries",
            },
            "dataset": {
                "registry_path": "./datasets/registry.yaml",
            },
            "dictionary": {
                "fingerprint_salt": "repo-fixture-test",
                "lookup_hit_sample_percent": 0,
                "lookup_miss_sample_percent": 0,
            },
        }
    )
    container = AppContainer()
    container.app_config.override(app_config)

    try:
        monkeypatch.chdir(outside_cwd)
        assert Path(container._dictionary_specs_root()) == dictionary_specs_root.resolve()
        assert Path(container._dictionary_data_root()) == dictionary_data_root.resolve()

        dictionary_container = container.dictionary()
        dictionary_container.init_resources()
        provider = dictionary_container.provider()
        assert provider is not None
        assert provider.contains("organizations", "org-1") is True
    finally:
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
