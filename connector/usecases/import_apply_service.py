"""
Назначение:
    Оркестратор apply-операций поверх target executor с агрегацией доменного результата.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from connector.domain.planning.plan_models import Operation, Plan, PlanItem
from connector.domain.planning.record_ref import RecordRef
from connector.domain.diagnostics.exceptions import MissingRequiredSecretError
from connector.domain.models import DiagnosticItem, DiagnosticStage
from connector.domain.diagnostics.context import error as diag_error
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.policies import StopPolicy, SystemErrorCode, resolve_primary_code
from connector.domain.diagnostics.translator import translate_execution_result, system_code_of
from connector.domain.diagnostics.boundary import diagnostic_boundary
from connector.domain.diagnostics.policies import default_stop_policy
from connector.domain.ports.secrets.retention import SecretApplyRetentionHookProtocol
from connector.domain.ports.target.apply import ApplyAdapterProtocol
from connector.domain.ports.target.execution import ExecutionResult, RequestExecutorProtocol
from connector.usecases.apply.models import ApplyItemOutcome, ApplyResult, ApplySummary
from connector.usecases.apply.telemetry import ApplyTelemetrySink, NullApplyTelemetrySink
from connector.usecases.common.identity_sync import IdentityIndexSyncer

_OUTCOME_STATUS_FAILED = "FAILED"


@dataclass
class _ItemProcessContext:
    """Контекст обработки одного plan-item: телеметрия, стоп-политика и агрегаторы ошибок."""

    catalog: ErrorCatalog
    sink: ApplyTelemetrySink
    stop_policy: StopPolicy
    error_stats: dict[str, int]
    retention_stats: dict[str, int]
    system_codes: set[SystemErrorCode]
    add_outcome: Callable[[ApplyItemOutcome], None]
    plan_run_id: str | None
    allow_post_success_side_effects: bool
    retention_hook: SecretApplyRetentionHookProtocol | None = None

    def register_error(self, *, ref: RecordRef, action: str, diag: DiagnosticItem) -> SystemErrorCode:
        self.error_stats[diag.code] = self.error_stats.get(diag.code, 0) + 1
        sys_code = system_code_of(self.catalog, diag)
        self.system_codes.add(sys_code)
        self.sink.on_item_error(record_ref=ref, op=action, diag=diag)
        return sys_code

    def add_failed_outcome(
        self,
        *,
        item: PlanItem,
        action: str,
        diagnostics: tuple[DiagnosticItem, ...],
    ) -> None:
        self.add_outcome(
            ApplyItemOutcome(
                record_ref=item.record_ref,
                op=action,
                status=_OUTCOME_STATUS_FAILED,
                target_id=item.target_id,
                diagnostics=diagnostics,
            )
        )

    def is_fatal(self, sys_code: SystemErrorCode) -> bool:
        return self.stop_policy.is_fatal(sys_code)

    def register_retention(self, counters: dict[str, int] | None) -> None:
        if not counters:
            return
        for key, value in counters.items():
            self.retention_stats[key] = self.retention_stats.get(key, 0) + int(value)


@dataclass(frozen=True, slots=True)
class _ItemProcessResult:
    """Приращения итоговых счётчиков после обработки одного элемента плана."""

    created_inc: int = 0
    updated_inc: int = 0
    failed_inc: int = 0
    item_fatal: bool = False


class ImportApplyService:
    """
    Назначение/ответственность:
        Выполняет plan-item через adapter+executor, применяет stop-политику и
        возвращает агрегированный ApplyResult.

    Контракт:
        - при `allow_post_success_side_effects=False` success-path не выполняет
          post-write side effects (identity sync + secret retention hooks).
    """

    def __init__(
        self,
        executor: RequestExecutorProtocol,
        identity_syncer: IdentityIndexSyncer | None = None,
        secret_retention: SecretApplyRetentionHookProtocol | None = None,
        *,
        allow_post_success_side_effects: bool = True,
    ) -> None:
        self.executor = executor
        self.identity_syncer = identity_syncer
        self.secret_retention = secret_retention
        self.allow_post_success_side_effects = allow_post_success_side_effects

    def apply_plan(
        self,
        plan: Plan,
        catalog: ErrorCatalog,
        apply_adapter: ApplyAdapterProtocol | None,
        *,
        stop_on_first_error: bool,
        max_actions: int | None,
        max_item_outcomes: int,
        telemetry: ApplyTelemetrySink | None = None,
    ) -> ApplyResult:
        """
        Выполнить план импорта и вернуть итог apply-цикла.

        Контракт:
            - `plan.meta.dataset` обязателен;
            - `apply_adapter` должен быть настроен для преобразования PlanItem -> RequestSpec;
            - `max_item_outcomes` ограничивает число сохранённых per-item outcome.
        """
        sink: ApplyTelemetrySink = telemetry or NullApplyTelemetrySink()
        created = updated = failed = 0
        # На текущем контракте apply-adapter нет field-level warnings, поэтому всегда 0.
        rows_with_warnings = 0
        skipped = getattr(plan.summary, "skipped", 0) if plan and plan.summary else 0
        actions_count = 0
        error_stats: dict[str, int] = {}
        retention_stats: dict[str, int] = {}
        fatal_error = False
        system_codes: set[SystemErrorCode] = set()
        item_outcomes: list[ApplyItemOutcome] = []
        outcomes_dropped = False

        dataset_name = getattr(plan.meta, "dataset", None)
        if not dataset_name:
            raise ValueError("Plan meta.dataset is required for apply")

        stop_policy = default_stop_policy()

        def _add_outcome(outcome: ApplyItemOutcome) -> None:
            nonlocal outcomes_dropped
            if len(item_outcomes) < max_item_outcomes:
                item_outcomes.append(outcome)
            else:
                outcomes_dropped = True

        context = _ItemProcessContext(
            catalog=catalog,
            sink=sink,
            stop_policy=stop_policy,
            error_stats=error_stats,
            retention_stats=retention_stats,
            system_codes=system_codes,
            add_outcome=_add_outcome,
            plan_run_id=getattr(plan.meta, "run_id", None),
            allow_post_success_side_effects=self.allow_post_success_side_effects,
            retention_hook=self.secret_retention,
        )

        for item in plan.items:
            if max_actions is not None and actions_count >= max_actions:
                break

            actions_count += 1
            item_result = self._process_item(
                item=item,
                dataset_name=dataset_name,
                apply_adapter=apply_adapter,
                context=context,
            )
            created += item_result.created_inc
            updated += item_result.updated_inc
            failed += item_result.failed_inc
            fatal_error = fatal_error or item_result.item_fatal

            if stop_on_first_error and item_result.failed_inc > 0:
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
            retention_stats=dict(retention_stats),
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

    def _process_item(
        self,
        *,
        item: PlanItem,
        dataset_name: str,
        apply_adapter: ApplyAdapterProtocol | None,
        context: _ItemProcessContext,
    ) -> _ItemProcessResult:
        action = item.op
        ref = item.record_ref
        try:
            exec_result, boundary_errors = self._execute_item(
                item=item,
                apply_adapter=apply_adapter,
                context=context,
            )
            if boundary_errors:
                return self._handle_boundary_errors(
                    item=item,
                    action=action,
                    ref=ref,
                    context=context,
                    boundary_errors=boundary_errors,
                )

            if exec_result is None:
                diag = diag_error(
                    catalog=context.catalog,
                    stage=DiagnosticStage.APPLY,
                    code="INTERNAL_ERROR",
                    field=None,
                    message="empty execution result",
                    record_ref=None,
                )
                return self._handle_single_failure_diag(
                    item=item,
                    action=action,
                    ref=ref,
                    context=context,
                    diag=diag,
                    fatal=False,
                )

            if exec_result.ok:
                return self._handle_success_item(
                    item=item,
                    action=action,
                    dataset_name=dataset_name,
                    response_payload=exec_result.response_payload,
                    context=context,
                )

            diag = translate_execution_result(
                catalog=context.catalog,
                stage=DiagnosticStage.SINK,
                result=exec_result,
                record_ref=None,
            )
            sys_code = system_code_of(context.catalog, diag)
            return self._handle_single_failure_diag(
                item=item,
                action=action,
                ref=ref,
                context=context,
                diag=diag,
                fatal=context.is_fatal(sys_code),
            )
        except MissingRequiredSecretError as exc:
            return self._handle_exception_failure(
                item=item,
                action=action,
                ref=ref,
                context=context,
                code=exc.code,
                field=exc.field,
                message=str(exc),
            )
        except Exception as exc:
            return self._handle_exception_failure(
                item=item,
                action=action,
                ref=ref,
                context=context,
                code="UNEXPECTED_ERROR",
                field=None,
                message=str(exc),
            )

    def _execute_item(
        self,
        *,
        item: PlanItem,
        apply_adapter: ApplyAdapterProtocol | None,
        context: _ItemProcessContext,
    ) -> tuple[ExecutionResult | None, tuple[DiagnosticItem, ...]]:
        if apply_adapter is None:
            raise ValueError("Apply adapter is not configured")
        request_spec = apply_adapter.to_request(item)
        boundary_errors: list[DiagnosticItem] = []
        exec_result: ExecutionResult | None = None
        with diagnostic_boundary(
            stage=DiagnosticStage.APPLY,
            catalog=context.catalog,
            sink=boundary_errors,
            record_ref=None,
        ):
            exec_result = self.executor.execute(request_spec)
        return exec_result, tuple(boundary_errors)

    def _handle_boundary_errors(
        self,
        *,
        item: PlanItem,
        action: str,
        ref: RecordRef,
        context: _ItemProcessContext,
        boundary_errors: tuple[DiagnosticItem, ...],
    ) -> _ItemProcessResult:
        first_sys_code: SystemErrorCode | None = None
        for diag in boundary_errors:
            sys_code = context.register_error(ref=ref, action=action, diag=diag)
            if first_sys_code is None:
                first_sys_code = sys_code
        context.add_failed_outcome(
            item=item,
            action=action,
            diagnostics=tuple(boundary_errors),
        )
        item_fatal = context.is_fatal(first_sys_code) if first_sys_code is not None else False
        return _ItemProcessResult(failed_inc=1, item_fatal=item_fatal)

    def _handle_success_item(
        self,
        *,
        item: PlanItem,
        action: str,
        dataset_name: str,
        response_payload: Any | None,
        context: _ItemProcessContext,
    ) -> _ItemProcessResult:
        created_inc = 1 if action == Operation.CREATE else 0
        updated_inc = 1 if action == Operation.UPDATE else 0
        context.sink.on_item_ok(record_ref=item.record_ref, op=action, target_id=item.target_id)
        if context.allow_post_success_side_effects:
            self._sync_identity_index(
                dataset=dataset_name,
                desired_state=item.desired_state,
                response_payload=response_payload,
                source_ref=item.source_ref,
            )
            if context.retention_hook is not None:
                retention_counters = context.retention_hook.on_apply_success(
                    dataset=dataset_name,
                    op=action,
                    source_ref=item.source_ref,
                    secret_fields=list(item.secret_fields or []),
                    secret_lifecycle=item.secret_lifecycle,
                    run_id=context.plan_run_id,
                )
                context.register_retention(dict(retention_counters))
        return _ItemProcessResult(created_inc=created_inc, updated_inc=updated_inc)

    def _handle_single_failure_diag(
        self,
        *,
        item: PlanItem,
        action: str,
        ref: RecordRef,
        context: _ItemProcessContext,
        diag: DiagnosticItem,
        fatal: bool,
    ) -> _ItemProcessResult:
        context.register_error(ref=ref, action=action, diag=diag)
        context.add_failed_outcome(
            item=item,
            action=action,
            diagnostics=(diag,),
        )
        return _ItemProcessResult(failed_inc=1, item_fatal=fatal)

    def _handle_exception_failure(
        self,
        *,
        item: PlanItem,
        action: str,
        ref: RecordRef,
        context: _ItemProcessContext,
        code: str,
        field: str | None,
        message: str,
    ) -> _ItemProcessResult:
        diag = diag_error(
            catalog=context.catalog,
            stage=DiagnosticStage.APPLY,
            code=code,
            field=field,
            message=message,
            record_ref=None,
        )
        return self._handle_single_failure_diag(
            item=item,
            action=action,
            ref=ref,
            context=context,
            diag=diag,
            fatal=False,
        )

    def _sync_identity_index(
        self,
        *,
        dataset: str,
        desired_state: dict[str, Any],
        response_payload: Any | None,
        source_ref: dict[str, Any] | None,
    ) -> None:
        if self.identity_syncer is None:
            return

        id_field = self.identity_syncer.id_field_for(dataset)
        resolved_id = response_payload.get(id_field) if isinstance(response_payload, dict) else None
        if resolved_id is None:
            resolved_id = desired_state.get(id_field)

        key_values: dict[str, Any] = {}
        if isinstance(source_ref, dict):
            key_values.update(source_ref)
        key_values.update(desired_state)

        self.identity_syncer.sync(dataset=dataset, resolved_id=resolved_id, key_values=key_values)
