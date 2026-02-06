"""
Назначение:
    Загрузка DSL-спецификаций из YAML.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from connector.domain.transform.dsl.specs import (
    MappingSpec,
    NormalizeSpec,
    EnrichSpec,
    ValidationSpec,
    MatchSpec,
    ResolveSpec,
    SinkSpec,
)


def load_mapping_spec(path: str | Path) -> MappingSpec:
    """
    Назначение:
        Прочитать YAML и сформировать MappingSpec.
    """

    raw = _read_yaml(path)
    return MappingSpec.model_validate(raw)


def load_mapping_spec_for_dataset(dataset: str) -> MappingSpec:
    """
    Назначение:
        Загрузить mapping DSL по имени датасета из datasets/registry.yml.
    """
    registry = _load_registry()
    mapping_path = _resolve_registry_path(registry, dataset, "mapping")
    return load_mapping_spec(mapping_path)


def load_normalize_spec_for_dataset(dataset: str) -> NormalizeSpec:
    """
    Назначение:
        Загрузить normalize DSL по имени датасета из datasets/registry.yml.
    """
    registry = _load_registry()
    normalize_path = _resolve_registry_path(registry, dataset, "normalize")
    raw = _read_yaml(normalize_path)
    return NormalizeSpec.model_validate(raw)


def load_enrich_spec_for_dataset(dataset: str) -> EnrichSpec:
    """
    Назначение:
        Загрузить enrich DSL по имени датасета из datasets/registry.yml.
    """
    registry = _load_registry()
    enrich_path = _resolve_registry_path(registry, dataset, "enrich")
    raw = _read_yaml(enrich_path)
    raw = _expand_enrich_templates(raw)
    return EnrichSpec.model_validate(raw)


def load_validate_spec_for_dataset(dataset: str) -> ValidationSpec:
    """
    Назначение:
        Загрузить validate DSL по имени датасета из datasets/registry.yml.
    """
    registry = _load_registry()
    validate_path = _resolve_registry_path(registry, dataset, "validate")
    raw = _read_yaml(validate_path)
    return ValidationSpec.model_validate(raw)


def load_match_spec_for_dataset(dataset: str) -> MatchSpec:
    """
    Назначение:
        Загрузить match DSL по имени датасета из datasets/registry.yml.
    """
    registry = _load_registry()
    match_path = _resolve_registry_path(registry, dataset, "match")
    raw = _read_yaml(match_path)
    return MatchSpec.model_validate(raw)


def load_resolve_spec_for_dataset(dataset: str) -> ResolveSpec:
    """
    Назначение:
        Загрузить resolve DSL по имени датасета из datasets/registry.yml.
    """
    registry = _load_registry()
    resolve_path = _resolve_registry_path(registry, dataset, "resolve")
    raw = _read_yaml(resolve_path)
    return ResolveSpec.model_validate(raw)


def load_sink_spec_for_dataset(dataset: str) -> SinkSpec:
    """
    Назначение:
        Загрузить sink-модель по имени датасета из datasets/registry.yml.
    """
    registry = _load_registry()
    sink_path = _resolve_registry_path(registry, dataset, "sink")
    raw = _read_yaml(sink_path)
    return SinkSpec.model_validate(raw)


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
                raise ValueError(f"Unknown lookup template: {template_name}")
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
    registry_path = _repo_root() / "datasets" / "registry.yml"
    return _read_yaml(registry_path)


def _resolve_registry_path(registry: dict[str, Any], dataset: str, stage: str) -> Path:
    datasets = registry.get("datasets") or {}
    if dataset not in datasets:
        raise ValueError(f"Dataset '{dataset}' not found in registry.yml")
    entry = datasets[dataset] or {}
    filename = entry.get(stage)
    if not filename:
        raise ValueError(f"Dataset '{dataset}' does not define '{stage}' in registry.yml")
    return _repo_root() / "datasets" / filename


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]
