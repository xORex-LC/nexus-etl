from __future__ import annotations

import logging

from connector.datasets.registry import get_spec
from connector.domain.transform.core.extractor import Extractor
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.models import DiagnosticStage
from connector.domain.reporting.contracts import ReportContextKey
from connector.domain.reporting.adapters.result_policy import StageCommandResultResolver
from connector.domain.reporting.adapters.stage_result_reporter import StageResultReporter
from connector.domain.reporting.adapters.strategies import TransformStageReportStrategy
from connector.domain.reporting.policy import ReportPolicy
from connector.domain.reporting.sink import IReportSink
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
        report_sink: IReportSink,
        report_policy: ReportPolicy,
        catalog: ErrorCatalog,
    ) -> CommandResult:
        payload_builder = _build_enrich_report_payload_builder(dataset)
        reporter = StageResultReporter(
            sink=report_sink,
            report_policy=report_policy,
            include_items=self.include_enriched_items,
            context_key=ReportContextKey.ENRICH,
            ok_label="enriched_ok",
            failed_label="enrich_failed",
            strategy=TransformStageReportStrategy(payload_builder=payload_builder),
            report_stage=DiagnosticStage.ENRICH,
            include_upstream_diagnostics=False,
        )

        extractor = Extractor(row_source, catalog=catalog)
        for map_result in pipeline.run(extractor.run()):
            reporter.process(map_result)

        stats = reporter.publish_context()
        return StageCommandResultResolver().resolve(stats)


def _build_enrich_report_payload_builder(dataset: str):
    """
    Назначение:
        Собрать sink-aware payload preview для enrich report items.

    Причина:
        Enrich runtime может хранить промежуточные служебные поля в row, но report payload
        должен показывать только то, что реально пройдет в apply payload boundary.
    """
    dataset_spec = get_spec(dataset)
    apply_adapter = dataset_spec.get_apply_adapter()
    raw_builder = getattr(apply_adapter, "payload_builder", None)

    def _payload_builder(result):
        row = result.row
        if row is None or not isinstance(row, dict) or raw_builder is None:
            return row
        preview_builder = getattr(raw_builder, "build_preview", None)
        if callable(preview_builder):
            return preview_builder(dict(row))
        try:
            return raw_builder(dict(row))
        except Exception:  # noqa: BLE001
            return row

    return _payload_builder
