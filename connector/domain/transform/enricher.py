from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Generic, Protocol, TypeVar

from connector.domain.models import DiagnosticStage, DiagnosticItem
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.context import error as diag_error, warning as diag_warning
from connector.domain.ports.secrets import SecretStoreProtocol
from connector.domain.transform.match_key import MatchKey
from connector.domain.transform.enricher_report import EnricherReport
from connector.domain.transform.result import TransformResult, TransformResultBuilder

T = TypeVar("T")
D = TypeVar("D")


class EnrichOutcome(str, Enum):
    """
    Назначение:
        Стандартные исходы операции enrich.
    """

    APPLIED = "APPLIED"
    SKIPPED = "SKIPPED"
    WARNED = "WARNED"
    FAILED = "FAILED"
    NEEDS_RESOLVE = "NEEDS_RESOLVE"


class RunWhenErrors(str, Enum):
    """
    Назначение:
        Политика запуска операции при наличии ошибок до enrich.
    """

    NEVER = "NEVER"
    ONLY_NON_FATAL = "ONLY_NON_FATAL"
    ALWAYS = "ALWAYS"


class EnrichOperationType(str, Enum):
    """
    Назначение:
        Тип операции enrich.
    """

    COMPUTE = "COMPUTE"
    FILL_MISSING = "FILL_MISSING"
    LOOKUP = "LOOKUP"
    GENERATE = "GENERATE"
    MEMBERSHIP = "MEMBERSHIP"


class MergeMode(str, Enum):
    """
    Назначение:
        Режим слияния значений поля.
    """

    FILL_ONLY_IF_EMPTY = "fill_only_if_empty"
    RECOMPUTE_ALWAYS = "recompute_always"
    OVERRIDE_IF_EMPTY = "override_if_empty"
    OVERRIDE_IF_AUTHORITATIVE = "override_if_authoritative"
    NEVER_OVERRIDE = "never_override"


@dataclass(frozen=True)
class MergePolicy:
    """
    Назначение:
        Политика слияния значений поля.
    """

    mode: str = MergeMode.FILL_ONLY_IF_EMPTY


@dataclass(frozen=True)
class StrictnessPolicy:
    """
    Назначение:
        Политика реакции на ключевые ситуации enrich.
    """

    on_missing_key: str = EnrichOutcome.SKIPPED
    on_no_candidates: str = EnrichOutcome.SKIPPED
    on_ambiguous: str = EnrichOutcome.NEEDS_RESOLVE
    on_provider_error: str = EnrichOutcome.WARNED


@dataclass(frozen=True)
class CandidateValue:
    """
    Назначение:
        Унифицированное представление кандидата для enrich.
    """

    field: str
    value: Any
    source: str
    priority: int | None = None
    confidence: float | None = None
    evidence: dict[str, Any] | None = None


@dataclass(frozen=True)
class CandidateDecision:
    """
    Назначение:
        Результат разрешения конфликтов кандидатов.
    """

    status: str
    selected: CandidateValue | None
    candidates: list[CandidateValue]
    reason: str | None = None


@dataclass(frozen=True)
class EnrichEvent:
    """
    Назначение:
        Аудит изменения поля в enrich.
    """

    op: str
    field: str
    before: Any
    after: Any
    source: str
    decision: str
    outcome: str


@dataclass(frozen=True)
class ResolveHint:
    """
    Назначение:
        Подсказка для resolver при неоднозначности.
    """

    field: str
    lookup_key: dict[str, Any]
    reason: str
    candidates: list[dict[str, Any]]
    suggested_policy: str | None = None


@dataclass
class OperationReport:
    """
    Назначение:
        Результат выполнения одной операции enrich.
    """

    op: str
    outcome: EnrichOutcome
    events: list[EnrichEvent] = field(default_factory=list)
    resolve_hints: list[ResolveHint] = field(default_factory=list)
    warnings: list[DiagnosticItem] = field(default_factory=list)
    errors: list[DiagnosticItem] = field(default_factory=list)


@dataclass(frozen=True)
class EnrichContext:
    """
    Назначение:
        Контекст выполнения enrich (run-level).
    """

    dataset: str
    run_id: str | None = None
    as_of: Any | None = None


