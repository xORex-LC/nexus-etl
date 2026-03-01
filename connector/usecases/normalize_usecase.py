from __future__ import annotations

import logging

from connector.domain.transform.core.extractor import Extractor
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.models import DiagnosticStage
from connector.domain.reporting.adapters.result_policy import StageCommandResultResolver
from connector.domain.reporting.adapters.stage_result_reporter import StageResultReporter
from connector.domain.reporting.adapters.strategies import TransformStageReportStrategy
from connector.domain.transform.stages.stages import PipelineOrchestrator


class NormalizeUseCase:
    """
    Назначение/ответственность:
        Use-case для отчета по нормализации (normalize + map) без записи в vault.
    """

    def __init__(
        self,
        report_items_limit: int,
        include_normalized_items: bool,
    ) -> None:
        self.report_items_limit = report_items_limit
        self.include_normalized_items = include_normalized_items

    def run(
        self,
        row_source,
        pipeline: PipelineOrchestrator,
        dataset: str,
        logger: logging.Logger,
        run_id: str,
        report,
        catalog: ErrorCatalog,
    ) -> CommandResult:
        reporter = StageResultReporter(
            report=report,
            include_items=self.include_normalized_items,
            context_key="normalize",
            ok_label="normalized_ok",
            failed_label="normalize_failed",
            strategy=TransformStageReportStrategy(),
            report_stage=DiagnosticStage.NORMALIZE,
            include_upstream_diagnostics=False,
        )

        extractor = Extractor(row_source, catalog=catalog)
        for map_result in pipeline.run(extractor.run()):
            reporter.process(map_result)

        stats = reporter.publish_context()
        return StageCommandResultResolver().resolve(stats)
