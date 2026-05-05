from __future__ import annotations

from pathlib import Path

import pytest

from connector.domain.dictionary_dsl import loader as dictionary_loader
from connector.domain.dsl.issues import DslLoadError


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _patch_repo_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(dictionary_loader, "_repo_root", lambda: root)
    monkeypatch.setattr(dictionary_loader, "_default_repo_root", lambda: root)
    monkeypatch.setattr(
        dictionary_loader,
        "_active_registry_path",
        lambda: root / "datasets" / "registry.yml",
    )
    monkeypatch.setattr(
        dictionary_loader,
        "_active_datasets_root",
        lambda: root / "datasets",
    )


def test_optional_registry_loader_returns_none_when_section_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(
        tmp_path / "datasets" / "registry.yml",
        """
datasets:
  employees:
    source: employees.source.yaml
""".strip(),
    )
    _patch_repo_root(monkeypatch, tmp_path)

    result = dictionary_loader.load_optional_dictionary_registry_spec_for_runtime()

    assert result is None


def test_registry_loader_accepts_empty_items_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(
        tmp_path / "datasets" / "registry.yml",
        """
dictionaries:
  version: 1
  manifest: dictionaries/manifest.custom.yaml
  items: {}
""".strip(),
    )
    _patch_repo_root(monkeypatch, tmp_path)

    spec = dictionary_loader.load_dictionary_registry_spec_for_runtime()

    assert spec.version == 1
    assert spec.manifest == "dictionaries/manifest.custom.yaml"
    assert spec.items == {}


def test_registry_loader_wraps_invalid_registry_as_dict_dsl_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(
        tmp_path / "datasets" / "registry.yml",
        """
dictionaries: []
""".strip(),
    )
    _patch_repo_root(monkeypatch, tmp_path)

    with pytest.raises(DslLoadError) as exc_info:
        dictionary_loader.load_dictionary_registry_spec_for_runtime()

    assert exc_info.value.code == "DICT_DSL_REGISTRY_INVALID"


def test_load_enabled_dictionary_specs_wraps_invalid_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(
        tmp_path / "datasets" / "registry.yml",
        """
dictionaries:
  version: 1
  manifest: dictionaries/manifest.custom.yaml
  items:
    organizations:
      spec: dictionaries/organizations.dictionary.yaml
      enabled: true
""".strip(),
    )
    _write(
        tmp_path / "datasets" / "dictionaries" / "organizations.dictionary.yaml",
        """
dictionary: organizations
source:
  format: csv
  location: dictionaries/organizations.csv
schema:
  key_column:
    name: code
  value_columns: []
""".strip(),
    )
    _patch_repo_root(monkeypatch, tmp_path)

    with pytest.raises(DslLoadError) as exc_info:
        dictionary_loader.load_enabled_dictionary_specs_for_runtime()

    assert exc_info.value.code == "DICT_DSL_SPEC_INVALID"


def test_load_enabled_dictionary_specs_validates_registry_key_matches_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(
        tmp_path / "datasets" / "registry.yml",
        """
dictionaries:
  version: 1
  manifest: dictionaries/manifest.custom.yaml
  items:
    organizations:
      spec: dictionaries/organizations.dictionary.yaml
      enabled: true
""".strip(),
    )
    _write(
        tmp_path / "datasets" / "dictionaries" / "organizations.dictionary.yaml",
        """
dictionary: departments
source:
  format: csv
  location: dictionaries/organizations.csv
schema:
  key_column:
    name: code
  value_columns:
    - name: name
      nullable: false
""".strip(),
    )
    _patch_repo_root(monkeypatch, tmp_path)

    with pytest.raises(DslLoadError) as exc_info:
        dictionary_loader.load_enabled_dictionary_specs_for_runtime()

    assert exc_info.value.code == "DICT_DSL_SPEC_INVALID"
    assert "registry key" in str(exc_info.value)


def test_manifest_loader_raises_missing_code_when_file_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(
        tmp_path / "datasets" / "registry.yml",
        """
dictionaries:
  version: 1
  manifest: dictionaries/manifest.custom.yaml
  items: {}
""".strip(),
    )
    _patch_repo_root(monkeypatch, tmp_path)

    with pytest.raises(DslLoadError) as exc_info:
        dictionary_loader.load_dictionary_manifest_spec_for_runtime()

    assert exc_info.value.code == "DICT_SOURCE_MANIFEST_MISSING"


def test_manifest_loader_wraps_invalid_structure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(
        tmp_path / "datasets" / "registry.yml",
        """
dictionaries:
  version: 1
  manifest: dictionaries/manifest.custom.yaml
  items: {}
""".strip(),
    )
    _write(
        tmp_path / "datasets" / "dictionaries" / "manifest.custom.yaml",
        """
- bad
""".strip(),
    )
    _patch_repo_root(monkeypatch, tmp_path)

    with pytest.raises(DslLoadError) as exc_info:
        dictionary_loader.load_dictionary_manifest_spec_for_runtime()

    assert exc_info.value.code == "DICT_SOURCE_MANIFEST_INVALID"


def test_manifest_loader_loads_valid_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(
        tmp_path / "datasets" / "registry.yml",
        """
dictionaries:
  version: 1
  manifest: dictionaries/manifest.custom.yaml
  items: {}
""".strip(),
    )
    _write(
        tmp_path / "datasets" / "dictionaries" / "manifest.custom.yaml",
        """
version: 1
items:
  organizations:
    csv_path: dictionaries/organizations.csv
    content_sha256: "0d7f"
    schema_hash: "8d2c"
    row_count: 1
    updated_at_utc: "2026-02-19T19:31:00Z"
    owner: "dataset-employees"
""".strip(),
    )
    _patch_repo_root(monkeypatch, tmp_path)

    manifest = dictionary_loader.load_dictionary_manifest_spec_for_runtime()

    assert manifest.version == 1
    assert manifest.items["organizations"].row_count == 1
