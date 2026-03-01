from __future__ import annotations

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.models import DiagnosticStage
from connector.domain.reporting.adapters.result_policy import StageCommandResultResolver
from connector.domain.reporting.adapters.stage_result_reporter import StageResultReporter
from connector.domain.reporting.adapters.strategies import PlanningStageReportStrategy
from connector.domain.transform.core.extractor import Extractor
from connector.domain.transform.core.iterators import iter_ok
from connector.domain.transform.stages.stages import PipelineOrchestrator


class MatchUseCase:
    """
    Назначение/ответственность:
        Use-case для сопоставления строк (map → normalize → enrich → match).

    Граница ответственности:
        - Owns: сборка Extractor из row_source, report aggregation.
        - Micro-batching делегирован MatchStage (IMatchBatchSettings).
        - iter_ok фильтрует error records из upstream стадий перед aggregation.
        - Does NOT: управлять lifecycle dedup-state или scope cleanup —
          это ответственность PipelineHooks через on_stage_complete("match").
    """

    def __init__(
        self,
        report_items_limit: int,
        include_matched_items: bool,
    ) -> None:
        self.report_items_limit = report_items_limit
        self.include_matched_items = include_matched_items

    def run(
        self,
        row_source,
        pipeline: PipelineOrchestrator,
        dataset: str,
        report,
        catalog: ErrorCatalog,
    ) -> CommandResult:
        """
        Назначение:
            Выполнить полный pipeline (map → match) и агрегировать результаты.

        Параметр pipeline:
            PipelineOrchestrator с checkpoint MATCH (MAP→NORMALIZE→ENRICH→MATCH).
            Lifecycle hooks для scope cleanup передаются через pipeline.
            Scope cleanup вызывается автоматически через on_stage_complete("match").

        Фильтрация upstream ошибок:
            iter_ok фильтрует записи с errors из предыдущих стадий.
            MatchStage guard пропускает row=None записи — они попадают в iter_ok
            и отфильтровываются (имеют errors от upstream стадий).
        """
        reporter = StageResultReporter(
            report=report,
            include_items=self.include_matched_items,
            context_key="match",
            ok_label="matched_ok",
            failed_label="match_failed",
            strategy=PlanningStageReportStrategy(
                meta_builder=lambda r: {
                    "match_status": (r.row.match_decision.status.value if r.row else None)
                },
            ),
            report_stage=DiagnosticStage.MATCH,
            include_upstream_diagnostics=False,
        )

        extractor = Extractor(row_source, catalog=catalog)
        for matched in iter_ok(pipeline.run(extractor.run())):
            force_failed = bool((matched.meta or {}).get("match_drop_reason"))
            reporter.process(matched, force_failed=force_failed)

        stats = reporter.publish_context()
        has_conflicts = report.summary.errors_total > 0
        return StageCommandResultResolver().resolve(stats, has_conflicts=has_conflicts)
