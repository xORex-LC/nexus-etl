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
from connector.domain.dsl.build_options import MapDslBuildOptions
from connector.domain.dsl.engine import TransformationEngine
from connector.domain.dsl.loader import (
    load_map_build_options_for_dataset,
    load_mapping_spec_for_dataset,
    load_sink_spec_for_dataset,
)
from connector.domain.dsl.specs import MappingSpec, SinkSpec
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
        options: MapDslBuildOptions | None = None,
    ) -> None:
        self.catalog = catalog
        self.dsl = dsl or MapperDsl(options=options)
        self.core = self.dsl.compile(spec, sink_spec=sink_spec)

    @classmethod
    def from_dataset(
        cls,
        *,
        dataset: str,
        catalog: ErrorCatalog,
        engine: TransformationEngine | None = None,
        options: MapDslBuildOptions | None = None,
    ) -> "MapperEngine":
        # NOTE: engine/options overrides are test and migration hooks.
        spec = load_mapping_spec_for_dataset(dataset)
        sink_spec = load_sink_spec_for_dataset(dataset)
        dsl_options = options or load_map_build_options_for_dataset(dataset)
        dsl = MapperDsl(engine=engine, options=dsl_options)
        return cls(spec, catalog=catalog, dsl=dsl, sink_spec=sink_spec, options=dsl_options)

    def map(self, record: SourceRecord) -> TransformResult[Mapping[str, object]]:
        return self.core.map_record(record, catalog=self.catalog)
