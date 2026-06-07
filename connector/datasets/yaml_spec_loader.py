"""Назначение:
    Eager loading snapshot для YAML-driven DatasetSpec.

Граница ответственности:
    - Owns: разовую загрузку и валидацию dataset-level/runtime DSL артефактов
      для одного датасета.
    - Does NOT: runtime accessor API DatasetSpec, apply/report adapters и
      registry auto-discovery policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from connector.domain.dataset_dsl.loader import load_dataset_dsl_spec
from connector.domain.dataset_dsl.specs import DatasetDslSpec
from connector.domain.dsl.specs._base import DslBaseModel
from connector.domain.transform_dsl import (
    load_enrich_spec_for_dataset,
    load_mapping_spec_for_dataset,
    load_match_spec_for_dataset,
    load_normalize_spec_for_dataset,
    load_resolve_spec_for_dataset,
    load_sink_spec_for_dataset,
    load_source_spec_for_dataset,
    load_topology_spec_for_dataset,
)
from connector.domain.transform_dsl.specs import SinkSpec, SourceSpec, TopologySpec

SUPPORTED_YAML_STAGE_LOADERS = {
    "map": load_mapping_spec_for_dataset,
    "normalize": load_normalize_spec_for_dataset,
    "enrich": load_enrich_spec_for_dataset,
    "match": load_match_spec_for_dataset,
    "resolve": load_resolve_spec_for_dataset,
    "sink": load_sink_spec_for_dataset,
}


@dataclass(frozen=True)
class LoadedYamlDatasetArtifacts:
    """Назначение:
        Immutable snapshot уже загруженных YAML-артефактов датасета.

    Контракт:
        - содержит только валидированные DSL-модели;
        - не выполняет lazy loading;
        - используется как единственный источник runtime access в `YamlDatasetSpec`.
    """

    dataset_name: str
    dataset_dsl: DatasetDslSpec
    source_spec: SourceSpec
    sink_spec: SinkSpec
    topology_spec: TopologySpec | None
    stage_specs: Mapping[str, DslBaseModel]


def load_yaml_dataset_artifacts(dataset_name: str) -> LoadedYamlDatasetArtifacts:
    """Назначение:
        Загрузить полный YAML snapshot датасета для runtime DatasetSpec.

    Контракт:
        - eager loads dataset-level DSL, source, sink и все поддерживаемые
          stage specs;
        - валидирует конфигурацию до выполнения команд;
        - не кеширует результаты глобально.
    """

    dataset_dsl = load_dataset_dsl_spec(dataset_name)
    source_spec = load_source_spec_for_dataset(dataset_name)
    stage_specs = {
        stage_type: loader(dataset_name)
        for stage_type, loader in SUPPORTED_YAML_STAGE_LOADERS.items()
    }
    sink_spec = stage_specs["sink"]
    topology_spec = None
    if dataset_dsl.topology is not None and dataset_dsl.topology.enabled:
        topology_spec = load_topology_spec_for_dataset(dataset_name)
        stage_specs["topology"] = topology_spec
    return LoadedYamlDatasetArtifacts(
        dataset_name=dataset_name,
        dataset_dsl=dataset_dsl,
        source_spec=source_spec,
        sink_spec=sink_spec,
        topology_spec=topology_spec,
        stage_specs=MappingProxyType(dict(stage_specs)),
    )


__all__ = [
    "LoadedYamlDatasetArtifacts",
    "SUPPORTED_YAML_STAGE_LOADERS",
    "load_yaml_dataset_artifacts",
]
