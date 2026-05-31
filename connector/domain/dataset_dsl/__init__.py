"""
Назначение:
    Dataset DSL — декларативная конфигурация dataset-level метаданных.

Граница ответственности:
    - Owns: Pydantic-модели, загрузчик, компиляторы (payload, params, catalog).
    - Does NOT: YamlDatasetSpec (connector.datasets.yaml_spec), registry (connector.datasets.registry).
"""

from connector.domain.dataset_dsl.loader import load_dataset_dsl_spec
from connector.domain.dataset_dsl.payload_compiler import SinkDrivenPayloadBuilder
from connector.domain.dataset_dsl.specs import DatasetDslSpec, TopologyCapabilitySpec

__all__ = [
    "load_dataset_dsl_spec",
    "DatasetDslSpec",
    "TopologyCapabilitySpec",
    "SinkDrivenPayloadBuilder",
]
