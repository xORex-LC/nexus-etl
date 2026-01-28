from __future__ import annotations

import logging

from connector.infra.logging.setup import logEvent
from connector.infra.artifacts.plan_writer import write_plan_file
from connector.common.time import getNowIso
from connector.usecases.plan_usecase import PlanUseCase
from connector.usecases.enrich_usecase import EnrichUseCase
from connector.usecases.validate_usecase import ValidateUseCase
from connector.usecases.match_usecase import MatchUseCase
from connector.usecases.resolve_usecase import ResolveUseCase
from connector.domain.planning.matcher import Matcher
from connector.domain.planning.resolver import Resolver
import json
from connector.domain.planning.match_models import MatchedRow
from connector.domain.models import Identity, MatchStatus, RowRef
from connector.domain.transform.source_record import SourceRecord
from connector.domain.transform.result import TransformResult
from connector.domain.planning.matcher import _build_fingerprint
from connector.datasets.registry import get_spec

class ImportPlanService:
    """
    Оркестратор построения плана импорта.
    """

    def run(
        self,
        conn,
        csv_path: str,
        csv_has_header: bool,
        include_deleted: bool,
        dataset: str,
        logger,
        run_id: str,
        report_items_limit: int,
        report_dir: str,
        vault_file: str | None = None,
        settings=None,
    ) -> int:
        generated_at = getNowIso()

        dataset_spec = get_spec(dataset)
        validation_deps = dataset_spec.build_validation_deps(conn, settings)
        secret_store = None
        if vault_file:
            from connector.infra.secrets.file_vault_provider import FileVaultSecretStore

            secret_store = FileVaultSecretStore(vault_file)
        enrich_deps = dataset_spec.build_enrich_deps(conn, settings, secret_store=secret_store)
        planning_deps = dataset_spec.build_planning_deps(conn, settings)
        row_source = dataset_spec.build_record_source(
            csv_path=csv_path,
            csv_has_header=csv_has_header,
        )
        transform_bundle = dataset_spec.build_transformers(validation_deps, enrich_deps)
        transformer = transform_bundle.build_pipeline()
        validator_bundle = dataset_spec.build_validator(validation_deps)
        validator = validator_bundle.validator
        enrich_usecase = EnrichUseCase(
            report_items_limit=report_items_limit,
            include_enriched_items=False,
        )
        enriched_ok = enrich_usecase.iter_enriched_ok(
            row_source=row_source,
            transformer=transformer,
        )
        validate_usecase = ValidateUseCase(
            report_items_limit=report_items_limit,
            include_valid_items=False,
        )
        validated_rows = validate_usecase.iter_validated_ok(
            enriched_source=enriched_ok,
            validator=validator,
        )
        matching_rules = dataset_spec.build_matching_rules()
        resolve_rules = dataset_spec.build_resolve_rules()
        link_rules = dataset_spec.build_link_rules()
        cache_repo = planning_deps.cache_repo
        if cache_repo is None:
            raise ValueError("planning cache_repo is not configured")
        if planning_deps.identity_repo is None:
            raise ValueError("planning identity_repo is not configured")
        if planning_deps.pending_repo is None:
            raise ValueError("planning pending_repo is not configured")

        matcher = Matcher(
            dataset=dataset,
            cache_repo=cache_repo,
            matching_rules=matching_rules,
            resolve_rules=resolve_rules,
            include_deleted=include_deleted,
        )
        match_usecase = MatchUseCase(
            report_items_limit=report_items_limit,
            include_matched_items=False,
        )
        matched_rows = list(
            match_usecase.iter_matched_ok(
                validated_source=validated_rows,
                matcher=matcher,
            )
        )

        pending_rows = _load_pending_rows(
            dataset=dataset,
            pending_repo=planning_deps.pending_repo,
            cache_repo=cache_repo,
            include_deleted=include_deleted,
            ignored_fields=matching_rules.ignored_fields,
        )
        matched_rows.extend(pending_rows)

        resolver = Resolver(
            resolve_rules,
            link_rules,
            identity_repo=planning_deps.identity_repo,
            pending_repo=planning_deps.pending_repo,
            settings=planning_deps.resolver_settings,
        )
        resolve_usecase = ResolveUseCase(
            report_items_limit=report_items_limit,
            include_resolved_items=False,
        )
        resolved_rows = resolve_usecase.iter_resolved_ok(
            matched_source=matched_rows,
            resolver=resolver,
            dataset=dataset,
        )

        use_case = PlanUseCase()
        plan_result = use_case.run(
            resolved_row_source=resolved_rows,
        )
        plan_meta = {
            "csv_path": csv_path,
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

        return 0


def _load_pending_rows(
    *,
    dataset: str,
    pending_repo,
    cache_repo,
    include_deleted: bool,
    ignored_fields: set[str],
) -> list[TransformResult[MatchedRow]]:
    if pending_repo is None:
        return []
    pending_rows = pending_repo.list_pending_rows(dataset)
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
        resource_id = payload.get("resource_id")
        meta = payload.get("meta") or {}

        candidates = cache_repo.find(
            dataset,
            {identity.primary: identity.primary_value},
            include_deleted=include_deleted,
        )
        if len(candidates) > 1:
            match_status = MatchStatus.CONFLICT_TARGET
            existing = None
        elif candidates:
            match_status = MatchStatus.MATCHED
            existing = candidates[0]
        else:
            match_status = MatchStatus.NOT_FOUND
            existing = None

        fingerprint = _build_fingerprint(desired_state, ignored_fields)
        matched_row = MatchedRow(
            row_ref=row_ref,
            identity=identity,
            match_status=match_status,
            desired_state=desired_state,
            existing=existing,
            fingerprint=fingerprint,
            source_links={},
            resource_id=resource_id,
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
