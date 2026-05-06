from __future__ import annotations

from pathlib import Path

import pytest

from connector.common.runtime_paths import RuntimePathOverrides
from connector.domain.dictionary_dsl import load_dictionary_manifest_spec_for_runtime
from connector.domain.dsl.loader import (
    configure_registry_path,
    configure_runtime_paths,
    datasets_root,
    registry_path,
)
from connector.domain.dsl.loader import _common as common_loader
from connector.domain.target_dsl.loader import _resolve_target_path
from connector.domain.transform_dsl import load_source_spec_for_dataset


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture(autouse=True)
def _reset_loader_runtime_state() -> None:
    configure_runtime_paths(None)
    yield
    configure_runtime_paths(None)


def test_dsl_loader_uses_runtime_paths_default_registry(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    registry = runtime_root / "datasets" / "registry.yaml"
    _write(registry, "datasets: {}\n")

    try:
        configure_registry_path(None)
        configure_runtime_paths(RuntimePathOverrides(runtime_root=runtime_root))

        assert registry_path() == registry.resolve()
        assert datasets_root() == (runtime_root / "datasets").resolve()
    finally:
        configure_registry_path(None)


def test_source_loader_prefers_source_projection_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _write(
        runtime_root / "datasets" / "registry.yaml",
        """
datasets:
  employees:
    source: employees/source.yaml
""".strip(),
    )
    _write(
        runtime_root / "etc" / "source-projection" / "employees" / "source.yaml",
        """
dataset: employees
source:
  type: file
  format: csv
  location: ./sources/employees.csv
""".strip(),
    )
    _write(
        runtime_root / "datasets" / "employees" / "source.yaml",
        """
dataset: employees
source:
  type: file
  format: csv
  location: ./legacy/employees.csv
""".strip(),
    )

    try:
        configure_registry_path(None)
        configure_runtime_paths(RuntimePathOverrides(runtime_root=runtime_root))

        spec = load_source_spec_for_dataset("employees")

        assert spec.source.location == "./sources/employees.csv"
    finally:
        configure_registry_path(None)


def test_source_loader_falls_back_to_legacy_datasets_root_when_projection_file_is_missing(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    _write(
        runtime_root / "datasets" / "registry.yaml",
        """
datasets:
  employees:
    source: employees/source.yaml
""".strip(),
    )
    _write(
        runtime_root / "datasets" / "employees" / "source.yaml",
        """
dataset: employees
source:
  type: file
  format: csv
  location: ./legacy/employees.csv
""".strip(),
    )

    try:
        configure_registry_path(None)
        configure_runtime_paths(RuntimePathOverrides(runtime_root=runtime_root))

        spec = load_source_spec_for_dataset("employees")

        assert spec.source.location == "./legacy/employees.csv"
    finally:
        configure_registry_path(None)


def test_registry_override_resolves_stage_specs_relative_to_override_root(tmp_path: Path) -> None:
    registry = tmp_path / "custom-registry.yaml"
    _write(
        registry,
        """
datasets:
  custom:
    source: source.yaml
""".strip(),
    )
    _write(
        tmp_path / "source.yaml",
        """
dataset: custom
source:
  type: file
  format: csv
  location: /tmp/custom.csv
""".strip(),
    )

    try:
        configure_runtime_paths(None)
        configure_registry_path(registry)

        spec = load_source_spec_for_dataset("custom")

        assert registry_path() == registry.resolve()
        assert datasets_root() == tmp_path.resolve()
        assert spec.source.location == "/tmp/custom.csv"
    finally:
        configure_registry_path(None)


def test_target_path_resolution_prefers_target_projection_root_and_falls_back_to_legacy_dataset_root(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    _write(runtime_root / "datasets" / "registry.yaml", "datasets: {}\n")
    new_target = runtime_root / "etc" / "target-projection" / "targets" / "ankey.yaml"
    legacy_target = runtime_root / "datasets" / "targets" / "ankey.yaml"
    _write(new_target, "provider: ankey\n")
    _write(legacy_target, "provider: legacy\n")

    configure_runtime_paths(RuntimePathOverrides(runtime_root=runtime_root))
    preferred = _resolve_target_path({"targets": {"ankey": "targets/ankey.yaml"}}, "ankey")
    assert preferred == new_target.resolve()

    new_target.unlink()
    fallback = _resolve_target_path({"targets": {"ankey": "targets/ankey.yaml"}}, "ankey")
    assert fallback == legacy_target.resolve()


def test_dictionary_manifest_loader_prefers_dictionary_specs_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _write(
        runtime_root / "datasets" / "registry.yaml",
        """
dictionaries:
  version: 1
  manifest: employees/manifest.yaml
  items: {}
""".strip(),
    )
    _write(
        runtime_root / "etc" / "dictionaries" / "employees" / "manifest.yaml",
        """
version: 1
items: {}
""".strip(),
    )
    _write(
        runtime_root / "datasets" / "employees" / "manifest.yaml",
        """
version: 1
items:
  legacy:
    csv_path: legacy.csv
    content_sha256: "deadbeef"
    schema_hash: "schema"
    row_count: 1
    updated_at_utc: "2026-01-01T00:00:00Z"
    owner: "legacy"
""".strip(),
    )

    try:
        configure_registry_path(None)
        configure_runtime_paths(RuntimePathOverrides(runtime_root=runtime_root))

        manifest = load_dictionary_manifest_spec_for_runtime()

        assert manifest.version == 1
        assert manifest.items == {}
    finally:
        configure_registry_path(None)


def test_dictionary_runtime_helpers_fall_back_to_legacy_dataset_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _write(runtime_root / "datasets" / "registry.yaml", "datasets: {}\n")
    legacy_spec = runtime_root / "datasets" / "dictionaries" / "departments.dictionary.yaml"
    _write(
        legacy_spec,
        """
dictionary: departments
source:
  format: csv
  location: departments.csv
schema:
  key_column:
    name: code
  value_columns:
    - name: name
      nullable: false
""".strip(),
    )

    configure_runtime_paths(RuntimePathOverrides(runtime_root=runtime_root))

    resolved = common_loader._resolve_dictionary_spec_path("dictionaries/departments.dictionary.yaml")

    assert resolved == legacy_spec.resolve()
