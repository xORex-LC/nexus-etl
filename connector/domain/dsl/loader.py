"""
Назначение:
    Загрузка DSL-спецификаций из YAML.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

import yaml
import os

from connector.domain.dsl.build_options import (
    BaseDslBuildOptions,
    CacheDslBuildOptions,
    EnrichDslBuildOptions,
    MapDslBuildOptions,
    MatchDslBuildOptions,
    NormalizeDslBuildOptions,
    ResolveDslBuildOptions,
    build_options_from_mapping,
)
from connector.domain.dsl.specs import (
    MappingSpec,
    SourceSpec,
    NormalizeSpec,
    EnrichSpec,
    ValidationSpec,
    MatchSpec,
    ResolveSpec,
    SinkSpec,
    CacheRegistrySpec,
    CacheDatasetSpec,
)
from connector.domain.dsl.issues import DslLoadError

TSpec = TypeVar("TSpec")


def load_mapping_spec(path: str | Path) -> MappingSpec:
    """
    Назначение:
        Прочитать YAML и сформировать MappingSpec.
    """
    return _load_spec_from_path(path, MappingSpec, code="MAP_DSL_SPEC_INVALID")


def load_mapping_spec_for_dataset(dataset: str) -> MappingSpec:
    """
    Назначение:
        Загрузить mapping DSL по имени датасета из datasets/registry.yml.
    """
    return _load_dataset_stage_spec(
        dataset=dataset,
        stage="mapping",
        spec_cls=MappingSpec,
        code="MAP_DSL_SPEC_INVALID",
    )


def load_source_spec_for_dataset(dataset: str) -> SourceSpec:
    """
    Назначение:
        Загрузить source DSL по имени датасета из datasets/registry.yml.
    """
    return _load_dataset_stage_spec(
        dataset=dataset,
        stage="source",
        spec_cls=SourceSpec,
        code="SOURCE_DSL_SPEC_INVALID",
    )


def resolve_source_location(spec: SourceSpec) -> str:
    """
    Назначение:
        Разрешить путь/локацию источника из source-spec.

    Алгоритм:
        - Если задан `location_ref`, берём значение из env.
        - Если env-переменная пуста, fallback на `location`.
        - Если итоговое значение пустое, бросаем DslLoadError.
    """
    ref = spec.source.location_ref
    if ref:
        ref_value = os.getenv(ref)
        if ref_value and ref_value.strip():
            return ref_value.strip()
    location = spec.source.location
    if location and location.strip():
        return location.strip()
    raise DslLoadError(
        code="SOURCE_DSL_LOCATION_INVALID",
        message="source location is not configured (location_ref/location)",
        details={"dataset": spec.dataset},
    )


def load_normalize_spec_for_dataset(dataset: str) -> NormalizeSpec:
    """
    Назначение:
        Загрузить normalize DSL по имени датасета из datasets/registry.yml.
    """
    return _load_dataset_stage_spec(
        dataset=dataset,
        stage="normalize",
        spec_cls=NormalizeSpec,
        code="NORMALIZE_DSL_SPEC_INVALID",
    )


def load_enrich_spec_for_dataset(dataset: str) -> EnrichSpec:
    """
    Назначение:
        Загрузить enrich DSL по имени датасета из datasets/registry.yml.
    """
    return _load_dataset_stage_spec(
        dataset=dataset,
        stage="enrich",
        spec_cls=EnrichSpec,
        code="ENRICH_DSL_SPEC_INVALID",
        post_load=_expand_enrich_templates,
    )


def load_validate_spec_for_dataset(dataset: str) -> ValidationSpec:
    """
    Назначение:
        Загрузить validate DSL по имени датасета из datasets/registry.yml.
    """
    return _load_dataset_stage_spec(
        dataset=dataset,
        stage="validate",
        spec_cls=ValidationSpec,
        code="VALIDATE_DSL_SPEC_INVALID",
    )


def load_match_spec_for_dataset(dataset: str) -> MatchSpec:
    """
    Назначение:
        Загрузить match DSL по имени датасета из datasets/registry.yml.
    """
    return _load_dataset_stage_spec(
        dataset=dataset,
        stage="match",
        spec_cls=MatchSpec,
        code="MATCH_DSL_SPEC_INVALID",
    )


def load_resolve_spec_for_dataset(dataset: str) -> ResolveSpec:
    """
    Назначение:
        Загрузить resolve DSL по имени датасета из datasets/registry.yml.
    """
    return _load_dataset_stage_spec(
        dataset=dataset,
        stage="resolve",
        spec_cls=ResolveSpec,
        code="RESOLVE_DSL_SPEC_INVALID",
    )


def load_sink_spec_for_dataset(dataset: str) -> SinkSpec:
    """
    Назначение:
        Загрузить sink-модель по имени датасета из datasets/registry.yml.
    """
    return _load_dataset_stage_spec(
        dataset=dataset,
        stage="sink",
        spec_cls=SinkSpec,
        code="SINK_DSL_SPEC_INVALID",
    )


def load_cache_registry_spec(path: str | Path | None = None) -> CacheRegistrySpec:
    """
    Назначение:
        Загрузить cache registry spec (из отдельного файла или datasets/registry.yml).
    """
    try:
        raw = _read_yaml(path) if path is not None else _load_registry()
    except Exception as exc:
        raise DslLoadError(
            code="CACHE_DSL_REGISTRY_INVALID",
            message=f"Failed to read cache registry: {exc}",
            details={"path": str(path) if path is not None else "datasets/registry.yml"},
        ) from exc

    cache_payload = _extract_cache_registry_payload(raw)
    try:
        return CacheRegistrySpec.model_validate(cache_payload)
    except Exception as exc:
        raise DslLoadError(
            code="CACHE_DSL_REGISTRY_INVALID",
            message=f"Invalid cache registry DSL: {exc}",
            details={"path": str(path) if path is not None else "datasets/registry.yml"},
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
    spec_path = _repo_root() / "datasets" / dataset_entry.cache_spec
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


def load_map_build_options_for_dataset(dataset: str) -> MapDslBuildOptions:
    return _load_stage_build_options(dataset, "mapping", MapDslBuildOptions)


def load_normalize_build_options_for_dataset(dataset: str) -> NormalizeDslBuildOptions:
    return _load_stage_build_options(dataset, "normalize", NormalizeDslBuildOptions)


def load_enrich_build_options_for_dataset(dataset: str) -> EnrichDslBuildOptions:
    return _load_stage_build_options(dataset, "enrich", EnrichDslBuildOptions)


def load_match_build_options_for_dataset(dataset: str) -> MatchDslBuildOptions:
    return _load_stage_build_options(dataset, "match", MatchDslBuildOptions)


def load_resolve_build_options_for_dataset(dataset: str) -> ResolveDslBuildOptions:
    return _load_stage_build_options(dataset, "resolve", ResolveDslBuildOptions)


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
        - Если dataset_overrides не передан, используются cache.datasets.*.build_options.cache (если есть).
    """
    registry = _load_registry()
    root_build_options = registry.get("build_options") or {}
    global_base = root_build_options.get("base") or {}
    global_stage = (root_build_options.get("stages") or {}).get("cache") or {}
    merged: dict[str, Any] = {}
    merged.update(global_base)
    merged.update(global_stage)
    if dataset_overrides is None:
        cache_payload = registry.get("cache") or {}
        cache_datasets = cache_payload.get("datasets") or {}
        dataset_overrides = {}
        for dataset_name, entry in cache_datasets.items():
            if not isinstance(entry, dict):
                continue
            stage_override = ((entry.get("build_options") or {}).get("cache") or {})
            if stage_override:
                dataset_overrides[dataset_name] = stage_override
    if dataset_overrides:
        for dataset_name in sorted(dataset_overrides.keys()):
            merged.update(dataset_overrides[dataset_name] or {})
    if cli_overrides:
        merged.update(cli_overrides)
    return build_options_from_mapping(CacheDslBuildOptions, merged)


