from __future__ import annotations

import logging
import json
from itertools import chain

from connector.infra.logging.setup import logEvent
from connector.infra.artifacts.plan_writer import write_plan_file
from connector.common.time import getNowIso
from connector.usecases.plan_usecase import PlanUseCase
from connector.domain.transform.core.extractor import Extractor
from connector.domain.transform.core.iterators import iter_ok
from connector.domain.transform.stages.stages import StagePipeline
from connector.usecases.resolve_usecase import ResolveUseCase
from connector.usecases.planning_match_runtime import open_match_runtime, iter_matched_ok
from connector.domain.transform.matcher.match_models import (
    MatchedRow,
    MatchCandidate,
    MatchDecision,
    MatchDecisionReason,
    MatchDecisionStatus,
    build_fingerprint,
)
from connector.domain.models import Identity, RowRef
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.core.result import TransformResult
from connector.datasets.registry import get_spec
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.ports.cache.roles import EnrichLookupPort, PendingReplayPort, PlanningRuntimePort


class ImportPlanService:
    """
    Оркестратор построения плана импорта.
    """

    def run(
        self,
        *,
        pending_replay: PendingReplayPort,
        enrich_lookup: EnrichLookupPort,
        planning_runtime: PlanningRuntimePort,
        csv_has_header: bool,
        include_deleted: bool,
        dataset: str,
        logger,
        run_id: str,
        report_items_limit: int,
        report_dir: str,
        vault_file: str | None = None,
        settings=None,
    ) -> CommandResult:
        generated_at = getNowIso()

        dataset_spec = get_spec(dataset)
        strict = getattr(settings, "diagnostics_strict", False)
        catalog = build_catalog(dataset, strict=strict)
        secret_store = None
        if vault_file:
            from connector.infra.secrets.file_vault_provider import FileVaultSecretStore

            secret_store = FileVaultSecretStore(vault_file)
        enrich_deps = dataset_spec.build_enrich_deps(
            settings,
            enrich_lookup=enrich_lookup,
            secret_store=secret_store,
        )
        planning_deps = dataset_spec.build_planning_deps(
            settings,
            planning_runtime=planning_runtime,
        )
        row_source = dataset_spec.build_record_source(
            csv_has_header=csv_has_header,
        )
        map_stage, normalize_stage, enrich_stage = dataset_spec.build_transform_stages(
            enrich_deps=enrich_deps,
            catalog=catalog,
        )
        extractor = Extractor(row_source, catalog=catalog)
        stage_pipeline = StagePipeline(
            [
                map_stage,
                normalize_stage,
                enrich_stage,
            ]
        )
        enriched_rows = iter_ok(
            stage_pipeline.run(extractor.run()),
            should_skip=lambda item: item.row is None,
        )
        match_stage, resolve_stage = dataset_spec.build_planning_stages(
            planning_deps=planning_deps,
            catalog=catalog,
            include_deleted=include_deleted,
            settings=settings,
        )
        match_spec = dataset_spec.build_match_spec(settings=settings)
        planning_runtime_dep = planning_deps.cache_gateway
        if planning_runtime_dep is None:
            raise ValueError("planning runtime is not configured")
        with open_match_runtime(
            run_id=run_id,
            match_stage=match_stage,
            match_runtime=planning_runtime_dep,
            report_items_limit=report_items_limit,
            include_matched_items=False,
            batch_size=getattr(settings, "match_batch_size", 500),
            flush_interval_ms=getattr(settings, "match_flush_interval_ms", 500),
        ) as match_runtime:
            matched_rows = iter_matched_ok(
                runtime=match_runtime,
                enriched_source=enriched_rows,
            )

            pending_rows = _load_pending_rows(
                dataset=dataset,
                pending_replay=pending_replay,
                include_deleted=include_deleted,
                ignored_fields=set(match_spec.match.ignored_fields),
            )
            matched_with_pending = chain(matched_rows, pending_rows)

            resolve_usecase = ResolveUseCase(
                report_items_limit=report_items_limit,
                include_resolved_items=False,
                batch_size=getattr(settings, "resolve_batch_size", 500),
                flush_interval_ms=getattr(settings, "resolve_flush_interval_ms", 500),
            )
            resolved_rows = iter_ok(
                resolve_usecase.iter_resolved(
                    matched_source=matched_with_pending,
                    resolve_stage=resolve_stage,
                    dataset=dataset,
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

def _load_pending_rows(
    *,
    dataset: str,
    pending_replay: PendingReplayPort,
    include_deleted: bool,
    ignored_fields: set[str],
) -> list[TransformResult[MatchedRow]]:
    # TODO(DSL plan/resolve): this replay path still reconstructs MatchDecision
    # inside usecase-level orchestration. After plan/resolve DSL migration,
    # move to a single source of truth (deserialize stored typed decision or
    # resolve via core), so usecase does not contain match decision logic.
    pending_rows = pending_replay.list_pending_rows(dataset)
    if not pending_rows:
        return []
    results: list[TransformResult[MatchedRow]] = []
    for pending in pending_rows:
        try:
            payload = json.loads(pending.payload)
        except (TypeError, json.JSONDecodeError):
            continue
        identity_data = payload.get("identity") or {}
        values = identity_data.get("values") or {}
        identity = Identity(primary=identity_data.get("primary") or "match_key", values=values)
        if not identity.primary_value:
            continue
        row_ref_data = payload.get("row_ref") or {}
        row_ref = RowRef(
            line_no=int(row_ref_data.get("line_no") or 0),
            row_id=str(row_ref_data.get("row_id") or pending.source_row_id),
            identity_primary=row_ref_data.get("identity_primary"),
            identity_value=row_ref_data.get("identity_value"),
        )
        desired_state = payload.get("desired_state") or {}
        target_id = payload.get("target_id")
        if target_id is None:
            # Legacy support: pending payload may store resource_id.
            target_id = payload.get("resource_id")
        meta = payload.get("meta") or {}

        candidates = pending_replay.find(
            dataset,
            {identity.primary: identity.primary_value},
            include_deleted=include_deleted,
        )
        if len(candidates) > 1:
            existing = None
            score = None
            decision_reason = "replay_ambiguous"
            top_candidates = tuple(
                {
                    "target_id": str(item.get("_id") or item.get("target_id"))
                    if (item.get("_id") or item.get("target_id")) is not None
                    else None,
                    "score": None,
                }
                for item in candidates[:3]
            )
            decision_candidates = tuple(
                MatchCandidate(
                    target_id=item.get("target_id"),
                    identity=identity.primary_value or None,
                    score=item.get("score"),
                    match_mode="replay",
                    evidence=item.get("evidence"),
                )
                for item in top_candidates
            )
            match_decision = MatchDecision(
                status=MatchDecisionStatus.AMBIGUOUS,
                reason_code=decision_reason,
                selected=None,
                candidates=decision_candidates,
                score=score,
                meta={"match_mode": "replay"},
            )
        elif candidates:
            existing = candidates[0]
            score = 1.0
            decision_reason = MatchDecisionReason.IDENTITY_EXACT
            selected_target = existing.get("_id") or existing.get("target_id")
            selected = MatchCandidate(
                target_id=str(selected_target) if selected_target is not None else None,
                identity=identity.primary_value or None,
                score=score,
                match_mode="exact",
                evidence={"identity_primary": identity.primary},
            )
            top_candidates = (
                {
                    "target_id": selected.target_id,
                    "score": score,
                },
            )
            match_decision = MatchDecision(
                status=MatchDecisionStatus.MATCHED,
                reason_code=decision_reason,
                selected=selected,
                candidates=(selected,),
                score=score,
                meta={"match_mode": "exact"},
            )
        else:
            existing = None
            score = None
            decision_reason = MatchDecisionReason.IDENTITY_NOT_FOUND
            match_decision = MatchDecision(
                status=MatchDecisionStatus.NOT_FOUND,
                reason_code=decision_reason,
                selected=None,
                candidates=(),
                score=score,
                meta={"match_mode": "exact"},
            )

        fingerprint, fingerprint_fields = build_fingerprint(
            desired_state,
            ignored_fields=ignored_fields,
        )
        matched_row = MatchedRow(
            row_ref=row_ref,
            identity=identity,
            desired_state=desired_state,
            existing=existing,
            fingerprint=fingerprint,
            fingerprint_fields=fingerprint_fields,
            source_links={},
            target_id=target_id,
            match_decision=match_decision,
        )
        record = SourceRecord(line_no=row_ref.line_no, record_id=row_ref.row_id, values={})
        results.append(
            TransformResult(
                record=record,
                row=matched_row,
                row_ref=row_ref,
                match_key=None,
                meta=meta,
                secret_candidates={},
                errors=[],
                warnings=[],
            )
        )
    return results
