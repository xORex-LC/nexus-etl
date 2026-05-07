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
from connector.domain.transform_dsl import (
    load_mapping_spec_for_dataset,
    load_source_spec_for_dataset,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture(autouse=True)
def _reset_loader_runtime_state() -> None:
    configure_registry_path(None)
    configure_runtime_paths(None)
    yield
    configure_registry_path(None)
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
        "dataset: ignored\n",
    )

    try:
        configure_registry_path(None)
        configure_runtime_paths(RuntimePathOverrides(runtime_root=runtime_root))

        spec = load_source_spec_for_dataset("employees")

        assert spec.source.location == "./sources/employees.csv"
    finally:
        configure_registry_path(None)


def test_mapping_loader_prefers_source_projection_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _write(
        runtime_root / "datasets" / "registry.yaml",
        """
datasets:
  employees:
    mapping: employees/mapping.yaml
""".strip(),
    )
    _write(
        runtime_root / "etc" / "source-projection" / "employees" / "mapping.yaml",
        """
dataset: employees
source_columns: ["name"]
mapping:
  rules:
    - target: full_name
      source: name
      op: copy
""".strip(),
    )
    _write(
        runtime_root / "datasets" / "employees" / "mapping.yaml",
        """
dataset: ignored
source_columns: ["source_field"]
mapping:
  rules:
    - target: sink_field
      source: source_field
      op: copy
""".strip(),
    )

    try:
        configure_registry_path(None)
        configure_runtime_paths(RuntimePathOverrides(runtime_root=runtime_root))

        spec = load_mapping_spec_for_dataset("employees")

        assert spec.dataset == "employees"
        assert spec.source_columns == ["name"]
        assert spec.mapping.rules[0].source == "name"
    finally:
        configure_registry_path(None)


def test_registry_override_changes_active_registry_without_changing_runtime_roots(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    registry = tmp_path / "config" / "custom-registry.yaml"
    _write(
        registry,
        """
datasets:
  custom:
    source: custom/source.yaml
""".strip(),
    )
    _write(
        runtime_root / "datasets" / "registry.yaml",
        "datasets: {}\n",
    )
    _write(
        runtime_root / "etc" / "source-projection" / "custom" / "source.yaml",
        """
dataset: custom
source:
  type: file
  format: csv
  location: ./custom.csv
""".strip(),
    )

    try:
        configure_runtime_paths(RuntimePathOverrides(runtime_root=runtime_root))
        configure_registry_path(registry)

        spec = load_source_spec_for_dataset("custom")

        assert registry_path() == registry.resolve()
        assert datasets_root() == (runtime_root / "datasets").resolve()
        assert spec.source.location == "./custom.csv"
    finally:
        configure_registry_path(None)
        configure_runtime_paths(None)


def test_target_path_resolution_uses_target_projection_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _write(runtime_root / "datasets" / "registry.yaml", "datasets: {}\n")
    new_target = runtime_root / "etc" / "target-projection" / "targets" / "ankey.yaml"
    _write(new_target, "provider: ankey\n")

    configure_runtime_paths(RuntimePathOverrides(runtime_root=runtime_root))
    preferred = _resolve_target_path({"targets": {"ankey": "targets/ankey.yaml"}}, "ankey")
    assert preferred == new_target.resolve()


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
        "version: 999\nitems: {}\n",
    )

    try:
        configure_registry_path(None)
        configure_runtime_paths(RuntimePathOverrides(runtime_root=runtime_root))

        manifest = load_dictionary_manifest_spec_for_runtime()

        assert manifest.version == 1
        assert manifest.items == {}
    finally:
        configure_registry_path(None)


def test_dictionary_runtime_helpers_use_dictionary_specs_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _write(runtime_root / "datasets" / "registry.yaml", "datasets: {}\n")
    spec_path = runtime_root / "etc" / "dictionaries" / "employees" / "departments.dictionary.yaml"
    _write(
        spec_path,
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

    resolved = common_loader._resolve_dictionary_spec_path("employees/departments.dictionary.yaml")

    assert resolved == spec_path.resolve()
