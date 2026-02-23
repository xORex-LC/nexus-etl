from __future__ import annotations

import logging
from typing import Iterable

from connector.config.app_settings import MatchingRuntimeSettings
from connector.infra.logging.setup import logEvent
from connector.infra.artifacts.plan_writer import write_plan_file
from connector.common.time import getNowIso
from connector.usecases.plan_usecase import PlanUseCase
from connector.domain.transform.core.extractor import Extractor
from connector.domain.transform.core.iterators import iter_ok
from connector.domain.transform.stages.stages import MatchStage, ResolveStage, PipelineOrchestrator
from connector.usecases.resolve_usecase import ResolveUseCase
from connector.usecases.planning_match_runtime import open_match_runtime, iter_matched_ok
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.ports.cache.roles import PlanningRuntimePort


class ImportPlanService:
    """
    Назначение:
        Оркестратор построения плана импорта.

    Граница ответственности:
        - Координирует transform pipeline → match → resolve → plan.
        - НЕ собирает стадии: получает pre-built stages от caller (DEC-004).
        - НЕ управляет lifecycle инфры: cache/vault — ответственность DI-контейнера.
    """

    def run(
        self,
        *,
        planning_runtime: PlanningRuntimePort,
        include_deleted: bool,
        matching_runtime_settings: MatchingRuntimeSettings,
        dataset: str,
        logger,
        run_id: str,
        report_items_limit: int,
        report_dir: str,
        row_source: Iterable,
        transform_pipeline: PipelineOrchestrator,
        match_stage: MatchStage,
        resolve_stage: ResolveStage,
        catalog: ErrorCatalog,
    ) -> CommandResult:
        generated_at = getNowIso()

        extractor = Extractor(row_source, catalog=catalog)
        enriched_rows = iter_ok(
            transform_pipeline.run(extractor.run()),
            should_skip=lambda item: item.row is None,
        )
        with open_match_runtime(
            run_id=run_id,
            match_stage=match_stage,
            match_runtime=planning_runtime,
            report_items_limit=report_items_limit,
            include_matched_items=False,
            batch_size=matching_runtime_settings.match_batch_size,
            flush_interval_ms=matching_runtime_settings.match_flush_interval_ms,
        ) as match_runtime:
            matched_rows = iter_matched_ok(
                runtime=match_runtime,
                enriched_source=enriched_rows,
            )

            resolve_usecase = ResolveUseCase(
                report_items_limit=report_items_limit,
                include_resolved_items=False,
                batch_size=matching_runtime_settings.resolve_batch_size,
                flush_interval_ms=matching_runtime_settings.resolve_flush_interval_ms,
            )
            resolved_rows = iter_ok(
                resolve_usecase.iter_resolved(
                    matched_source=matched_rows,
                    resolve_stage=resolve_stage,
                    dataset=dataset,
                    pending_replay=planning_runtime,
                )
            )

            use_case = PlanUseCase()
            plan_result = use_case.run(
                resolved_row_source=resolved_rows,
            )
        plan_meta = {
            "csv_path": None,
            "include_deleted": include_deleted,
            "dataset": dataset,
        }
        plan_path = write_plan_file(
            plan_items=plan_result.items,
            summary=plan_result.summary_as_dict(),
            meta=plan_meta,
            report_dir=report_dir,
            run_id=run_id,
            generated_at=generated_at,
        )
        logEvent(logger, logging.INFO, run_id, "plan", f"Plan written: {plan_path}")
        result = CommandResult()
        result.add_code(SystemErrorCode.OK)
        return result
