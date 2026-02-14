from __future__ import annotations

from typing import Any, Callable

from connector.domain.planning.plan_models import Plan
from connector.domain.planning.record_ref import RecordRef
from connector.datasets.registry import get_spec
from connector.datasets.spec import DatasetSpec
from connector.domain.ports.target.execution import ExecutionResult, RequestExecutorProtocol
from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.domain.diagnostics.exceptions import MissingRequiredSecretError
from connector.domain.transform.matcher.identity_keys import format_identity_key
from connector.domain.ports.cache.roles import ApplyRuntimePort
from connector.domain.models import DiagnosticStage
from connector.domain.diagnostics.context import error as diag_error
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.policies import SystemErrorCode, resolve_primary_code
from connector.domain.diagnostics.translator import translate_execution_result, system_code_of
from connector.domain.diagnostics.boundary import diagnostic_boundary
from connector.domain.diagnostics.policies import default_stop_policy
from connector.usecases.apply.models import ApplyItemOutcome, ApplyResult, ApplySummary
from connector.usecases.apply.telemetry import ApplyTelemetrySink, NullApplyTelemetrySink


class ImportApplyService:
    """
    Оркестратор выполнения плана импорта.
    """

    def __init__(
        self,
        executor: RequestExecutorProtocol,
        secrets: SecretProviderProtocol | None = None,
        spec_resolver: Callable[..., DatasetSpec] = get_spec,
        apply_runtime: ApplyRuntimePort | None = None,
        identity_keys: dict[str, set[str]] | None = None,
        identity_id_fields: dict[str, str] | None = None,
    ):
        self.executor = executor
        self.secrets = secrets
        self.spec_resolver = spec_resolver
        self.apply_runtime = apply_runtime
        self.identity_keys = identity_keys or {}
        self.identity_id_fields = identity_id_fields or {}

    def apply_plan(
        self,
        plan: Plan,
        catalog: ErrorCatalog,
        *,
        stop_on_first_error: bool,
        max_actions: int | None,
        dry_run: bool,
        max_item_outcomes: int,
        resource_exists_retries: int,
        telemetry: ApplyTelemetrySink | None = None,
    ) -> ApplyResult:
        sink: ApplyTelemetrySink = telemetry or NullApplyTelemetrySink()
        created = updated = failed = 0
        rows_with_warnings = 0  # TODO: increment when adapters support field-level warnings; call sink.on_item_warn()
        skipped = getattr(plan.summary, "skipped", 0) if plan and plan.summary else 0
        actions_count = 0
        error_stats: dict[str, int] = {}
        fatal_error = False
        system_codes: set[SystemErrorCode] = set()
        item_outcomes: list[ApplyItemOutcome] = []
        outcomes_dropped = False

        dataset_name = getattr(plan.meta, "dataset", None)
        if not dataset_name:
            raise ValueError("Plan meta.dataset is required for apply")
        dataset_spec = self.spec_resolver(dataset_name, secrets=self.secrets)
        apply_adapter = dataset_spec.get_apply_adapter()
        stop_policy = default_stop_policy()

        def _add_outcome(outcome: ApplyItemOutcome) -> None:
            nonlocal outcomes_dropped
            if len(item_outcomes) < max_item_outcomes:
                item_outcomes.append(outcome)
            else:
                outcomes_dropped = True

        for item in plan.items:
            action = item.op
            ref = item.record_ref
            if max_actions is not None and actions_count >= max_actions:
                break

            actions_count += 1
            if not item.target_id:
                failed += 1
                diag = diag_error(
                    catalog=catalog,
                    stage=DiagnosticStage.APPLY,
                    code="TARGET_ID_MISSING",
                    field="target_id",
                    message="target_id is required",
                    record_ref=None,
                )
                error_stats[diag.code] = error_stats.get(diag.code, 0) + 1
                sys_code = system_code_of(catalog, diag)
                system_codes.add(sys_code)
                sink.on_item_error(record_ref=ref, op=action, diag=diag)
                _add_outcome(ApplyItemOutcome(
                    record_ref=ref,
                    op=action,
                    status="FAILED",
                    target_id=None,
                    diagnostics=(diag,),
                ))
                if stop_on_first_error:
                    break
                continue

            retries_left = resource_exists_retries
            current_item = item
            while True:
                try:
                    if dry_run:
                        exec_result = ExecutionResult(
                            ok=True, status_code=200, response_json={"dry_run": True},
                            error_code=None, error_message=None,
                        )
                    else:
                        if apply_adapter is None:
                            raise ValueError("Apply adapter is not configured")
                        request_spec = apply_adapter.to_request(current_item)
                        boundary_errors: list = []
                        exec_result: ExecutionResult | None = None
                        with diagnostic_boundary(
                            stage=DiagnosticStage.APPLY,
                            catalog=catalog,
                            sink=boundary_errors,
                            record_ref=None,
                        ):
                            exec_result = self.executor.execute(request_spec)
                        if boundary_errors:
                            failed += 1
                            for diag in boundary_errors:
                                error_stats[diag.code] = error_stats.get(diag.code, 0) + 1
                                sys_code = system_code_of(catalog, diag)
                                system_codes.add(sys_code)
                                sink.on_item_error(record_ref=ref, op=action, diag=diag)
                            if stop_policy.is_fatal(system_code_of(catalog, boundary_errors[0])):
                                fatal_error = True
                            _add_outcome(ApplyItemOutcome(
                                record_ref=ref,
                                op=action,
                                status="FAILED",
                                target_id=current_item.target_id,
                                diagnostics=tuple(boundary_errors),
                            ))
                            break
                        if exec_result is None:
                            failed += 1
                            diag = diag_error(
                                catalog=catalog,
                                stage=DiagnosticStage.APPLY,
                                code="INTERNAL_ERROR",
                                field=None,
                                message="empty execution result",
                                record_ref=None,
                            )
                            error_stats[diag.code] = error_stats.get(diag.code, 0) + 1
                            sys_code = system_code_of(catalog, diag)
                            system_codes.add(sys_code)
                            sink.on_item_error(record_ref=ref, op=action, diag=diag)
                            _add_outcome(ApplyItemOutcome(
                                record_ref=ref,
                                op=action,
                                status="FAILED",
                                target_id=current_item.target_id,
                                diagnostics=(diag,),
                            ))
                            break

                    if exec_result.ok:
                        if action == "create":
                            created += 1
                        elif action == "update":
                            updated += 1
                        sink.on_item_ok(record_ref=ref, op=action, target_id=current_item.target_id)
                        self._update_identity_index(
                            dataset=dataset_name,
                            desired_state=current_item.desired_state,
                            response_json=exec_result.response_json,
                            source_ref=current_item.source_ref,
                        )
                        break

                    next_item = None
                    if not dry_run and apply_adapter:
                        next_item = apply_adapter.on_failed_request(current_item, exec_result, retries_left)
                    if next_item and retries_left > 0:
                        retries_left -= 1
                        current_item = next_item
                        continue

                    failed += 1
                    diag = translate_execution_result(
                        catalog=catalog,
                        stage=DiagnosticStage.SINK,
                        result=exec_result,
                        record_ref=None,
                    )
                    error_stats[diag.code] = error_stats.get(diag.code, 0) + 1
                    sys_code = system_code_of(catalog, diag)
                    system_codes.add(sys_code)
                    if stop_policy.is_fatal(sys_code):
                        fatal_error = True
                    sink.on_item_error(record_ref=ref, op=action, diag=diag)
                    _add_outcome(ApplyItemOutcome(
                        record_ref=ref,
                        op=action,
                        status="FAILED",
                        target_id=current_item.target_id,
                        diagnostics=(diag,),
                    ))
                    break
                except MissingRequiredSecretError as exc:
                    failed += 1
                    err_code = exc.code
                    error_stats[err_code] = error_stats.get(err_code, 0) + 1
                    diag = diag_error(
                        catalog=catalog,
                        stage=DiagnosticStage.APPLY,
                        code=err_code,
                        field=exc.field,
                        message=str(exc),
                        record_ref=None,
                    )
                    sys_code = system_code_of(catalog, diag)
                    system_codes.add(sys_code)
                    sink.on_item_error(record_ref=ref, op=action, diag=diag)
                    _add_outcome(ApplyItemOutcome(
                        record_ref=ref,
                        op=action,
                        status="FAILED",
                        target_id=current_item.target_id,
                        diagnostics=(diag,),
                    ))
                    break
                except Exception as exc:
                    failed += 1
                    err_code = "UNEXPECTED_ERROR"
                    error_stats[err_code] = error_stats.get(err_code, 0) + 1
                    diag = diag_error(
                        catalog=catalog,
                        stage=DiagnosticStage.APPLY,
                        code=err_code,
                        field=None,
                        message=str(exc),
                        record_ref=None,
                    )
                    sys_code = system_code_of(catalog, diag)
                    system_codes.add(sys_code)
                    sink.on_item_error(record_ref=ref, op=action, diag=diag)
                    _add_outcome(ApplyItemOutcome(
                        record_ref=ref,
                        op=action,
                        status="FAILED",
                        target_id=current_item.target_id,
                        diagnostics=(diag,),
                    ))
                    break

            if stop_on_first_error and failed:
                break

        if not system_codes:
            system_codes.add(SystemErrorCode.OK)

        primary_code = resolve_primary_code(system_codes, stop_policy)
        all_codes = tuple(sorted(system_codes, key=lambda c: c.value))

        summary = ApplySummary(
            created=created,
            updated=updated,
            failed=failed,
            skipped=skipped,
            items_total=actions_count,
            rows_with_warnings=rows_with_warnings,
            error_stats=dict(error_stats),
        )

        result = ApplyResult(
            summary=summary,
            primary_code=primary_code,
            all_codes=all_codes,
            fatal_error=fatal_error,
            item_outcomes=tuple(item_outcomes),
            outcomes_truncated=outcomes_dropped,
        )

        sink.on_summary(
            primary_code=result.primary_code,
            all_codes=result.all_codes,
            fatal_error=result.fatal_error,
            counters=result.summary,
        )

        return result

    def _update_identity_index(
        self,
        *,
        dataset: str,
        desired_state: dict[str, Any],
        response_json: Any | None,
        source_ref: dict[str, Any] | None,
    ) -> None:
        if self.apply_runtime is None:
            return
        key_names = self.identity_keys.get(dataset)
        if not key_names:
            return
        id_field = self.identity_id_fields.get(dataset, "_id")
        resolved_id = None
        if isinstance(response_json, dict):
            resolved_id = response_json.get(id_field)
        if resolved_id is None:
            resolved_id = desired_state.get(id_field)
        if resolved_id is None:
            return
        resolved_id_str = str(resolved_id).strip()
        if resolved_id_str == "":
            return
        for key_name in key_names:
            value = desired_state.get(key_name)
            if value is None and isinstance(source_ref, dict):
                value = source_ref.get(key_name)
            if value is None:
                continue
            value_str = str(value).strip()
            if value_str == "":
                continue
            identity_key = format_identity_key(key_name, value_str)
            self.apply_runtime.upsert_identity(dataset, identity_key, resolved_id_str)
            self._resolve_pending_for_key(dataset, identity_key)

    def _resolve_pending_for_key(self, dataset: str, identity_key: str) -> None:
        if self.apply_runtime is None:
            return
        pending = self.apply_runtime.list_pending_for_key(dataset, identity_key)
        for item in pending:
            self.apply_runtime.mark_resolved(item.pending_id)
