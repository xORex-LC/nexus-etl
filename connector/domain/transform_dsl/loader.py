"""
Назначение:
    Загрузка Transform DSL-спецификаций и build options.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from connector.domain.dsl.build_options import (
    BaseDslBuildOptions,
    build_options_from_mapping,
)
from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.loader._common import (
    _load_registry_or_raise,
    _load_spec_from_path,
    _read_yaml_or_raise,
    _resolve_dataset_stage_path,
    _resolve_source_data_path,
    _resolve_source_projection_path,
    _validate_spec_or_raise,
)
from connector.domain.transform_dsl.build_options import (
    EnrichDslBuildOptions,
    MapDslBuildOptions,
    MatchDslBuildOptions,
    NormalizeDslBuildOptions,
    ResolveDslBuildOptions,
)
from connector.domain.transform_dsl.specs import (
    EnrichSpec,
    MappingSpec,
    MatchSpec,
    NormalizeSpec,
    ResolveSpec,
    SinkSpec,
    SourceSpec,
    ValidationSpec,
)


# ========== SPEC LOADERS ==========


def load_mapping_spec(path: str | Path) -> MappingSpec:
    """
    Назначение:
        Прочитать YAML и сформировать MappingSpec.
    """
    return _load_spec_from_path(path, MappingSpec, code="MAP_DSL_SPEC_INVALID")


def load_mapping_spec_for_dataset(dataset: str) -> MappingSpec:
    """
    Назначение:
        Загрузить mapping DSL по имени датасета из runtime registry file.
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
        Загрузить source DSL по имени датасета из runtime registry file.
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

    Контракт:
        - file-source использует logical/relative ref из `source.location`;
        - relative ref резолвится через runtime `source_data_root`;
        - absolute path допускается как explicit escape hatch;
        - process ENV больше не участвует в runtime path resolution.
    """
    location = spec.source.location
    if location and location.strip():
        if spec.source.type == "file":
            return str(_resolve_source_data_path(location))
        return location.strip()
    raise DslLoadError(
        code="SOURCE_DSL_LOCATION_INVALID",
        message="source location is not configured",
        details={"dataset": spec.dataset},
    )


def load_normalize_spec_for_dataset(dataset: str) -> NormalizeSpec:
    """
    Назначение:
        Загрузить normalize DSL по имени датасета из runtime registry file.
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
        Загрузить enrich DSL по имени датасета из runtime registry file.
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
        Загрузить validate DSL по имени датасета из runtime registry file.
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
        Загрузить match DSL по имени датасета из runtime registry file.
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
        Загрузить resolve DSL по имени датасета из runtime registry file.
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
        Загрузить sink-модель по имени датасета из runtime registry file.
    """
    return _load_dataset_stage_spec(
        dataset=dataset,
        stage="sink",
        spec_cls=SinkSpec,
        code="SINK_DSL_SPEC_INVALID",
    )


# ========== BUILD OPTIONS LOADERS ==========


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


# ========== PRIVATE HELPERS ==========


def _resolve_dataset_path(registry: dict[str, Any], dataset: str, stage: str) -> Path:
    datasets = registry.get("datasets") or {}
    if dataset not in datasets:
        raise DslLoadError(
            code="DSL_REGISTRY_INVALID",
            message=f"Dataset '{dataset}' not found in registry file",
            details={"dataset": dataset, "stage": stage},
        )
    entry = datasets[dataset] or {}
    filename = entry.get(stage)
    if not filename:
        raise DslLoadError(
            code="DSL_REGISTRY_INVALID",
            message=f"Dataset '{dataset}' does not define '{stage}' in registry file",
            details={"dataset": dataset, "stage": stage},
        )
    if stage == "source":
        return _resolve_source_projection_path(filename)
    return _resolve_dataset_stage_path(filename)


def _load_dataset_stage_spec(
    *,
    dataset: str,
    stage: str,
    spec_cls: type,
    code: str,
    post_load=None,
):
    """
    Назначение:
        Загрузить spec для датасета/стадии из registry.
    """
    registry = _load_registry_or_raise()
    stage_path = _resolve_dataset_path(registry, dataset, stage)
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
            message=f"Dataset '{dataset}' not found in registry file (loading build_options for '{stage}')",
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
    strict_mode = bool(merged.get("strict", False))
    return build_options_from_mapping(options_cls, merged, strict=strict_mode)
