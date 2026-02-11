from __future__ import annotations

from typing import Iterable

from connector.domain.transform.matcher.match_models import MatchedRow
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.models import DiagnosticStage
from connector.domain.transform.core.iterators import iter_micro_batches
from connector.domain.transform.core.result_processor import PlanningResultProcessor
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.stages.stages import MatchStage


class MatchUseCase:
    """
    Назначение/ответственность:
        Use-case для сопоставления строк после enrich (enrich -> match).
    """

    def __init__(
        self,
        report_items_limit: int,
        include_matched_items: bool,
        batch_size: int = 500,
        flush_interval_ms: int = 500,
    ) -> None:
        self.report_items_limit = report_items_limit
        self.include_matched_items = include_matched_items
        self.batch_size = batch_size
        self.flush_interval_ms = flush_interval_ms

    def iter_matched(
        self,
        enriched_source: Iterable[TransformResult],
        match_stage: MatchStage,
        *,
        run_scope: str | None = None,
    ):
        """
        Назначение:
            Итератор сопоставленных строк (для resolver/plan).
        """
        return self._iter_matched(
            enriched_source,
            match_stage,
            run_scope=run_scope,
        )

    def run(
        self,
        enriched_source: Iterable[TransformResult],
        match_stage: MatchStage,
        dataset: str,
        report,
        run_scope: str | None = None,
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

        for matched in self._iter_matched(
            enriched_source,
            match_stage,
            run_scope=run_scope,
        ):
            force_failed = bool((matched.meta or {}).get("match_drop_reason"))
            processor.process(matched, force_failed=force_failed)

        result = processor.finalize()
        if report.summary.errors_total > 0:
            result.add_code(SystemErrorCode.CONFLICT)
        return result

    def _iter_matched(
        self,
        enriched_source: Iterable[TransformResult],
        match_stage: MatchStage,
        *,
        run_scope: str | None = None,
    ):
        matcher = match_stage.matcher
        matcher.reset_source_dedup()
        matcher.bind_runtime_scope(run_scope)
        for batch in iter_micro_batches(
            enriched_source,
            batch_size=self.batch_size,
            flush_interval_ms=self.flush_interval_ms,
        ):
            for matched in match_stage.run(batch):
                yield matched
