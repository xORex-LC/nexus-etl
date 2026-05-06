from __future__ import annotations

from pathlib import Path

import pytest

from connector.common.runtime_paths import (
    RuntimeLayoutError,
    RuntimePathOverrides,
    detect_runtime_paths,
    resolve_registry_path_for_datasets_root,
)


def _write(path: Path, content: str = "datasets: {}\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_detect_runtime_paths_prefers_explicit_runtime_root_override(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _write(runtime_root / "datasets" / "registry.yaml")

    paths = detect_runtime_paths(
        overrides=RuntimePathOverrides(runtime_root=runtime_root),
        argv0="/ignored/bin/nexus",
        module_file=tmp_path / "src" / "module.py",
    )

    assert paths.root == runtime_root.resolve()
    assert paths.datasets_root == (runtime_root / "datasets").resolve()
    assert paths.default_registry_path == (runtime_root / "datasets" / "registry.yaml").resolve()
    assert paths.config_root == (runtime_root / "etc").resolve()
    assert paths.dictionary_specs_root == (runtime_root / "etc" / "dictionaries").resolve()
    assert paths.dictionary_data_root == (runtime_root / "dictionaries").resolve()
    assert paths.source_data_root == (runtime_root / "examples" / "sources").resolve()


def test_detect_runtime_paths_uses_standalone_layout_near_argv0(tmp_path: Path) -> None:
    dist_root = tmp_path / "nexus.dist"
    _write(dist_root / "datasets" / "registry.yaml")

    paths = detect_runtime_paths(
        overrides=RuntimePathOverrides(),
        argv0=dist_root / "nexus",
        module_file=tmp_path / "elsewhere" / "module.py",
    )

    assert paths.root == dist_root.resolve()
    assert paths.cache_root == (dist_root / "var" / "cache").resolve()
    assert paths.resolve_report_file("report.json") == (dist_root / "reports" / "report.json").resolve()


def test_detect_runtime_paths_uses_module_parent_search_for_dev_checkout(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    module_file = repo_root / "connector" / "common" / "runtime_paths.py"
    _write(repo_root / "datasets" / "registry.yaml")

    paths = detect_runtime_paths(
        overrides=RuntimePathOverrides(),
        argv0="/outside/bin/nexus",
        module_file=module_file,
    )

    assert paths.root == repo_root.resolve()
    assert paths.default_registry_path == (repo_root / "datasets" / "registry.yaml").resolve()


def test_detect_runtime_paths_accepts_legacy_registry_yml_fallback(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    module_file = repo_root / "connector" / "common" / "runtime_paths.py"
    _write(repo_root / "datasets" / "registry.yml")

    paths = detect_runtime_paths(
        overrides=RuntimePathOverrides(),
        argv0="/outside/bin/nexus",
        module_file=module_file,
    )

    assert paths.default_registry_path == (repo_root / "datasets" / "registry.yml").resolve()


def test_detect_runtime_paths_raises_when_layout_is_missing(tmp_path: Path) -> None:
    with pytest.raises(RuntimeLayoutError):
        detect_runtime_paths(
            overrides=RuntimePathOverrides(),
            argv0=tmp_path / "bin" / "nexus",
            module_file=tmp_path / "src" / "module.py",
        )


def test_resolve_registry_path_for_datasets_root_prefers_yaml(tmp_path: Path) -> None:
    datasets_root = tmp_path / "datasets"
    _write(datasets_root / "registry.yml")
    _write(datasets_root / "registry.yaml")

    assert resolve_registry_path_for_datasets_root(datasets_root) == (
        datasets_root / "registry.yaml"
    ).resolve()


def test_detect_runtime_paths_applies_relative_overrides_from_runtime_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _write(runtime_root / "datasets" / "registry.yaml")

    paths = detect_runtime_paths(
        overrides=RuntimePathOverrides(
            runtime_root=runtime_root,
            dictionary_specs_root="./etc/dicts",
            source_projection_root="./etc/sources",
            target_projection_root="./etc/targets",
        ),
        argv0="/ignored/bin/nexus",
        module_file=tmp_path / "src" / "module.py",
    )

    assert paths.dictionary_specs_root == (runtime_root / "etc" / "dicts").resolve()
    assert paths.source_projection_root == (runtime_root / "etc" / "sources").resolve()
    assert paths.target_projection_root == (runtime_root / "etc" / "targets").resolve()


def test_runtime_paths_resolve_resource_families_against_expected_roots(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _write(runtime_root / "datasets" / "registry.yaml")
    paths = detect_runtime_paths(
        overrides=RuntimePathOverrides(runtime_root=runtime_root),
        argv0="/ignored/bin/nexus",
        module_file=tmp_path / "src" / "module.py",
    )

    assert paths.resolve_dataset_stage_ref("employees/mapping.yaml") == (
        runtime_root / "datasets" / "employees" / "mapping.yaml"
    ).resolve()
    assert paths.resolve_dictionary_spec_ref("employees/departments.dictionary.yaml") == (
        runtime_root / "etc" / "dictionaries" / "employees" / "departments.dictionary.yaml"
    ).resolve()
    assert paths.resolve_dictionary_data_ref("employees/departments.csv") == (
        runtime_root / "dictionaries" / "employees" / "departments.csv"
    ).resolve()
    assert paths.resolve_source_data_ref("employees.csv") == (
        runtime_root / "examples" / "sources" / "employees.csv"
    ).resolve()
    assert paths.resolve_cache_db_file() == (
        runtime_root / "var" / "cache" / "ankey_cache.sqlite3"
    ).resolve()
    assert paths.resolve_vault_db_file() == (
        runtime_root / "var" / "cache" / "ankey_vault.sqlite3"
    ).resolve()
    assert paths.resolve_identity_db_file() == (
        runtime_root / "var" / "cache" / "identity.sqlite3"
    ).resolve()
