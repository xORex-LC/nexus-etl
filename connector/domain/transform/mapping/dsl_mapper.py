"""
Назначение:
    Универсальный DSL-маппер: читает YAML-спеку и применяет MapperEngine.
"""

from __future__ import annotations

from typing import Mapping

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.transform.sources import SourceMapper
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.dsl.loader import load_mapping_spec_for_dataset
from connector.domain.transform.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.transform.mapping.engine import MapperEngine


class DslMapper(SourceMapper[Mapping[str, object]]):
    """
    Назначение/ответственность:
        Применяет mapping DSL к SourceRecord.
    """

    def __init__(self, catalog: ErrorCatalog, dataset: str) -> None:
        self.catalog = catalog
        self.spec = load_mapping_spec_for_dataset(dataset)
        registry = OperationRegistry()
        register_core_ops(registry)
        self.engine = MapperEngine(self.spec, registry)

    def map(self, record: SourceRecord) -> TransformResult[Mapping[str, object]]:
        return self.engine.map_record(record, catalog=self.catalog)
