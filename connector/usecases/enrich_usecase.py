from __future__ import annotations

import logging

from connector.domain.transform.core.extractor import Extractor
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.models import DiagnosticStage
from connector.domain.reporting.contracts import ReportContextKey
from connector.domain.reporting.adapters.result_policy import StageCommandResultResolver
from connector.domain.reporting.adapters.stage_result_reporter import StageResultReporter
from connector.domain.reporting.adapters.strategies import TransformStageReportStrategy
from connector.domain.reporting.policy import resolve_report_policy
from connector.domain.transform.stages.stages import PipelineOrchestrator


class EnrichUseCase:
    """
    Назначение/ответственность:
        Use-case для отчета по обогащению (normalize + map + enrich) с записью секретов через enricher.
    """

    def __init__(
        self,
        report_items_limit: int,
        include_enriched_items: bool,
    ) -> None:
        self.report_items_limit = report_items_limit
        self.include_enriched_items = include_enriched_items

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
        report_policy = resolve_report_policy(report)
        reporter = StageResultReporter(
            report=report,
            report_policy=report_policy,
            include_items=self.include_enriched_items,
            context_key=ReportContextKey.ENRICH,
            ok_label="enriched_ok",
            failed_label="enrich_failed",
            strategy=TransformStageReportStrategy(),
            report_stage=DiagnosticStage.ENRICH,
            include_upstream_diagnostics=False,
        )

        extractor = Extractor(row_source, catalog=catalog)
        for map_result in pipeline.run(extractor.run()):
            reporter.process(map_result)

        stats = reporter.publish_context()
        return StageCommandResultResolver().resolve(stats)
