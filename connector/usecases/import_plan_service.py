from __future__ import annotations

import logging
import json
from itertools import chain

from connector.config.app_settings import (
    MatchingRuntimeSettings,
    ObservabilitySettings,
    PendingSettings,
)
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
    MatchDecisionStatus,
)
from connector.domain.models import Identity, RowRef
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.core.result import TransformResult
from connector.datasets.registry import get_spec
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.ports.cache.roles import EnrichLookupPort, PendingReplayPort, PlanningRuntimePort
from connector.domain.ports.secrets.provider import SecretStoreProtocol
from connector.domain.ports.transform.dictionaries import DictionaryProviderPort


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
        observability_settings: ObservabilitySettings,
        pending_settings: PendingSettings,
        matching_runtime_settings: MatchingRuntimeSettings,
        dataset: str,
        logger,
        run_id: str,
        report_items_limit: int,
        report_dir: str,
        secret_store: SecretStoreProtocol | None = None,
        dictionaries: DictionaryProviderPort | None = None,
    ) -> CommandResult:
        generated_at = getNowIso()

        dataset_spec = get_spec(dataset)
        strict = observability_settings.diagnostics_strict
        catalog = build_catalog(dataset, strict=strict)
        enrich_deps = dataset_spec.build_enrich_deps(
            None,
            enrich_lookup=enrich_lookup,
            secret_store=secret_store,
            dictionaries=dictionaries,
        )
        planning_deps = dataset_spec.build_planning_deps(
            pending_settings,
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
            settings=pending_settings,
        )
        planning_runtime_dep = planning_deps.cache_gateway
        if planning_runtime_dep is None:
            raise ValueError("planning runtime is not configured")
        with open_match_runtime(
            run_id=run_id,
            match_stage=match_stage,
            match_runtime=planning_runtime_dep,
            report_items_limit=report_items_limit,
            include_matched_items=False,
            batch_size=matching_runtime_settings.match_batch_size,
            flush_interval_ms=matching_runtime_settings.match_flush_interval_ms,
        ) as match_runtime:
            matched_rows = iter_matched_ok(
                runtime=match_runtime,
                enriched_source=enriched_rows,
            )

            pending_rows = _load_pending_rows(
                dataset=dataset,
                pending_replay=pending_replay,
            )
            matched_with_pending = chain(matched_rows, pending_rows)

            resolve_usecase = ResolveUseCase(
                report_items_limit=report_items_limit,
                include_resolved_items=False,
                batch_size=matching_runtime_settings.resolve_batch_size,
                flush_interval_ms=matching_runtime_settings.resolve_flush_interval_ms,
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
) -> list[TransformResult[MatchedRow]]:
    pending_rows = pending_replay.list_pending_rows(dataset)
    if not pending_rows:
        return []
    results: list[TransformResult[MatchedRow]] = []
    for pending in pending_rows:
        try:
            payload = json.loads(pending.payload)
        except (TypeError, json.JSONDecodeError):
            continue
        parsed = _deserialize_pending_matched_row(payload)
        if parsed is None:
            continue
        matched_row, meta = parsed
        row_ref = matched_row.row_ref
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


