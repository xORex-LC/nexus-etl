from __future__ import annotations

from pathlib import Path

import pytest

from connector.common.runtime_paths import (
    RUNTIME_ROOT_ENV_VAR,
    RuntimeLayoutError,
    detect_runtime_paths,
    resolve_registry_path_for_datasets_root,
)


def _write(path: Path, content: str = "datasets: {}\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_detect_runtime_paths_prefers_env_override(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _write(runtime_root / "datasets" / "registry.yaml")

    paths = detect_runtime_paths(
        env={RUNTIME_ROOT_ENV_VAR: str(runtime_root)},
        argv0="/ignored/bin/nexus",
        module_file=tmp_path / "src" / "module.py",
    )

    assert paths.root == runtime_root.resolve()
    assert paths.datasets_root == (runtime_root / "datasets").resolve()
    assert paths.default_registry_path == (runtime_root / "datasets" / "registry.yaml").resolve()


def test_detect_runtime_paths_uses_standalone_layout_near_argv0(tmp_path: Path) -> None:
    dist_root = tmp_path / "nexus.dist"
    _write(dist_root / "datasets" / "registry.yaml")

    paths = detect_runtime_paths(
        env={},
        argv0=dist_root / "nexus",
        module_file=tmp_path / "elsewhere" / "module.py",
    )

    assert paths.root == dist_root.resolve()
    assert paths.examples_root == (dist_root / "examples").resolve()
    assert paths.cache_root == (dist_root / "var" / "cache").resolve()


def test_detect_runtime_paths_uses_module_parent_search_for_dev_checkout(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    module_file = repo_root / "connector" / "common" / "runtime_paths.py"
    _write(repo_root / "datasets" / "registry.yaml")

    paths = detect_runtime_paths(
        env={},
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
        env={},
        argv0="/outside/bin/nexus",
        module_file=module_file,
    )

    assert paths.default_registry_path == (repo_root / "datasets" / "registry.yml").resolve()


def test_detect_runtime_paths_raises_when_layout_is_missing(tmp_path: Path) -> None:
    with pytest.raises(RuntimeLayoutError):
        detect_runtime_paths(
            env={},
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
