from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import yaml


TEST_RUNTIME_ROOT_ENV = "ANKEY_TEST_RUNTIME_ROOT"
TRACKED_EMPLOYEES_SOURCE_FILENAME = "source_employees_example_1.csv"
_CANONICAL_REGISTRY_FILENAME = "registry.yaml"


def repo_root() -> Path:
    """Return repository root for runtime-oriented tests."""
    return Path(__file__).resolve().parents[1]


def tracked_employees_runtime_roots() -> dict[str, Path]:
    """Return the active isolated runtime roots used by tests."""
    runtime_root = _active_test_runtime_root()
    datasets_root = runtime_root / "datasets"
    return {
        "runtime_root": runtime_root,
        "registry_path": datasets_root / _CANONICAL_REGISTRY_FILENAME,
        "datasets_root": datasets_root,
        "dictionary_specs_root": datasets_root,
        "dictionary_data_root": runtime_root / "dictionaries",
        "source_projection_root": datasets_root,
        "target_projection_root": datasets_root,
        "source_data_root": runtime_root / "sources",
    }


def build_isolated_test_runtime_root(runtime_root: Path) -> dict[str, Path]:
    """Build an isolated runtime layout for tests from the canonical repo registry."""
    runtime_root = runtime_root.resolve()
    datasets_root = runtime_root / "datasets"
    dictionary_data_root = runtime_root / "dictionaries"
    source_data_root = runtime_root / "sources"

    datasets_root.mkdir(parents=True, exist_ok=True)
    dictionary_data_root.mkdir(parents=True, exist_ok=True)
    source_data_root.mkdir(parents=True, exist_ok=True)

    repo_datasets_root = repo_root() / "datasets"
    repo_dictionary_data_root = repo_root() / "dictionaries"
    repo_source_data_root = repo_root() / "examples" / "sources"

    registry_payload = _normalized_registry_payload(repo_datasets_root)
    _copy_registry_artifacts(
        registry_payload=registry_payload,
        repo_datasets_root=repo_datasets_root,
        repo_dictionary_data_root=repo_dictionary_data_root,
        repo_source_data_root=repo_source_data_root,
        datasets_root=datasets_root,
        dictionary_data_root=dictionary_data_root,
        source_data_root=source_data_root,
    )

    registry_path = datasets_root / _CANONICAL_REGISTRY_FILENAME
    registry_path.write_text(
        yaml.safe_dump(registry_payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    _patch_employees_source_alias(datasets_root / "employees" / "source" / "source.yaml")

    return {
        "runtime_root": runtime_root,
        "registry_path": registry_path,
        "datasets_root": datasets_root,
        "dictionary_specs_root": datasets_root,
        "dictionary_data_root": dictionary_data_root,
        "source_projection_root": datasets_root,
        "target_projection_root": datasets_root,
        "source_data_root": source_data_root,
    }


def prepare_tracked_employees_source_file(source_path: Path) -> Path:
    """Copy a generated CSV into the runtime filename expected by the test source spec."""
    runtime_path = source_path.parent / TRACKED_EMPLOYEES_SOURCE_FILENAME
    if source_path.resolve() != runtime_path.resolve():
        shutil.copy2(source_path, runtime_path)
    return runtime_path


def write_runtime_config(
    tmp_path: Path,
    *,
    registry_path: Path | None = None,
    datasets_root: Path | None = None,
    source_data_root: Path | None = None,
    source_projection_root: Path | None = None,
    target_projection_root: Path | None = None,
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
    if datasets_root is not None:
        runtime_payload["datasets_root"] = str(datasets_root)
    if source_data_root is not None:
        runtime_payload["source_data_root"] = str(source_data_root)
    if source_projection_root is not None:
        runtime_payload["source_projection_root"] = str(source_projection_root)
    if target_projection_root is not None:
        runtime_payload["target_projection_root"] = str(target_projection_root)
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


def _active_test_runtime_root() -> Path:
    runtime_root = os.environ.get(TEST_RUNTIME_ROOT_ENV)
    if runtime_root:
        return Path(runtime_root).resolve()
    return repo_root().resolve()


def _normalized_registry_payload(repo_datasets_root: Path) -> dict[str, Any]:
    payload = yaml.safe_load((repo_datasets_root / _CANONICAL_REGISTRY_FILENAME).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("tests registry payload must be a mapping")

    targets = payload.get("targets") or {}
    for target_name, ref in list(targets.items()):
        if isinstance(ref, str):
            targets[target_name] = _normalize_dataset_ref(repo_datasets_root, ref)

    datasets = payload.get("datasets") or {}
    for entry in datasets.values():
        if not isinstance(entry, dict):
            continue
        for key, ref in list(entry.items()):
            if isinstance(ref, str):
                normalized = _maybe_normalize_dataset_ref(repo_datasets_root, ref)
                if normalized is not None:
                    entry[key] = normalized

    cache = payload.get("cache") or {}
    for entry in (cache.get("datasets") or {}).values():
        if not isinstance(entry, dict):
            continue
        ref = entry.get("cache_spec")
        if isinstance(ref, str):
            entry["cache_spec"] = _normalize_dataset_ref(repo_datasets_root, ref)

    dictionaries = payload.get("dictionaries") or {}
    manifest_ref = dictionaries.get("manifest")
    if isinstance(manifest_ref, str):
        dictionaries["manifest"] = _normalize_dataset_ref(repo_datasets_root, manifest_ref)
    for entry in (dictionaries.get("items") or {}).values():
        if not isinstance(entry, dict):
            continue
        ref = entry.get("spec")
        if isinstance(ref, str):
            entry["spec"] = _normalize_dataset_ref(repo_datasets_root, ref)

    return payload


def _copy_registry_artifacts(
    *,
    registry_payload: dict[str, Any],
    repo_datasets_root: Path,
    repo_dictionary_data_root: Path,
    repo_source_data_root: Path,
    datasets_root: Path,
    dictionary_data_root: Path,
    source_data_root: Path,
) -> None:
    dataset_refs: set[str] = set()

    targets = registry_payload.get("targets") or {}
    dataset_refs.update(ref for ref in targets.values() if isinstance(ref, str))

    datasets = registry_payload.get("datasets") or {}
    for entry in datasets.values():
        if not isinstance(entry, dict):
            continue
        dataset_refs.update(ref for ref in entry.values() if isinstance(ref, str))

    cache = registry_payload.get("cache") or {}
    for entry in (cache.get("datasets") or {}).values():
        if not isinstance(entry, dict):
            continue
        ref = entry.get("cache_spec")
        if isinstance(ref, str):
            dataset_refs.add(ref)

    dictionaries = registry_payload.get("dictionaries") or {}
    manifest_ref = dictionaries.get("manifest")
    if isinstance(manifest_ref, str):
        dataset_refs.add(manifest_ref)
    for entry in (dictionaries.get("items") or {}).values():
        if not isinstance(entry, dict):
            continue
        ref = entry.get("spec")
        if isinstance(ref, str):
            dataset_refs.add(ref)

    for ref in sorted(dataset_refs):
        src = repo_datasets_root / ref
        if not src.exists():
            continue
        dst = datasets_root / ref
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    manifest_payload = yaml.safe_load((datasets_root / str(manifest_ref)).read_text(encoding="utf-8")) if isinstance(manifest_ref, str) else {}
    manifest_items = (manifest_payload or {}).get("items") or {}
    for item in manifest_items.values():
        if not isinstance(item, dict):
            continue
        csv_path = item.get("csv_path")
        if not isinstance(csv_path, str):
            continue
        src = repo_dictionary_data_root / csv_path
        if src.exists():
            shutil.copy2(src, dictionary_data_root / csv_path)

    for src in repo_source_data_root.glob("*.csv"):
        shutil.copy2(src, source_data_root / src.name)

    source_alias_src = source_data_root / "source_employees.csv"
    if source_alias_src.exists():
        shutil.copy2(source_alias_src, source_data_root / TRACKED_EMPLOYEES_SOURCE_FILENAME)


def _patch_employees_source_alias(source_spec_path: Path) -> None:
    if not source_spec_path.exists():
        return
    payload = yaml.safe_load(source_spec_path.read_text(encoding="utf-8")) or {}
    source_section = payload.get("source")
    if not isinstance(source_section, dict):
        return
    source_section["location"] = TRACKED_EMPLOYEES_SOURCE_FILENAME
    source_spec_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _normalize_dataset_ref(repo_datasets_root: Path, ref: str) -> str:
    source_path = _locate_dataset_artifact(repo_datasets_root, ref)
    return source_path.relative_to(repo_datasets_root).as_posix()


def _maybe_normalize_dataset_ref(repo_datasets_root: Path, ref: str) -> str | None:
    try:
        return _normalize_dataset_ref(repo_datasets_root, ref)
    except FileNotFoundError:
        return None


def _locate_dataset_artifact(repo_datasets_root: Path, ref: str) -> Path:
    direct = repo_datasets_root / ref
    if direct.exists():
        return direct

    name = Path(ref).name
    matches = sorted(repo_datasets_root.rglob(name))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(f"dataset artifact not found: {ref}")
    raise FileNotFoundError(f"dataset artifact is ambiguous: {ref}")
