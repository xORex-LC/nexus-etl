"""
Назначение:
    MapperEngine: DSL-обвязка для маппинга (StageEngine).
"""

from __future__ import annotations

from typing import Mapping

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.transform.sources import SourceMapper
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.dsl.engine import TransformationEngine
from connector.domain.transform.dsl.loader import load_mapping_spec_for_dataset, load_sink_spec_for_dataset
from connector.domain.transform.dsl.specs import MappingSpec, SinkSpec
from connector.domain.transform.mapping.mapper_core import MapperCore
from connector.domain.transform.mapping.mapper_dsl import MapperDsl


class MapperEngine(SourceMapper[Mapping[str, object]]):
    """
    Назначение/ответственность:
        DSL-движок стадии map: загружает правила и применяет MapperCore.
    """

    def __init__(
        self,
        spec: MappingSpec,
        *,
        catalog: ErrorCatalog,
        dsl: MapperDsl | None = None,
        sink_spec: SinkSpec | None = None,
    ) -> None:
        self.catalog = catalog
        self.dsl = dsl or MapperDsl()
        self.core = self.dsl.compile(spec, sink_spec=sink_spec)

    @classmethod
    def from_dataset(
        cls,
        *,
        dataset: str,
        catalog: ErrorCatalog,
        engine: TransformationEngine | None = None,
    ) -> "MapperEngine":
        spec = load_mapping_spec_for_dataset(dataset)
        sink_spec = load_sink_spec_for_dataset(dataset)
        dsl = MapperDsl(engine=engine)
        return cls(spec, catalog=catalog, dsl=dsl, sink_spec=sink_spec)

    def map(self, record: SourceRecord) -> TransformResult[Mapping[str, object]]:
        return self.core.map_record(record, catalog=self.catalog)