@dataclass(frozen=True)
class _EnrichOpError:
    """
    Назначение:
        Внутреннее представление ошибки операции enrich без исключений.
    """

    code: str
    message: str
    field: str | None = None


class CandidateProvider(Protocol, Generic[T, D]):
    """
    Назначение:
        Контракт источника кандидатов для enrich.
    """

    name: str

    def fetch(
        self,
        ctx: EnrichContext,
        result: TransformResult[T],
        deps: D,
        key_values: dict[str, Any],
    ) -> list[CandidateValue]:
        ...


KeyBuilder = Callable[[TransformResult[T]], Any]


@dataclass(frozen=True)
class KeyRegistry(Generic[T]):
    """
    Назначение:
        Реестр ключей enrich (key_name -> builder).
    """

    builders: dict[str, KeyBuilder[T]]

    def resolve(self, key: str, result: TransformResult[T]) -> Any | None:
        builder = self.builders.get(key)
        if builder is None:
            if result.row is not None and hasattr(result.row, key):
                return getattr(result.row, key)
            if result.meta:
                return result.meta.get(key)
            return None
        return builder(result)


@dataclass(frozen=True)
class EnrichmentOperation(Generic[T, D]):
    """
    Назначение:
        Декларативная спецификация операции enrich.
    """

    name: str
    op_type: EnrichOperationType
    targets: tuple[str, ...]
    required_keys: tuple[str, ...] = ()
    providers: tuple[CandidateProvider[T, D], ...] = ()
    merge_policy: MergePolicy | None = None
    strictness: StrictnessPolicy | None = None
    run_when_errors: RunWhenErrors = RunWhenErrors.NEVER
    compute: Callable[[TransformResult[T], D], dict[str, Any] | None] | None = None
    generator: Callable[[TransformResult[T], D], Any] | None = None
    exists: Callable[[D, Any], Any] | None = None
    allow_if: Callable[[TransformResult[T], Any], bool] | None = None
    max_attempts: int = 3
    postprocess: Callable[[Any], Any] | None = None
    missing_error_code: str | None = None
    conflict_error_code: str | None = None
    error_field: str | None = None


@dataclass(frozen=True)
class EnricherSpec(Generic[T, D]):
    """
    Назначение:
        Спецификация enrich для датасета.
    """

    operations: tuple[EnrichmentOperation[T, D], ...]
    key_registry: KeyRegistry[T]
    field_semantics: dict[str, str] = field(default_factory=dict)
    source_priorities: dict[str, int] = field(default_factory=dict)
    default_merge_policy: MergePolicy = MergePolicy()
    default_strictness: StrictnessPolicy = StrictnessPolicy()
    authoritative_sources: set[str] = field(default_factory=lambda: {"sink_cache"})
    is_fatal_error: Callable[[DiagnosticItem], bool] | None = None
    stop_on_failed: bool = False


class _FieldMutationTracker:
    """
    Назначение:
        Отслеживание конфликтов между операциями по одному полю.
    """

    def __init__(self) -> None:
        self._writers: dict[str, str] = {}

    def has_writer(self, field: str) -> bool:
        return field in self._writers

    def register(self, field: str, op_name: str) -> None:
        self._writers[field] = op_name

    def last_writer(self, field: str) -> str | None:
        return self._writers.get(field)


class ConflictResolver:
    """
    Назначение:
        Разрешение конфликтов между кандидатами.
    """

    def decide(self, candidates: list[CandidateValue]) -> CandidateDecision:
        if not candidates:
            return CandidateDecision(status="NONE", selected=None, candidates=[], reason="no_candidates")
        if len(candidates) == 1:
            return CandidateDecision(status="SELECTED", selected=candidates[0], candidates=candidates)
        sorted_candidates = sorted(
            candidates,
            key=lambda cand: (
                -((cand.priority if cand.priority is not None else 0)),
                -(cand.confidence or 0.0),
            ),
        )
        top = sorted_candidates[0]
        if len(sorted_candidates) > 1:
            second = sorted_candidates[1]
            if top.priority == second.priority and (top.confidence or 0.0) == (second.confidence or 0.0):
                return CandidateDecision(status="AMBIGUOUS", selected=None, candidates=sorted_candidates)
        return CandidateDecision(status="SELECTED", selected=top, candidates=sorted_candidates)


