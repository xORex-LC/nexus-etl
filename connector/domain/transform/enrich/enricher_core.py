"""
Назначение:
    Обогащение данных (кэш/справочники/генераторы).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from connector.domain.models import DiagnosticStage, DiagnosticItem
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.context import error as diag_error, warning as diag_warning
from connector.domain.ports.secrets.provider import SecretStoreProtocol
from connector.domain.transform.common.sink_schema import validate_sink_fields
from connector.domain.transform.core.result import TransformResult, TransformResultBuilder
from connector.domain.dsl.issues import DslIssue
from connector.domain.transform.ids.match_key import MatchKey
from connector.domain.transform_dsl.specs import SinkSpec
from connector.domain.transform.enrich.models import (
    CandidateValue,
    EnrichContext,
    EnrichEvent,
    EnrichOutcome,
    EnrichOperationType,
    MergePolicy,
    OperationReport,
    ResolveHint,
    RunWhenErrors,
)
from connector.domain.transform.enrich.report import EnricherReport
from connector.domain.transform.enrich.resolver import ConflictResolver, MergeEngine, _FieldMutationTracker
from connector.domain.transform_dsl.compilers.enrich import EnricherSpec, EnrichmentOperation

T = TypeVar("T")
D = TypeVar("D")

@dataclass(frozen=True)
class _EnrichOpError:
    """
    Назначение:
        Внутреннее представление ошибки операции enrich без исключений.
    """

    code: str
    message: str
    field: str | None = None


class EnricherCore(Generic[T, D]):
    """
    Назначение:
        Ядро обогащения: исполняет compiled enrich-контракт и сохраняет секреты.

    Границы ответственности:
        - исполняет уже скомпилированные generate/lookup/compute policies;
        - не разбирает raw YAML DSL shape;
        - не содержит dataset-specific special cases.
    """

    def __init__(
        self,
        spec: EnricherSpec[T, D],
        deps: D,
        secret_store: SecretStoreProtocol | None,
        dataset: str,
        catalog: ErrorCatalog,
        sink_spec: SinkSpec | None = None,
        run_id: str | None = None,
    ) -> None:
        self.spec = spec
        self.deps = deps
        self.secret_store = secret_store
        self.dataset = dataset
        self.catalog = catalog
        self.sink_spec = sink_spec
        self.run_id = run_id
        self.conflict_resolver = ConflictResolver()
        self.merge_engine = MergeEngine(spec.authoritative_sources)

    def enrich(self, result: TransformResult[T]) -> TransformResult[T]:
        """
        Назначение:
            Выполнить операции enrich и вернуть обновлённый TransformResult.

        Алгоритм:
            - Создаёт builder и контекст выполнения.
            - Последовательно применяет операции по правилам spec.
            - Сохраняет события/резолв‑подсказки в meta.
            - Пишет секреты в secret_store (если есть).
        """
        if result.row is None:
            return result

        ctx = EnrichContext(dataset=self.dataset, run_id=self.run_id)
        tracker = _FieldMutationTracker()
        builder = result.as_builder()

        if "enrich_events" not in builder.meta:
            builder.meta["enrich_events"] = []
        if "resolve_requests" not in builder.meta:
            builder.meta["resolve_requests"] = []

        summary = EnricherReport()
        if (
            builder.errors
            and self.spec.is_fatal_error is None
            and any(op.run_when_errors == RunWhenErrors.ONLY_NON_FATAL for op in self.spec.operations)
        ):
            builder.add_warning_item(
                self._make_warning(
                    builder,
                    code="ENRICH_FATAL_POLICY_UNSET",
                    message="run_when_errors=ONLY_NON_FATAL requires fatal error classifier",
                )
            )

        for op in self.spec.operations:
            if not self._should_run_operation(op, builder.errors):
                continue
            op_report = self._execute_operation(ctx, builder, op, tracker)
            summary.record(op_report)
            for item in op_report.errors:
                builder.add_error_item(item)
            for item in op_report.warnings:
                builder.add_warning_item(item)
            if op_report.events:
                builder.meta["enrich_events"].extend([event.__dict__ for event in op_report.events])
            if op_report.resolve_hints:
                builder.meta["resolve_requests"].extend([hint.__dict__ for hint in op_report.resolve_hints])
            if self.spec.stop_on_failed and op_report.outcome == EnrichOutcome.FAILED:
                break

        self._store_secrets(builder)

        builder.meta["enrich_summary"] = summary.as_dict()
        return builder.build()

    def _should_run_operation(
        self,
        op: EnrichmentOperation[T, D],
        errors: list[DiagnosticItem],
    ) -> bool:
        if not errors:
            return True
        if op.run_when_errors == RunWhenErrors.ALWAYS:
            return True
        if op.run_when_errors == RunWhenErrors.NEVER:
            return False
        checker = self.spec.is_fatal_error
        if checker is None:
            # TODO(severity): определить fatal/non-fatal через DiagnosticItem.severity.
            return False
        return not any(checker(err) for err in errors)

    def _execute_operation(
        self,
        ctx: EnrichContext,
        builder: TransformResultBuilder[T],
        op: EnrichmentOperation[T, D],
        tracker: _FieldMutationTracker,
    ) -> OperationReport:
        current = builder.build()
        strictness = op.strictness or self.spec.default_strictness
        merge_policy = op.merge_policy or self.spec.default_merge_policy
        if len(op.targets) != 1:
            return self._report_by_policy(
                builder=builder,
                op=op,
                outcome=EnrichOutcome.FAILED,
                code="ENRICH_MULTI_TARGET_UNSUPPORTED",
                message="operation targets must contain exactly one field",
                reason="invalid_operation",
            )

        key_values = {}
        for key in op.required_keys:
            key_values[key] = self.spec.key_registry.resolve(key, current)
        if op.required_keys and any(value is None or value == "" for value in key_values.values()):
            return self._report_by_policy(
                builder=builder,
                op=op,
                outcome=strictness.on_missing_key,
                code="ENRICH_MISSING_KEY",
                message="required key is missing",
                reason="missing_key",
            )

        candidates, op_error = self._collect_candidates(ctx, current, op, key_values)
        if op_error is not None:
            return self._report_by_policy(
                builder=builder,
                op=op,
                outcome=strictness.on_provider_error,
                code=op_error.code,
                message=op_error.message,
                field=op_error.field,
                reason="provider_error",
            )
        if not candidates:
            if op.op_type == EnrichOperationType.COMPUTE and op.missing_error_code:
                return self._report_by_policy(
                    builder=builder,
                    op=op,
                    outcome=strictness.on_provider_error,
                    code=op.missing_error_code,
                    message="computed value is missing",
                    field=op.error_field,
                    reason="missing_value",
                )
            return self._report_by_policy(
                builder=builder,
                op=op,
                outcome=strictness.on_no_candidates,
                code="ENRICH_NO_CANDIDATES",
                message="no candidates available",
                reason="no_candidates",
            )

        decision = self.conflict_resolver.decide(candidates)
        if decision.status == "AMBIGUOUS":
            hint = ResolveHint(
                field=op.targets[0],
                lookup_key=self._build_lookup_key(op, key_values, ctx),
                reason="ambiguous",
                candidates=[self._candidate_ref(cand) for cand in decision.candidates],
                suggested_policy="manual",
            )
            report = self._report_by_policy(
                builder=builder,
                op=op,
                outcome=strictness.on_ambiguous,
                code="ENRICH_AMBIGUOUS",
                message="ambiguous candidates",
                reason="ambiguous",
                details={"candidates_count": len(decision.candidates)},
            )
            report.resolve_hints.append(hint)
            return report

        if decision.status == "NONE":
            return self._report_by_policy(
                builder=builder,
                op=op,
                outcome=strictness.on_no_candidates,
                code="ENRICH_NO_CANDIDATES",
                message="no candidates available",
                reason="no_candidates",
            )

        return self._apply_candidates(builder, op, decision.selected, merge_policy, tracker)

    def _collect_candidates(
        self,
        ctx: EnrichContext,
        result: TransformResult[T],
        op: EnrichmentOperation[T, D],
        key_values: dict[str, Any],
    ) -> tuple[list[CandidateValue], _EnrichOpError | None]:
        if op.op_type == EnrichOperationType.COMPUTE:
            if op.compute is None:
                return [], None
            try:
                values = op.compute(result, self.deps)
            except Exception as exc:  # noqa: BLE001
                return [], _EnrichOpError(
                    code="ENRICH_PROVIDER_ERROR",
                    message=str(exc),
                    field=op.error_field,
                )
            if not values:
                return [], None
            target = op.targets[0]
            if target not in values:
                return [], None
            return [
                CandidateValue(
                    field=target,
                    value=values[target],
                    source="computed",
                    priority=self._priority_for("computed"),
                )
            ], None
        if op.op_type == EnrichOperationType.GENERATE:
            return self._generate_candidates(result, op)

        candidates: list[CandidateValue] = []
        target = op.targets[0]
        for provider in op.providers:
            try:
                fetched = provider.fetch(ctx, result, self.deps, key_values)
            except Exception as exc:  # noqa: BLE001
                return [], _EnrichOpError(
                    code="ENRICH_PROVIDER_ERROR",
                    message=str(exc),
                    field=op.error_field,
                )
            if fetched:
                for candidate in fetched:
                    if candidate.field != target:
                        return [], _EnrichOpError(
                            code="ENRICH_TARGET_MISMATCH",
                            message="candidate field does not match operation target",
                            field=candidate.field,
                        )
                    if candidate.priority is None:
                        candidate = CandidateValue(
                            field=candidate.field,
                            value=candidate.value,
                            source=candidate.source,
                            priority=self._priority_for(candidate.source),
                            confidence=candidate.confidence,
                            evidence=candidate.evidence,
                        )
                    candidates.append(candidate)
        return candidates, None

    def _generate_candidates(
        self,
        result: TransformResult[T],
        op: EnrichmentOperation[T, D],
    ) -> tuple[list[CandidateValue], _EnrichOpError | None]:
        if any(
            value is not None
            for value in (
                op.base_generator,
                op.condition,
                op.append_generator,
                op.conflict_policy,
            )
        ):
            return self._generate_compiled_candidates(result, op)

        if op.generator is None:
            return [], None
        attempts = 0
        max_attempts = max(1, op.max_attempts)
        while attempts < max_attempts:
            candidate = op.generator(result, self.deps)
            if candidate is None or candidate == "":
                if op.missing_error_code:
                    return [], _EnrichOpError(
                        code=op.missing_error_code,
                        message="required value is missing",
                        field=op.error_field,
                    )
                return [], None
            if op.postprocess is not None:
                candidate = op.postprocess(candidate)
            if op.exists is not None:
                existing = op.exists(self.deps, candidate)
                if existing is not None:
                    if op.allow_if and op.allow_if(result, existing):
                        return [
                            CandidateValue(
                                field=op.targets[0],
                                value=candidate,
                                source="generated",
                                priority=self._priority_for("generated"),
                            )
                        ], None
                    candidate = None
                    attempts += 1
                    continue
            return [
                CandidateValue(
                    field=op.targets[0],
                    value=candidate,
                    source="generated",
                    priority=self._priority_for("generated"),
                )
            ], None
        if op.conflict_error_code:
            return [], _EnrichOpError(
                code=op.conflict_error_code,
                message="unable to generate unique value",
                field=op.error_field,
            )
        return [], None

    def _generate_compiled_candidates(
        self,
        result: TransformResult[T],
        op: EnrichmentOperation[T, D],
    ) -> tuple[list[CandidateValue], _EnrichOpError | None]:
        """
        Назначение:
            Исполнить compiled generate-контракт с build/when/then/on_conflict semantics.

        Инварианты:
            - allow_if всегда проверяется раньше on_conflict;
            - retry_with_suffixes строится от base value, а не от предыдущей попытки;
            - then трактуется как append-stage.
        """
        base_candidate = self._build_compiled_base_candidate(result, op)
        if self._is_missing_candidate(base_candidate):
            if op.missing_error_code:
                return [], _EnrichOpError(
                    code=op.missing_error_code,
                    message="required value is missing",
                    field=op.error_field,
                )
            return [], None

        for candidate in self._iter_compiled_candidates(base_candidate, op):
            current = self._apply_postprocess(candidate, op)
            if self._is_missing_candidate(current):
                continue
            if op.exists is None:
                return [self._generated_candidate(op, current)], None

            existing = op.exists(self.deps, current)
            if existing is None:
                return [self._generated_candidate(op, current)], None

            if op.allow_if and op.allow_if(result, existing):
                return [self._generated_candidate(op, current)], None

        if op.conflict_error_code:
            return [], _EnrichOpError(
                code=op.conflict_error_code,
                message="unable to generate unique value",
                field=op.error_field,
            )
        return [], None

    def _build_compiled_base_candidate(
        self,
        result: TransformResult[T],
        op: EnrichmentOperation[T, D],
    ) -> Any:
        if op.base_generator is not None:
            base_value = op.base_generator(result, self.deps)
        elif op.generator is not None:
            base_value = op.generator(result, self.deps)
        else:
            return None

        if self._is_missing_candidate(base_value):
            return base_value

        if op.condition is None or not op.condition(result, self.deps):
            return base_value

        append_value = op.append_generator(result, self.deps) if op.append_generator else None
        if self._is_missing_candidate(append_value):
            return base_value
        return f"{base_value}{append_value}"

    def _iter_compiled_candidates(
        self,
        base_candidate: Any,
        op: EnrichmentOperation[T, D],
    ) -> list[Any]:
        policy = op.conflict_policy
        if policy is None or policy.strategy == "error":
            return [base_candidate]
        if policy.strategy == "retry_with_suffixes":
            return [base_candidate, *[f"{base_candidate}{suffix}" for suffix in policy.suffixes]]
        return [base_candidate]

    def _generated_candidate(self, op: EnrichmentOperation[T, D], value: Any) -> CandidateValue:
        return CandidateValue(
            field=op.targets[0],
            value=value,
            source="generated",
            priority=self._priority_for("generated"),
        )

    def _apply_postprocess(self, candidate: Any, op: EnrichmentOperation[T, D]) -> Any:
        if op.postprocess is None:
            return candidate
        return op.postprocess(candidate)

    def _is_missing_candidate(self, value: Any) -> bool:
        return value is None or value == ""

    def _apply_candidates(
        self,
        builder: TransformResultBuilder[T],
        op: EnrichmentOperation[T, D],
        candidate: CandidateValue | None,
        merge_policy: MergePolicy,
        tracker: _FieldMutationTracker,
    ) -> OperationReport:
        if candidate is None:
            return OperationReport(op=op.name, outcome=EnrichOutcome.SKIPPED)
        events: list[EnrichEvent] = []
        for target_field in op.targets:
            current = self._get_field_value(builder, target_field)
            if tracker.has_writer(target_field):
                if not self.merge_engine.should_apply(current, candidate, merge_policy):
                    events.append(
                        EnrichEvent(
                            op=op.name,
                            field=target_field,
                            before=current,
                            after=current,
                            source=candidate.source,
                            decision="conflict_skipped",
                            outcome=EnrichOutcome.SKIPPED.value,
                        )
                    )
                    continue
                decision_label = "overridden_previous_op"
            else:
                decision_label = "applied"
            if not self.merge_engine.should_apply(current, candidate, merge_policy):
                events.append(
                    EnrichEvent(
                        op=op.name,
                        field=target_field,
                        before=current,
                        after=current,
                        source=candidate.source,
                        decision="policy_skip",
                        outcome=EnrichOutcome.SKIPPED.value,
                    )
                )
                continue
            sink_field = self._sink_field_name(target_field)
            sink_issues = self._validate_sink_target(sink_field, candidate.value)
            if sink_issues:
                issue = sink_issues[0]
                return self._report_by_policy(
                    builder=builder,
                    op=op,
                    outcome=(op.strictness or self.spec.default_strictness).on_provider_error,
                    code=issue.code,
                    message=issue.message,
                    field=issue.field or sink_field,
                    reason="sink_validation",
                )
            self._set_field_value(builder, target_field, candidate.value)
            tracker.register(target_field, op.name)
            events.append(
                EnrichEvent(
                    op=op.name,
                    field=target_field,
                    before=current,
                    after=candidate.value,
                    source=candidate.source,
                    decision=decision_label,
                    outcome=EnrichOutcome.APPLIED.value,
                )
            )
        outcome = EnrichOutcome.APPLIED if any(event.outcome == EnrichOutcome.APPLIED.value for event in events) else EnrichOutcome.SKIPPED
        return OperationReport(op=op.name, outcome=outcome, events=events)

    def _get_field_value(self, builder: TransformResultBuilder[T], field: str) -> Any:
        if field == "match_key":
            return builder.match_key.value if builder.match_key else None
        if field.startswith("secret:"):
            key = field.split("secret:", 1)[1]
            return builder.secret_candidates.get(key)
        row = builder.row
        if row is None:
            return None
        return row.get(field) if isinstance(row, dict) else getattr(row, field, None)

    def _set_field_value(self, builder: TransformResultBuilder[T], field: str, value: Any) -> None:
        if field == "match_key":
            builder.set_match_key(MatchKey(str(value)))
            return
        if field.startswith("secret:"):
            key = field.split("secret:", 1)[1]
            if value is None:
                return
            builder.set_secret_candidate(key, str(value))
            return
        if builder.row is None:
            return
        if isinstance(builder.row, dict):
            builder.row[field] = value
        else:
            setattr(builder.row, field, value)

    def _build_lookup_key(
        self,
        op: EnrichmentOperation[T, D],
        values: dict[str, Any],
        ctx: EnrichContext,
    ) -> dict[str, Any]:
        return {
            "keys": dict(values),
            "strength": "strong",
            "as_of": ctx.as_of,
        }

    def _candidate_ref(self, candidate: CandidateValue) -> dict[str, Any]:
        target_id = None
        identity_key = None
        if candidate.evidence:
            target_id = candidate.evidence.get("target_id")
            identity_key = candidate.evidence.get("identity_key")
        return {
            "source": candidate.source,
            "identity_key": identity_key,
            "target_id": target_id,
            "evidence": candidate.evidence,
        }

    def _report_by_policy(
        self,
        builder: TransformResultBuilder[T],
        op: EnrichmentOperation[T, D],
        outcome: str,
        code: str,
        message: str,
        field: str | None = None,
        *,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> OperationReport:
        resolved = outcome if isinstance(outcome, EnrichOutcome) else EnrichOutcome(outcome)
        errors: list[DiagnosticItem] = []
        warnings: list[DiagnosticItem] = []
        resolved_field = field or op.error_field or (op.targets[0] if op.targets else None)
        resolved_details = {
            "rule": op.name,
            "target": op.targets[0] if op.targets else None,
        }
        if reason is not None:
            resolved_details["reason"] = reason
        if details:
            resolved_details.update(details)
        if resolved == EnrichOutcome.FAILED:
            errors.append(
                self._make_error(
                    builder,
                    code=code,
                    message=message,
                    field=resolved_field,
                    details=resolved_details,
                )
            )
        elif resolved in (EnrichOutcome.WARNED, EnrichOutcome.NEEDS_RESOLVE):
            warnings.append(
                self._make_warning(
                    builder,
                    code=code,
                    message=message,
                    field=resolved_field,
                    details=resolved_details,
                )
            )
        return OperationReport(op=op.name, outcome=resolved, warnings=warnings, errors=errors)

    def _make_error(
        self,
        builder: TransformResultBuilder[T],
        code: str,
        message: str,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> DiagnosticItem:
        return diag_error(
            stage=DiagnosticStage.ENRICH,
            code=code,
            field=field,
            message=message,
            record_ref=builder.row_ref,
            details=details,
            catalog=self.catalog,
        )

    def _make_warning(
        self,
        builder: TransformResultBuilder[T],
        code: str,
        message: str,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> DiagnosticItem:
        return diag_warning(
            stage=DiagnosticStage.ENRICH,
            code=code,
            field=field,
            message=message,
            record_ref=builder.row_ref,
            details=details,
            catalog=self.catalog,
        )

    def _priority_for(self, source: str) -> int:
        if source in self.spec.source_priorities:
            return self.spec.source_priorities[source]
        return 0

    def _store_secrets(
        self,
        builder: TransformResultBuilder[T],
    ) -> None:
        if not builder.secret_candidates:
            return
        if builder.match_key is None:
            builder.add_error_item(
                self._make_error(
                    builder,
                    code="SECRET_MATCH_KEY_MISSING",
                    message="match_key is required to store secrets",
                    field="matchKey",
                )
            )
            return
        if self.secret_store is not None:
            try:
                self.secret_store.put_many(
                    dataset=self.dataset,
                    match_key=builder.match_key.value,
                    secrets=builder.secret_candidates,
                    run_id=self.run_id,
                )
            except Exception as exc:  # noqa: BLE001
                _ = exc
                builder.add_error_item(
                    self._make_error(
                        builder,
                        code="SECRET_STORE_ERROR",
                        message="failed to store secrets",
                    )
                )

        secret_fields = list(builder.secret_candidates.keys())
        builder.meta["secret_fields"] = secret_fields
        self._clear_secret_fields(builder, secret_fields)
        builder.secret_candidates = {}

    def _clear_secret_fields(
        self,
        builder: TransformResultBuilder[T],
        secret_fields: list[str],
    ) -> None:
        row = builder.row
        if row is None:
            return
        for field in secret_fields:
            if isinstance(row, dict):
                if field in row:
                    row[field] = None
                continue
            if hasattr(row, field):
                setattr(row, field, None)

    def _sink_field_name(self, target_field: str) -> str:
        if target_field.startswith("secret:"):
            return target_field.split("secret:", 1)[1]
        return target_field

    def _validate_sink_target(self, sink_field: str, value: Any) -> list[DslIssue]:
        if self.sink_spec is None:
            return []
        return validate_sink_fields(
            {sink_field: value},
            self.sink_spec,
            fields=(sink_field,),
            check_types=True,
        )


__all__ = ["EnricherCore"]
