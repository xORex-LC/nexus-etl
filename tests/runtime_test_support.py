from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml


TRACKED_EMPLOYEES_SOURCE_FILENAME = "source_employees_example.csv"


def repo_root() -> Path:
    """Return repository root for runtime-oriented tests."""
    return Path(__file__).resolve().parents[1]


def tracked_employees_runtime_roots() -> dict[str, Path]:
    """Return tracked runtime roots for the repository employees dataset."""
    root = repo_root()
    return {
        "registry_path": root / "datasets" / "employees.registry.yaml",
        "dictionary_specs_root": root / "datasets",
        "dictionary_data_root": root / "dictionaries",
        "source_data_root": root / "examples" / "sources",
    }


def prepare_tracked_employees_source_file(source_path: Path) -> Path:
    """Copy a generated CSV into the tracked runtime filename expected by source.yaml."""
    runtime_path = source_path.parent / TRACKED_EMPLOYEES_SOURCE_FILENAME
    if source_path.resolve() != runtime_path.resolve():
        shutil.copy2(source_path, runtime_path)
    return runtime_path


def write_runtime_config(
    tmp_path: Path,
    *,
    registry_path: Path | None = None,
    source_data_root: Path | None = None,
    dictionary_specs_root: Path | None = None,
    dictionary_data_root: Path | None = None,
    cache_dir: Path | None = None,
    log_dir: Path | None = None,
    report_dir: Path | None = None,
) -> Path:
    """Write a minimal config.yaml for runtime path driven CLI tests."""
    payload: dict[str, Any] = {}

    if registry_path is not None:
        payload.setdefault("dataset", {})["registry_path"] = str(registry_path)

    runtime_payload: dict[str, str] = {}
    if source_data_root is not None:
        runtime_payload["source_data_root"] = str(source_data_root)
    if dictionary_specs_root is not None:
        runtime_payload["dictionary_specs_root"] = str(dictionary_specs_root)
    if dictionary_data_root is not None:
        runtime_payload["dictionary_data_root"] = str(dictionary_data_root)
    if runtime_payload:
        payload["runtime"] = runtime_payload

    paths_payload: dict[str, str] = {}
    if cache_dir is not None:
        paths_payload["cache_dir"] = str(cache_dir)
    if log_dir is not None:
        paths_payload["log_dir"] = str(log_dir)
    if report_dir is not None:
        paths_payload["report_dir"] = str(report_dir)
    if paths_payload:
        payload["paths"] = paths_payload

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return config_path
