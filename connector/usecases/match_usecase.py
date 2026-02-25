from __future__ import annotations

from typing import Iterable

from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.models import DiagnosticStage
from connector.domain.transform.core.result_processor import PlanningResultProcessor
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.stages.stages import MatchStage


class MatchUseCase:
    """
    Назначение/ответственность:
        Use-case для сопоставления строк после enrich (enrich -> match).

    Граница ответственности:
        - Owns: report aggregation.
        - Micro-batching делегирован MatchStage (IMatchBatchSettings).
        - Does NOT: управлять lifecycle dedup-state или scope cleanup.
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
        enriched_source: Iterable[TransformResult],
        match_stage: MatchStage,
        dataset: str,
        report,
    ) -> CommandResult:
        report.set_meta(dataset=dataset, items_limit=self.report_items_limit)
        processor = PlanningResultProcessor(
            report=report,
            include_items=self.include_matched_items,
            context_key="match",
            ok_label="matched_ok",
            failed_label="match_failed",
            meta_builder=lambda r: {
                "match_status": (r.row.match_decision.status.value if r.row else None)
            },
            report_stage=DiagnosticStage.MATCH,
            include_upstream_diagnostics=False,
        )

        for matched in match_stage.run(enriched_source):
            force_failed = bool((matched.meta or {}).get("match_drop_reason"))
            processor.process(matched, force_failed=force_failed)

        result = processor.finalize()
        if report.summary.errors_total > 0:
            result.add_code(SystemErrorCode.CONFLICT)
        return result