class MergeEngine:
    """
    Назначение:
        Применение merge-политики к полю.
    """

    def __init__(self, authoritative_sources: set[str]) -> None:
        self.authoritative_sources = authoritative_sources

    def should_apply(self, current: Any, candidate: CandidateValue, policy: MergePolicy) -> bool:
        handlers = {
            MergeMode.RECOMPUTE_ALWAYS: lambda: True,
            MergeMode.NEVER_OVERRIDE: lambda: False,
            MergeMode.OVERRIDE_IF_AUTHORITATIVE: lambda: candidate.source in self.authoritative_sources,
            MergeMode.OVERRIDE_IF_EMPTY: lambda: current is None or current == "",
        }
        handler = handlers.get(policy.mode, handlers[MergeMode.OVERRIDE_IF_EMPTY])
        return handler()


class Enricher(Generic[T, D]):
    """
    Назначение:
        Ядро обогащения: применяет операции и сохраняет секреты.
    """

    def __init__(
        self,
        spec: EnricherSpec[T, D],
        deps: D,
        secret_store: SecretStoreProtocol | None,
        dataset: str,
        catalog: ErrorCatalog,
        run_id: str | None = None,
    ) -> None:
        self.spec = spec
        self.deps = deps
        self.secret_store = secret_store
        self.dataset = dataset
        self.catalog = catalog
        self.run_id = run_id
        self.conflict_resolver = ConflictResolver()
        self.merge_engine = MergeEngine(spec.authoritative_sources)

    def enrich(self, result: TransformResult[T]) -> TransformResult[T]:
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
                )
            return self._report_by_policy(
                builder=builder,
                op=op,
                outcome=strictness.on_no_candidates,
                code="ENRICH_NO_CANDIDATES",
                message="no candidates available",
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
            fetched = provider.fetch(ctx, result, self.deps, key_values)
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
        return getattr(row, field, None) if row is not None else None

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
    ) -> OperationReport:
        resolved = outcome if isinstance(outcome, EnrichOutcome) else EnrichOutcome(outcome)
        errors: list[DiagnosticItem] = []
        warnings: list[DiagnosticItem] = []
        if resolved == EnrichOutcome.FAILED:
            errors.append(self._make_error(builder, code=code, message=message, field=field))
        elif resolved in (EnrichOutcome.WARNED, EnrichOutcome.NEEDS_RESOLVE):
            warnings.append(self._make_warning(builder, code=code, message=message, field=field))
        return OperationReport(op=op.name, outcome=resolved, warnings=warnings, errors=errors)

    def _make_error(
        self,
        builder: TransformResultBuilder[T],
        code: str,
        message: str,
        field: str | None = None,
    ) -> DiagnosticItem:
        return diag_error(
            stage=DiagnosticStage.ENRICH,
            code=code,
            field=field,
            message=message,
            record_ref=builder.row_ref,
            catalog=self.catalog,
        )

    def _make_warning(
        self,
        builder: TransformResultBuilder[T],
        code: str,
        message: str,
        field: str | None = None,
    ) -> DiagnosticItem:
        return diag_warning(
            stage=DiagnosticStage.ENRICH,
            code=code,
            field=field,
            message=message,
            record_ref=builder.row_ref,
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
        if self.secret_store is None:
            return
        if builder.match_key is None:
            builder.add_error_item(
                self._make_error(
                    builder,
                    code="MATCH_KEY_MISSING",
                    message="match_key is required to store secrets",
                    field="matchKey",
                )
            )
            return
        try:
            self.secret_store.put_many(
                dataset=self.dataset,
                match_key=builder.match_key.value,
                secrets=builder.secret_candidates,
                run_id=self.run_id,
            )
        except Exception as exc:  # noqa: BLE001
            builder.add_error_item(
                self._make_error(
                    builder,
                    code="SECRET_STORE_ERROR",
                    message=str(exc),
                )
            )


__all__ = [
    "CandidateProvider",
    "CandidateValue",
    "EnrichOutcome",
    "Enricher",
    "EnricherSpec",
    "EnrichmentOperation",
    "EnrichOperationType",
    "EnrichContext",
    "MergePolicy",
    "MergeMode",
    "RunWhenErrors",
    "StrictnessPolicy",
    "ResolveHint",
    "EnrichEvent",
    "OperationReport",
    "KeyRegistry",
]
