from __future__ import annotations

import logging

from connector.domain.transform.extractor import Extractor
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.transform.stages import MapStage
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.transform.result_processor import TransformResultProcessor


class MappingUseCase:
    """
    Назначение/ответственность:
        Use-case для отчета по маппингу (без записи в vault).
    """

    def __init__(
        self,
        report_items_limit: int,
        include_mapped_items: bool,
    ) -> None:
        self.report_items_limit = report_items_limit
        self.include_mapped_items = include_mapped_items

    def run(
        self,
        row_source,
        map_stage: MapStage,
        dataset: str,
        logger: logging.Logger,
        run_id: str,
        report,
        catalog: ErrorCatalog,
    ) -> CommandResult:
        report.set_meta(dataset=dataset, items_limit=self.report_items_limit)

        processor = TransformResultProcessor(
            report=report,
            include_items=self.include_mapped_items,
            context_key="mapping",
            ok_label="mapped_ok",
            failed_label="mapping_failed",
        )

        extractor = Extractor(row_source, catalog=catalog)
        for map_result in map_stage.run(extractor.run()):
            processor.process(map_result)

        return processor.finalize()
