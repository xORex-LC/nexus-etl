from __future__ import annotations

from collections import Counter

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.models import DiagnosticStage
from connector.domain.reporting.contracts import ReportContextKey
from connector.domain.reporting.adapters.result_policy import StageCommandResultResolver
from connector.domain.reporting.adapters.stage_result_reporter import StageResultReporter
from connector.domain.reporting.adapters.strategies import PlanningStageReportStrategy
from connector.domain.reporting.events import SetContextEvent
from connector.domain.reporting.policy import ReportPolicy
from connector.domain.reporting.sink import IReportSink
from connector.domain.transform.core.extractor import Extractor
from connector.domain.transform.core.result import TransformResult
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
        report_sink: IReportSink,
        report_policy: ReportPolicy,
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
            sink=report_sink,
            report_policy=report_policy,
            include_items=self.include_matched_items,
            context_key=ReportContextKey.MATCH,
            ok_label="matched_ok",
            failed_label="match_failed",
            strategy=PlanningStageReportStrategy(
                should_skip=_should_skip_match_result,
                meta_builder=lambda r: {
                    "match_status": (r.row.match_decision.status.value if r.row else None),
                    "topology_match_mode": (
                        r.row.match_decision.topology_match_mode.value
                        if r.row and r.row.match_decision.topology_match_mode is not None
                        else None
                    ),
                    "topology_reason": (
                        r.row.match_decision.topology_reason if r.row else None
                    ),
                    "topology_evidence": (
                        dict(r.row.match_decision.topology_evidence) if r.row else {}
                    ),
                },
            ),
            report_stage=DiagnosticStage.MATCH,
            report_stages=(
                DiagnosticStage.MATCH,
                DiagnosticStage.TOPOLOGY_VALIDATE,
            ),
            include_upstream_diagnostics=False,
        )

        extractor = Extractor(row_source, catalog=catalog)
        topology_mode_counter: Counter[str] = Counter()
        topology_enabled = False
        for matched in pipeline.run(extractor.run()):
            force_failed = bool((matched.meta or {}).get("match_drop_reason"))
            if matched.row is not None:
                decision = matched.row.match_decision
                if decision.topology_match_mode is not None:
                    topology_enabled = True
                    topology_mode_counter[decision.topology_match_mode.value] += 1
                elif bool(decision.meta.get("topology_applied")):
                    topology_enabled = True
            reporter.process(matched, force_failed=force_failed)

        stats = reporter.snapshot()
        report_sink.emit(
            SetContextEvent(
                name=ReportContextKey.MATCH,
                value={
                    **stats.to_context_payload(
                        ok_label="matched_ok",
                        failed_label="match_failed",
                    ),
                    "topology": {
                        "enabled": topology_enabled,
                        "by_mode": dict(sorted(topology_mode_counter.items())),
                    },
                },
            )
        )
        has_conflicts = stats.failed_rows > 0
        return StageCommandResultResolver().resolve(stats, has_conflicts=has_conflicts)


def _should_skip_match_result(result: TransformResult | None) -> bool:
    """Пропустить upstream-only записи, не дошедшие до собственного match/topology решения."""
    if result is None:
        return False
    if (result.meta or {}).get("match_drop_reason"):
        return False
    if result.row is not None:
        return False
    return not _has_match_stage_diagnostics(result)


def _has_match_stage_diagnostics(result: TransformResult) -> bool:
    """Проверить, есть ли у результата diagnostics именно match-стадии."""
    return any(
        item.stage == DiagnosticStage.MATCH or item.stage == DiagnosticStage.MATCH.value
        for item in (*result.errors, *result.warnings)
    )
