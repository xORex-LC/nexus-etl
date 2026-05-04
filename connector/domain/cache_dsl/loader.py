"""
Назначение:
    Загрузка Cache DSL-спецификаций и build options.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from connector.domain.dsl.build_options import build_options_from_mapping
from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.loader._common import _datasets_root, _load_registry_or_raise, _read_yaml, _registry_path
from connector.domain.cache_dsl.build_options import CacheDslBuildOptions
from connector.domain.cache_dsl.specs import CacheDatasetSpec, CacheRegistrySpec


# ========== SPEC LOADERS ==========


def load_cache_registry_spec(path: str | Path | None = None) -> CacheRegistrySpec:
    """
    Назначение:
        Загрузить cache registry spec (из отдельного файла или datasets/registry.yml).
    """
    try:
        raw = _read_yaml(path) if path is not None else _load_registry_or_raise()
    except Exception as exc:
        raise DslLoadError(
            code="CACHE_DSL_REGISTRY_INVALID",
            message=f"Failed to read cache registry: {exc}",
            details={"path": str(path) if path is not None else str(_registry_path())},
        ) from exc

    cache_payload = _extract_cache_registry_payload(raw)
    try:
        return CacheRegistrySpec.model_validate(cache_payload)
    except Exception as exc:
        raise DslLoadError(
            code="CACHE_DSL_REGISTRY_INVALID",
            message=f"Invalid cache registry DSL: {exc}",
            details={"path": str(path) if path is not None else str(_registry_path())},
        ) from exc


def load_cache_registry_spec_for_runtime() -> CacheRegistrySpec:
    """
    Назначение:
        Runtime helper для загрузки cache registry из datasets/registry.yml.
    """
    return load_cache_registry_spec(None)


def load_cache_dataset_spec(path: str | Path) -> CacheDatasetSpec:
    """
    Назначение:
        Прочитать YAML и сформировать CacheDatasetSpec.
    """
    try:
        raw = _read_yaml(path)
    except Exception as exc:
        raise DslLoadError(
            code="CACHE_DSL_SPEC_INVALID",
            message=f"Failed to read cache dataset spec: {exc}",
            details={"path": str(path)},
        ) from exc
    try:
        return CacheDatasetSpec.model_validate(raw)
    except Exception as exc:
        raise DslLoadError(
            code="CACHE_DSL_SPEC_INVALID",
            message=f"Invalid cache dataset DSL: {exc}",
            details={"path": str(path)},
        ) from exc


def load_cache_dataset_spec_for_dataset(dataset: str) -> CacheDatasetSpec:
    """
    Назначение:
        Загрузить cache dataset spec по имени датасета из cache registry.
    """
    registry = load_cache_registry_spec_for_runtime()
    dataset_entry = registry.datasets.get(dataset)
    if dataset_entry is None:
        raise DslLoadError(
            code="CACHE_DSL_DEP_MISSING",
            message=f"Dataset '{dataset}' is not present in cache registry",
            details={"dataset": dataset},
        )
    spec_path = _datasets_root() / dataset_entry.cache_spec
    spec = load_cache_dataset_spec(spec_path)
    if spec.dataset != dataset:
        raise DslLoadError(
            code="CACHE_DSL_SPEC_INVALID",
            message=(
                f"Cache dataset spec mismatch: registry key '{dataset}' "
                f"!= spec.dataset '{spec.dataset}'"
            ),
            details={"dataset": dataset, "path": str(spec_path)},
        )
    return spec


# ========== BUILD OPTIONS LOADERS ==========


def load_cache_build_options_for_runtime(
    *,
    dataset_overrides: dict[str, dict[str, Any]] | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> CacheDslBuildOptions:
    """
    Назначение:
        Загрузить compile-policy build options для cache runtime.

    Контракт:
        - merge-приоритет:
          defaults -> global.base -> global.stages.cache -> dataset overrides (optional) -> CLI overrides.
        - dataset_overrides может быть передан явно из orchestration слоя.
        - Если dataset_overrides не передан:
          - 0 dataset overrides -> применяются только global/CLI;
          - 1 dataset override -> применяется автоматически;
          - >1 dataset overrides -> бросается CACHE_DSL_BUILD_OPTIONS_AMBIGUOUS.
    """
    registry = _load_registry_or_raise()
    root_build_options = registry.get("build_options") or {}
    global_base = root_build_options.get("base") or {}
    global_stage = (root_build_options.get("stages") or {}).get("cache") or {}
    merged: dict[str, Any] = {}
    merged.update(global_base)
    merged.update(global_stage)
    if dataset_overrides is None:
        cache_payload = registry.get("cache") or {}
        cache_datasets = cache_payload.get("datasets") or {}
        discovered_overrides: dict[str, dict[str, Any]] = {}
        for dataset_name, entry in cache_datasets.items():
            if not isinstance(entry, dict):
                continue
            stage_override = ((entry.get("build_options") or {}).get("cache") or {})
            if stage_override:
                discovered_overrides[dataset_name] = stage_override
        if len(discovered_overrides) == 1:
            dataset_overrides = dict(discovered_overrides)
        elif len(discovered_overrides) > 1:
            raise DslLoadError(
                code="CACHE_DSL_BUILD_OPTIONS_AMBIGUOUS",
                message=(
                    "Ambiguous cache build_options for runtime: multiple dataset overrides found; "
                    "provide dataset_overrides explicitly from orchestration layer"
                ),
                details={"datasets": sorted(discovered_overrides.keys())},
            )
        else:
            dataset_overrides = {}
    if dataset_overrides:
        for dataset_name in sorted(dataset_overrides.keys()):
            merged.update(dataset_overrides[dataset_name] or {})
    if cli_overrides:
        merged.update(cli_overrides)
    strict_mode = bool(merged.get("strict", False))
    return build_options_from_mapping(CacheDslBuildOptions, merged, strict=strict_mode)


# ========== PRIVATE HELPERS ==========


def _extract_cache_registry_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Назначение:
        Выделить payload cache registry из общего registry.yml.
    """
    if "cache" in raw and isinstance(raw.get("cache"), dict):
        return raw["cache"]
    # fallback: допускаем отдельный cache-registry файл без верхнего ключа "cache"
    if {"version", "datasets"} <= set(raw.keys()):
        return raw
    raise DslLoadError(
        code="CACHE_DSL_REGISTRY_INVALID",
        message="cache section is missing in registry file",
    )