def _deserialize_pending_matched_row(
    payload: dict,
) -> tuple[MatchedRow, dict[str, object]] | None:
    identity_data = payload.get("identity")
    row_ref_data = payload.get("row_ref")
    desired_state = payload.get("desired_state")
    existing = payload.get("existing")
    fingerprint = payload.get("fingerprint")
    fingerprint_fields = payload.get("fingerprint_fields")
    decision_data = payload.get("match_decision")
    if not isinstance(identity_data, dict):
        return None
    if not isinstance(row_ref_data, dict):
        return None
    if not isinstance(desired_state, dict):
        return None
    if existing is not None and not isinstance(existing, dict):
        return None
    if not isinstance(fingerprint, str) or not fingerprint:
        return None
    if not isinstance(fingerprint_fields, list):
        return None
    if not isinstance(decision_data, dict):
        return None

    values = identity_data.get("values")
    primary = identity_data.get("primary")
    if not isinstance(values, dict):
        return None
    if not isinstance(primary, str) or not primary:
        return None
    identity = Identity(primary=primary, values={str(k): str(v) for k, v in values.items() if v is not None})
    if not identity.primary_value:
        return None

    row_id = row_ref_data.get("row_id")
    line_no_raw = row_ref_data.get("line_no")
    if not isinstance(row_id, str) or not row_id:
        return None
    try:
        line_no = int(line_no_raw)
    except (TypeError, ValueError):
        return None
    row_ref = RowRef(
        line_no=line_no,
        row_id=row_id,
        identity_primary=row_ref_data.get("identity_primary"),
        identity_value=row_ref_data.get("identity_value"),
    )

    match_decision = _deserialize_match_decision(decision_data)
    if match_decision is None:
        return None

    source_links = _deserialize_source_links(payload.get("source_links"))
    if source_links is None:
        return None

    fingerprint_fields_tuple = tuple(str(item) for item in fingerprint_fields)
    target_id = payload.get("target_id")
    if target_id is not None:
        target_id = str(target_id)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}

    matched_row = MatchedRow(
        row_ref=row_ref,
        identity=identity,
        desired_state=desired_state,
        existing=existing,
        fingerprint=fingerprint,
        fingerprint_fields=fingerprint_fields_tuple,
        match_decision=match_decision,
        source_links=source_links,
        target_id=target_id,
    )
    return matched_row, meta


def _deserialize_match_decision(payload: dict) -> MatchDecision | None:
    status_raw = payload.get("status")
    reason_code = payload.get("reason_code")
    if not isinstance(status_raw, str):
        return None
    if not isinstance(reason_code, str) or not reason_code:
        return None
    try:
        status = MatchDecisionStatus(status_raw)
    except ValueError:
        return None

    selected_payload = payload.get("selected")
    selected = _deserialize_candidate(selected_payload) if selected_payload is not None else None
    if selected_payload is not None and selected is None:
        return None

    candidates_payload = payload.get("candidates")
    if not isinstance(candidates_payload, list):
        return None
    candidates: list[MatchCandidate] = []
    for item in candidates_payload:
        candidate = _deserialize_candidate(item)
        if candidate is None:
            return None
        candidates.append(candidate)

    score = payload.get("score")
    if score is not None and not isinstance(score, (int, float)):
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    message = payload.get("message")
    if message is not None and not isinstance(message, str):
        return None

    return MatchDecision(
        status=status,
        reason_code=reason_code,
        message=message,
        selected=selected,
        candidates=tuple(candidates),
        score=float(score) if isinstance(score, (int, float)) else None,
        meta=meta,
    )


def _deserialize_candidate(payload: object) -> MatchCandidate | None:
    if not isinstance(payload, dict):
        return None
    match_mode = payload.get("match_mode")
    if not isinstance(match_mode, str) or not match_mode:
        return None
    target_id = payload.get("target_id")
    identity = payload.get("identity")
    score = payload.get("score")
    if target_id is not None:
        target_id = str(target_id)
    if identity is not None:
        identity = str(identity)
    if score is not None and not isinstance(score, (int, float)):
        return None
    evidence = payload.get("evidence")
    if evidence is not None and not isinstance(evidence, dict):
        return None
    return MatchCandidate(
        target_id=target_id,
        identity=identity,
        score=float(score) if isinstance(score, (int, float)) else None,
        match_mode=match_mode,
        evidence=evidence,
    )


def _deserialize_source_links(payload: object) -> dict[str, Identity] | None:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        return None
    source_links: dict[str, Identity] = {}
    for field, raw_identity in payload.items():
        if not isinstance(field, str):
            return None
        if not isinstance(raw_identity, dict):
            return None
        primary = raw_identity.get("primary")
        values = raw_identity.get("values")
        if not isinstance(primary, str) or not primary:
            return None
        if not isinstance(values, dict):
            return None
        source_links[field] = Identity(
            primary=primary,
            values={str(k): str(v) for k, v in values.items() if v is not None},
        )
    return source_links