def _read_yaml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("DSL YAML must be a mapping")
    return data


def _expand_enrich_templates(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Назначение:
        Развернуть lookup-templates/presets в enrich-правила.
    """

    enrich = raw.get("enrich") or {}
    templates = enrich.get("lookup_templates") or enrich.get("lookup_presets") or {}
    if isinstance(templates, list):
        templates = {item.get("name"): item for item in templates if isinstance(item, dict) and item.get("name")}

    lookup_rules = enrich.get("lookup") or []
    expanded: list[dict[str, Any]] = []
    for rule in lookup_rules:
        if not isinstance(rule, dict):
            expanded.append(rule)
            continue
        template_name = rule.pop("template", None) or rule.pop("preset", None)
        if template_name:
            template = templates.get(template_name)
            if not template:
                raise DslLoadError(
                    code="ENRICH_DSL_TEMPLATE_INVALID",
                    message=f"Unknown lookup template: {template_name}",
                    details={"template": template_name},
                )
            merged = {**template, **rule}
            if "name" not in merged:
                merged["name"] = rule.get("name") or template_name
            expanded.append(merged)
        else:
            expanded.append(rule)

    enrich["lookup"] = expanded
    enrich.pop("lookup_templates", None)
    enrich.pop("lookup_presets", None)
    raw["enrich"] = enrich
    return raw


def _load_registry() -> dict[str, Any]:
    return _load_registry_or_raise()


def _resolve_registry_path(registry: dict[str, Any], dataset: str, stage: str) -> Path:
    datasets = registry.get("datasets") or {}
    if dataset not in datasets:
        raise DslLoadError(
            code="DSL_REGISTRY_INVALID",
            message=f"Dataset '{dataset}' not found in registry.yml",
            details={"dataset": dataset, "stage": stage},
        )
    entry = datasets[dataset] or {}
    filename = entry.get(stage)
    if not filename:
        raise DslLoadError(
            code="DSL_REGISTRY_INVALID",
            message=f"Dataset '{dataset}' does not define '{stage}' in registry.yml",
            details={"dataset": dataset, "stage": stage},
        )
    return _repo_root() / "datasets" / filename


def _repo_root() -> Path:
    # loader.py moved from domain/transform/dsl to domain/dsl.
    # parents[3] points to repository root: <repo>/connector/domain/dsl/loader.py
    return Path(__file__).resolve().parents[3]


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


def _load_stage_build_options(
    dataset: str,
    stage: str,
    options_cls: type[BaseDslBuildOptions],
):
    """
    Назначение:
        Загрузить compile-policy build options с merge-приоритетом:
        defaults -> global.base/global.stages[stage] -> datasets[dataset].build_options[stage]
    """
    registry = _load_registry_or_raise()
    root_build_options = registry.get("build_options") or {}
    datasets = registry.get("datasets") or {}
    if dataset not in datasets:
        raise DslLoadError(
            code="DSL_REGISTRY_INVALID",
            message=f"Dataset '{dataset}' not found in registry.yml (loading build_options for '{stage}')",
            details={"dataset": dataset, "stage": stage},
        )
    dataset_entry = datasets.get(dataset) or {}
    dataset_build_options = dataset_entry.get("build_options") or {}

    global_base = root_build_options.get("base") or {}
    global_stage = (root_build_options.get("stages") or {}).get(stage) or {}
    dataset_stage = dataset_build_options.get(stage) or {}

    merged: dict[str, Any] = {}
    merged.update(global_base)
    merged.update(global_stage)
    merged.update(dataset_stage)
    return build_options_from_mapping(options_cls, merged)


def _load_registry_or_raise() -> dict[str, Any]:
    registry_path = _repo_root() / "datasets" / "registry.yml"
    try:
        return _read_yaml(registry_path)
    except Exception as exc:
        raise DslLoadError(
            code="DSL_REGISTRY_INVALID",
            message=f"Failed to read registry.yml: {exc}",
            details={"path": str(registry_path)},
        ) from exc


def _load_dataset_stage_spec(
    *,
    dataset: str,
    stage: str,
    spec_cls: type[TSpec],
    code: str,
    post_load=None,
) -> TSpec:
    registry = _load_registry_or_raise()
    stage_path = _resolve_registry_path(registry, dataset, stage)
    raw = _read_yaml_or_raise(stage_path, code=code, dataset=dataset, stage=stage)
    if post_load is not None:
        try:
            raw = post_load(raw)
        except DslLoadError:
            raise
        except Exception as exc:
            raise DslLoadError(
                code=code,
                message=f"Failed to preprocess DSL stage '{stage}': {exc}",
                details={"dataset": dataset, "stage": stage, "path": str(stage_path)},
            ) from exc
    return _validate_spec_or_raise(
        raw,
        spec_cls,
        code=code,
        details={"dataset": dataset, "stage": stage, "path": str(stage_path)},
    )


def _load_spec_from_path(path: str | Path, spec_cls: type[TSpec], *, code: str) -> TSpec:
    path_obj = Path(path)
    raw = _read_yaml_or_raise(path_obj, code=code)
    return _validate_spec_or_raise(raw, spec_cls, code=code, details={"path": str(path_obj)})


def _read_yaml_or_raise(
    path: str | Path,
    *,
    code: str,
    dataset: str | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    try:
        return _read_yaml(path)
    except Exception as exc:
        details: dict[str, Any] = {"path": str(path)}
        if dataset is not None:
            details["dataset"] = dataset
        if stage is not None:
            details["stage"] = stage
        raise DslLoadError(
            code=code,
            message=f"Failed to read DSL file: {exc}",
            details=details,
        ) from exc


def _validate_spec_or_raise(
    raw: dict[str, Any],
    spec_cls: type[TSpec],
    *,
    code: str,
    details: dict[str, Any] | None = None,
) -> TSpec:
    try:
        return spec_cls.model_validate(raw)
    except Exception as exc:
        raise DslLoadError(
            code=code,
            message=f"Invalid DSL spec: {exc}",
            details=details or {},
        ) from exc
