from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Generic, Iterable, Protocol, TypeVar

from connector.domain.models import DiagnosticStage, ValidationErrorItem
from connector.domain.ports.secrets import SecretStoreProtocol
from connector.domain.transform.match_key import MatchKey
from connector.domain.transform.enricher_report import EnricherReport
from connector.domain.transform.result import TransformResult

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
    OVERRIDE_IF_INVALID = "override_if_invalid"
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
    priority: int = 0
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


@dataclass(frozen=True)
class OperationReport:
    """
    Назначение:
        Результат выполнения одной операции enrich.
    """

    op: str
    outcome: EnrichOutcome
    events: list[EnrichEvent] = field(default_factory=list)
    resolve_hints: list[ResolveHint] = field(default_factory=list)
    warnings: list[ValidationErrorItem] = field(default_factory=list)
    errors: list[ValidationErrorItem] = field(default_factory=list)


@dataclass(frozen=True)
class EnrichContext:
    """
    Назначение:
        Контекст выполнения enrich (run-level).
    """

    dataset: str
    run_id: str | None = None
    as_of: Any | None = None


class EnrichOperationError(Exception):
    """
    Назначение:
        Управляемая ошибка внутри операции enrich с кодом.
    """

    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


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
    is_fatal_error: Callable[[ValidationErrorItem], bool] | None = None


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
            key=lambda cand: (cand.priority, -(cand.confidence or 0.0)),
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
        if policy.mode == MergeMode.RECOMPUTE_ALWAYS:
            return True
        if policy.mode == MergeMode.NEVER_OVERRIDE:
            return False
        if policy.mode == MergeMode.OVERRIDE_IF_AUTHORITATIVE:
            return candidate.source in self.authoritative_sources
        if policy.mode == MergeMode.OVERRIDE_IF_INVALID:
            return current is None or current == ""
        return current is None or current == ""


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
        run_id: str | None = None,
    ) -> None:
        self.spec = spec
        self.deps = deps
        self.secret_store = secret_store
        self.dataset = dataset
        self.run_id = run_id
        self.conflict_resolver = ConflictResolver()
        self.merge_engine = MergeEngine(spec.authoritative_sources)

    def enrich(self, result: TransformResult[T]) -> TransformResult[T]:
        if result.row is None:
            return result

        ctx = EnrichContext(dataset=self.dataset, run_id=self.run_id)
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []
        tracker = _FieldMutationTracker()

        if "enrich_events" not in result.meta:
            result.meta["enrich_events"] = []
        if "resolve_requests" not in result.meta:
            result.meta["resolve_requests"] = []
        summary = EnricherReport()

        for op in self.spec.operations:
            if not self._should_run_operation(op, result.errors):
                continue
            op_report = self._execute_operation(ctx, result, op, tracker)
            summary.record(op_report)
            errors.extend(op_report.errors)
            warnings.extend(op_report.warnings)
            if op_report.events:
                result.meta["enrich_events"].extend([event.__dict__ for event in op_report.events])
            if op_report.resolve_hints:
                result.meta["resolve_requests"].extend([hint.__dict__ for hint in op_report.resolve_hints])

        self._store_secrets(result, errors, warnings)

        result.errors = [*result.errors, *errors]
        result.warnings = [*result.warnings, *warnings]
        result.meta["enrich_summary"] = summary.as_dict()
        return result

    def _should_run_operation(
        self,
        op: EnrichmentOperation[T, D],
        errors: list[ValidationErrorItem],
    ) -> bool:
        if not errors:
            return True
        if op.run_when_errors == RunWhenErrors.ALWAYS:
            return True
        if op.run_when_errors == RunWhenErrors.NEVER:
            return False
        checker = self.spec.is_fatal_error
        if checker is None:
            # TODO(severity): определить fatal/non-fatal через ValidationErrorItem.severity.
            return False
        return not any(checker(err) for err in errors)

    def _execute_operation(
        self,
        ctx: EnrichContext,
        result: TransformResult[T],
        op: EnrichmentOperation[T, D],
        tracker: _FieldMutationTracker,
    ) -> OperationReport:
        strictness = op.strictness or self.spec.default_strictness
        merge_policy = op.merge_policy or self.spec.default_merge_policy

        key_values = {}
        for key in op.required_keys:
            key_values[key] = self.spec.key_registry.resolve(key, result)
        if op.required_keys and any(value is None or value == "" for value in key_values.values()):
            return self._report_by_policy(
                op=op,
                outcome=strictness.on_missing_key,
                code="ENRICH_MISSING_KEY",
                message="required key is missing",
            )

        try:
            candidates = self._collect_candidates(ctx, result, op, key_values)
        except EnrichOperationError as exc:
            return self._report_by_policy(
                op=op,
                outcome=strictness.on_provider_error,
                code=exc.code,
                message=exc.message,
                field=exc.field,
            )
        except Exception as exc:  # noqa: BLE001
            return self._report_by_policy(
                op=op,
                outcome=strictness.on_provider_error,
                code="ENRICH_PROVIDER_ERROR",
                message=str(exc),
            )

        if not candidates:
            return self._report_by_policy(
                op=op,
                outcome=strictness.on_no_candidates,
                code="ENRICH_NO_CANDIDATES",
                message="no candidates available",
            )

        decision = self.conflict_resolver.decide(candidates)
        if decision.status == "AMBIGUOUS":
            hint = ResolveHint(
                field=op.targets[0],
                lookup_key=self._build_lookup_key(op, key_values),
                reason="ambiguous",
                candidates=[self._candidate_ref(cand) for cand in decision.candidates],
                suggested_policy="manual",
            )
            report = self._report_by_policy(
                op=op,
                outcome=strictness.on_ambiguous,
                code="ENRICH_AMBIGUOUS",
                message="ambiguous candidates",
            )
            report.resolve_hints.append(hint)
            return report

        if decision.status == "NONE":
            return self._report_by_policy(
                op=op,
                outcome=strictness.on_no_candidates,
                code="ENRICH_NO_CANDIDATES",
                message="no candidates available",
            )

        return self._apply_candidates(result, op, decision.selected, merge_policy, tracker)

    def _collect_candidates(
        self,
        ctx: EnrichContext,
        result: TransformResult[T],
        op: EnrichmentOperation[T, D],
        key_values: dict[str, Any],
    ) -> list[CandidateValue]:
        if op.op_type == EnrichOperationType.COMPUTE:
            if op.compute is None:
                return []
            values = op.compute(result, self.deps)
            if not values:
                return []
            return [
                CandidateValue(
                    field=field,
                    value=value,
                    source="computed",
                    priority=self._priority_for("computed"),
                )
                for field, value in values.items()
            ]
        if op.op_type == EnrichOperationType.GENERATE:
            return self._generate_candidates(result, op)

        candidates: list[CandidateValue] = []
        for provider in op.providers:
            fetched = provider.fetch(ctx, result, self.deps, key_values)
            if fetched:
                for candidate in fetched:
                    if candidate.priority == 0:
                        candidate = CandidateValue(
                            field=candidate.field,
                            value=candidate.value,
                            source=candidate.source,
                            priority=self._priority_for(candidate.source),
                            confidence=candidate.confidence,
                            evidence=candidate.evidence,
                        )
                    candidates.append(candidate)
        return candidates

    def _generate_candidates(
        self,
        result: TransformResult[T],
        op: EnrichmentOperation[T, D],
    ) -> list[CandidateValue]:
        if op.generator is None:
            return []
        attempts = 0
        max_attempts = max(1, op.max_attempts)
        while attempts < max_attempts:
            candidate = op.generator(result, self.deps)
            if candidate is None or candidate == "":
                if op.missing_error_code:
                    raise EnrichOperationError(
                        code=op.missing_error_code,
                        message="required value is missing",
                        field=op.error_field,
                    )
                return []
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
                        ]
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
            ]
        if op.conflict_error_code:
            raise EnrichOperationError(
                code=op.conflict_error_code,
                message="unable to generate unique value",
                field=op.error_field,
            )
        return []

    def _apply_candidates(
        self,
        result: TransformResult[T],
        op: EnrichmentOperation[T, D],
        candidate: CandidateValue | None,
        merge_policy: MergePolicy,
        tracker: _FieldMutationTracker,
    ) -> OperationReport:
        if candidate is None:
            return OperationReport(op=op.name, outcome=EnrichOutcome.SKIPPED)
        events: list[EnrichEvent] = []
        for field in op.targets:
            current = self._get_field_value(result, field)
            if tracker.has_writer(field):
                if not self.merge_engine.should_apply(current, candidate, merge_policy):
                    events.append(
                        EnrichEvent(
                            op=op.name,
                            field=field,
                            before=current,
                            after=current,
                            source=candidate.source,
                            decision="conflict_skipped",
                            outcome=EnrichOutcome.SKIPPED.value,
                        )
                    )
                    continue
            if not self.merge_engine.should_apply(current, candidate, merge_policy):
                events.append(
                    EnrichEvent(
                        op=op.name,
                        field=field,
                        before=current,
                        after=current,
                        source=candidate.source,
                        decision="policy_skip",
                        outcome=EnrichOutcome.SKIPPED.value,
                    )
                )
                continue
            self._set_field_value(result, field, candidate.value)
            tracker.register(field, op.name)
            events.append(
                EnrichEvent(
                    op=op.name,
                    field=field,
                    before=current,
                    after=candidate.value,
                    source=candidate.source,
                    decision="applied",
                    outcome=EnrichOutcome.APPLIED.value,
                )
            )
        outcome = EnrichOutcome.APPLIED if any(event.outcome == EnrichOutcome.APPLIED.value for event in events) else EnrichOutcome.SKIPPED
        return OperationReport(op=op.name, outcome=outcome, events=events)

    def _get_field_value(self, result: TransformResult[T], field: str) -> Any:
        if field == "match_key":
            return result.match_key.value if result.match_key else None
        if field.startswith("secret:"):
            key = field.split("secret:", 1)[1]
            return result.secret_candidates.get(key)
        row = result.row
        return getattr(row, field, None) if row is not None else None

    def _set_field_value(self, result: TransformResult[T], field: str, value: Any) -> None:
        if field == "match_key":
            result.match_key = MatchKey(str(value))
            return
        if field.startswith("secret:"):
            key = field.split("secret:", 1)[1]
            if value is None:
                return
            result.secret_candidates[key] = str(value)
            return
        if result.row is None:
            return
        setattr(result.row, field, value)

    def _build_lookup_key(self, op: EnrichmentOperation[T, D], values: dict[str, Any]) -> dict[str, Any]:
        primary = op.required_keys[0] if op.required_keys else "unknown"
        return {"name": primary, "value": values.get(primary), "strength": "strong"}

    def _candidate_ref(self, candidate: CandidateValue) -> dict[str, Any]:
        return {
            "source": candidate.source,
            "identity_key": None,
            "target_id": None,
            "evidence": candidate.evidence,
        }

    def _report_by_policy(
        self,
        op: EnrichmentOperation[T, D],
        outcome: str,
        code: str,
        message: str,
        field: str | None = None,
    ) -> OperationReport:
        resolved = outcome if isinstance(outcome, EnrichOutcome) else EnrichOutcome(outcome)
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []
        if resolved == EnrichOutcome.FAILED:
            errors.append(self._make_error(code=code, message=message, field=field))
        elif resolved in (EnrichOutcome.WARNED, EnrichOutcome.NEEDS_RESOLVE):
            warnings.append(self._make_error(code=code, message=message, field=field))
        return OperationReport(op=op.name, outcome=resolved, warnings=warnings, errors=errors)

    def _make_error(self, code: str, message: str, field: str | None = None) -> ValidationErrorItem:
        return ValidationErrorItem(
            stage=DiagnosticStage.ENRICH,
            code=code,
            field=field,
            message=message,
        )

    def _priority_for(self, source: str) -> int:
        if source in self.spec.source_priorities:
            return self.spec.source_priorities[source]
        return 0

    def _store_secrets(
        self,
        result: TransformResult[T],
        errors: list[ValidationErrorItem],
        warnings: list[ValidationErrorItem],
    ) -> None:
        if not result.secret_candidates:
            return
        if self.secret_store is None:
            return
        if result.match_key is None:
            errors.append(
                ValidationErrorItem(
                    stage=DiagnosticStage.ENRICH,
                    code="MATCH_KEY_MISSING",
                    field="matchKey",
                    message="match_key is required to store secrets",
                )
            )
            return
        try:
            self.secret_store.put_many(
                dataset=self.dataset,
                match_key=result.match_key.value,
                secrets=result.secret_candidates,
                run_id=self.run_id,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(
                ValidationErrorItem(
                    stage=DiagnosticStage.ENRICH,
                    code="SECRET_STORE_ERROR",
                    field=None,
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
    "EnrichOperationError",
]
