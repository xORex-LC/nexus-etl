"""
Назначение:
    EnricherDsl: компиляция EnrichSpec в EnricherSpec (compiled).
    Compiled models: EnricherSpec, EnrichmentOperation, KeyRegistry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.models import DiagnosticItem
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.enrich.models import (
    CandidateValue,
    EnrichOperationType,
    EnrichOutcome,
    MergeMode,
    MergePolicy,
    RunWhenErrors,
    StrictnessPolicy,
)
from connector.domain.transform.enrich.providers import CandidateProvider
from connector.domain.transform.providers import ProviderGateway
from connector.domain.dsl.engine import TransformationEngine
from connector.domain.dsl.helpers import apply_ops
from connector.domain.dsl.issues import DslLoadError, DslSeverity
from connector.domain.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.dsl.specs import OperationCall
from connector.domain.transform_dsl.build_options import EnrichDslBuildOptions
from connector.domain.transform_dsl.specs import EnrichRule, EnrichSpec, MatchKeySpec, SecretsSpec
from connector.domain.transform.common.values import read_value_path
from connector.domain.transform.ids.match_key import MatchKeyError, build_delimited_match_key

T = TypeVar("T")
D = TypeVar("D")

KeyBuilder = Callable[[TransformResult[T]], Any]


# ========== COMPILED MODELS ==========


@dataclass(frozen=True)
class KeyRegistry(Generic[T]):
    """
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
    Спецификация enrich для датасета (compiled).
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


# ========== COMPILER ==========


class EnricherDsl:
    """
    Назначение/ответственность:
        Компилятор Enrich DSL -> EnricherSpec (StageDsl).
    """

    def __init__(
        self,
        *,
        registry: OperationRegistry | None = None,
        providers: ProviderGateway | None = None,
        options: EnrichDslBuildOptions | None = None,
    ) -> None:
        if registry is None:
            registry = OperationRegistry()
            register_core_ops(registry)
        if providers is None:
            providers = ProviderGateway.with_defaults()
        self.registry = registry
        self.providers = providers
        self.options = options

    def compile(self, spec: EnrichSpec) -> EnricherSpec:
        """
        Назначение:
            Скомпилировать EnrichSpec в EnricherSpec.
        """
        options = self.options or EnrichDslBuildOptions()
        if options.fail_on_unknown_ops:
            self._validate_ops_known(spec)
        try:
            return build_enricher_spec_from_dsl(
                spec,
                registry=self.registry,
                providers=self.providers,
                options=self.options,
            )
        except DslLoadError:
            raise
        except Exception as exc:
            raise DslLoadError(
                code="ENRICH_DSL_COMPILE_INVALID",
                message=f"Failed to compile enrich DSL: {exc}",
            ) from exc

    def _validate_ops_known(self, spec: EnrichSpec) -> None:
        for rule in (*spec.enrich.generate, *spec.enrich.lookup):
            for op_call in rule.ops:
                if self.registry.get(op_call.op) is None:
                    raise DslLoadError(
                        code="DSL_OP_UNKNOWN",
                        message=f"Unknown operation '{op_call.op}' in enrich rule '{rule.name}'",
                        details={"op": op_call.op, "rule": rule.name},
                    )
            if isinstance(rule.allow_if, OperationCall):
                if self.registry.get(rule.allow_if.op) is None:
                    raise DslLoadError(
                        code="DSL_OP_UNKNOWN",
                        message=f"Unknown operation '{rule.allow_if.op}' in enrich rule '{rule.name}' allow_if",
                        details={"op": rule.allow_if.op, "rule": rule.name},
                    )


# ========== BUILD HELPERS ==========


def build_enricher_spec_from_dsl(
    enrich_spec: EnrichSpec,
    *,
    registry: OperationRegistry,
    providers: ProviderGateway | None = None,
    options: EnrichDslBuildOptions | None = None,
) -> EnricherSpec:
    """
    Назначение:
        Построить EnricherSpec из EnrichSpec (DSL).
    """

    try:
        if options is None:
            options = EnrichDslBuildOptions()
        if providers is None:
            providers = ProviderGateway.with_defaults()
        engine = TransformationEngine(registry)
        operations: list[EnrichmentOperation] = []

        match_key_spec = enrich_spec.enrich.match_key
        if match_key_spec is not None:
            operations.append(_build_match_key_operation(match_key_spec))
        elif options.require_match_key:
            raise DslLoadError(
                code="ENRICH_DSL_COMPILE_INVALID",
                message="enrich spec must define match_key",
            )

        secrets_spec = enrich_spec.enrich.secrets or SecretsSpec()
        for rule in enrich_spec.enrich.generate:
            operations.append(
                _build_generate_operation(
                    rule,
                    engine,
                    secrets_spec,
                    providers,
                )
            )

        for rule in enrich_spec.enrich.lookup:
            operations.append(_build_lookup_operation(rule, engine, providers))

        return EnricherSpec(
            operations=tuple(operations),
            key_registry=KeyRegistry(builders={}),
        )
    except DslLoadError:
        raise
    except Exception as exc:
        raise DslLoadError(
            code="ENRICH_DSL_COMPILE_INVALID",
            message=f"Invalid enrich DSL runtime contract: {exc}",
        ) from exc


def _build_match_key_operation(match_key_spec: MatchKeySpec) -> EnrichmentOperation:
    def _build_match_key(result, deps) -> dict[str, Any] | None:
        _ = deps
        row = result.row
        if row is None:
            return None
        parts: list[str | None] = []
        for field_name in match_key_spec.fields:
            parts.append(read_value_path(row, field_name))
        try:
            match_key = build_delimited_match_key(parts, strict=match_key_spec.strict)
        except MatchKeyError:
            return None
        return {"match_key": match_key.value}

    return EnrichmentOperation(
        name="build_match_key",
        op_type=EnrichOperationType.COMPUTE,
        targets=("match_key",),
        run_when_errors=RunWhenErrors.ALWAYS,
        strictness=StrictnessPolicy(on_provider_error=EnrichOutcome.FAILED),
        compute=_build_match_key,
        missing_error_code="MATCH_KEY_MISSING",
        error_field="matchKey",
    )


def _build_generate_operation(
    rule: EnrichRule,
    engine: TransformationEngine,
    secrets_spec: SecretsSpec,
    providers: ProviderGateway,
) -> EnrichmentOperation:
    target = rule.target
    if target in secrets_spec.fields:
        target = f"secret:{target}"

    merge_policy = _merge_policy_for(rule)
    strictness = _strictness_for(rule)
    run_when_errors = _run_when_errors_for(rule)

    return EnrichmentOperation(
        name=rule.name,
        op_type=EnrichOperationType.GENERATE,
        targets=(target,),
        merge_policy=merge_policy,
        strictness=strictness,
        run_when_errors=run_when_errors,
        generator=_build_rule_generator(rule, engine),
        exists=_build_exists(rule, providers),
        allow_if=_build_allow_if(rule, engine),
        max_attempts=rule.max_attempts or 3,
        missing_error_code=rule.missing_error_code,
        conflict_error_code=rule.conflict_error_code,
        error_field=rule.error_field or rule.target,
    )


def _build_rule_generator(rule: EnrichRule, engine: TransformationEngine):
    def _generator(result, deps):
        _ = deps
        row = result.row
        if row is None:
            return None
        value = _read_rule_value(row, rule)
        if rule.ops:
            resolved, op_issues = apply_ops(engine, value, rule.ops)
            if any(issue.severity == DslSeverity.ERROR for issue in op_issues):
                return None
            return resolved
        return value

    return _generator


class _DslLookupProvider:
    """
    Назначение:
        Провайдер lookup-кандидатов, построенный из DSL-правила.
    """

    def __init__(self, rule: EnrichRule, engine: TransformationEngine, providers: ProviderGateway) -> None:
        self.rule = rule
        self.engine = engine
        self.providers = providers
        self.name = rule.provider.name if rule.provider else "dsl_lookup"

    def fetch(self, ctx, result, deps, key_values):  # noqa: ANN001
        _ = (ctx, key_values)
        row = result.row
        if row is None:
            return []
        if not self.rule.provider:
            raise DslLoadError(
                code="ENRICH_DSL_LOOKUP_PROVIDER_MISSING",
                message=f"lookup rule '{self.rule.name}' requires provider",
                details={"rule": self.rule.name, "target": self.rule.target},
            )

        value = _read_rule_value(row, self.rule)
        if self.rule.ops:
            resolved, op_issues = apply_ops(self.engine, value, self.rule.ops)
            if any(issue.severity == DslSeverity.ERROR for issue in op_issues):
                raise DslLoadError(
                    code="ENRICH_DSL_LOOKUP_KEY_OP_FAILED",
                    message=f"lookup rule '{self.rule.name}' key operations failed",
                    details={"rule": self.rule.name, "target": self.rule.target},
                )
            value = resolved

        if value is None or value == "":
            return []

        candidates = self.providers.lookup(
            self.rule.provider.name,
            deps,
            value,
            args=self.rule.provider.args,
        )

        result_values = []
        for candidate in candidates:
            resolved = read_value_path(candidate, self.rule.value_path or self.rule.target)
            result_values.append(
                {
                    "field": self.rule.target,
                    "value": resolved,
                    "source": self.name,
                }
            )
        return [
            CandidateValue(
                field=item["field"],
                value=item["value"],
                source=item["source"],
            )
            for item in result_values
            if item["value"] is not None
        ]


def _read_rule_value(row: Any, rule: EnrichRule) -> Any:
    if rule.sources:
        return [read_value_path(row, name) for name in rule.sources]
    if rule.source:
        return read_value_path(row, rule.source)
    return None


def _build_exists(rule: EnrichRule, providers: ProviderGateway):
    if not rule.exists:
        return None

    def _exists(deps, value):
        return providers.exists(
            rule.exists.provider.name,
            deps,
            value,
            args=rule.exists.provider.args,
        )

    return _exists


def _build_allow_if(rule: EnrichRule, engine: TransformationEngine):
    if not rule.allow_if:
        return None
    op_call = rule.allow_if

    def _allow_if(result, existing):
        context = {
            "row": result.row,
            "meta": result.meta,
            "match_key": result.match_key.value if result.match_key else None,
            "existing": existing,
        }
        outcome = engine.apply(context, [op_call])
        if any(issue.severity == DslSeverity.ERROR for issue in outcome.issues):
            return False
        return bool(outcome.value)

    return _allow_if


def _build_lookup_operation(
    rule: EnrichRule,
    engine: TransformationEngine,
    providers: ProviderGateway,
) -> EnrichmentOperation:
    if not rule.provider:
        raise DslLoadError(
            code="ENRICH_DSL_LOOKUP_PROVIDER_MISSING",
            message=f"lookup rule '{rule.name}' requires provider",
            details={"rule": rule.name, "target": rule.target},
        )
    merge_policy = _merge_policy_for(rule)
    strictness = _strictness_for(rule)
    run_when_errors = _run_when_errors_for(rule)
    provider = _DslLookupProvider(rule, engine, providers)
    return EnrichmentOperation(
        name=rule.name,
        op_type=EnrichOperationType.LOOKUP,
        targets=(rule.target,),
        providers=(provider,),
        merge_policy=merge_policy,
        strictness=strictness,
        run_when_errors=run_when_errors,
        missing_error_code=rule.missing_error_code,
        conflict_error_code=rule.conflict_error_code,
        error_field=rule.error_field or rule.target,
    )


def _merge_policy_for(rule: EnrichRule) -> MergePolicy | None:
    if not rule.merge:
        return None
    mapping = {
        "recompute_always": MergeMode.RECOMPUTE_ALWAYS,
        "fill_only_if_empty": MergeMode.OVERRIDE_IF_EMPTY,
        "override_if_empty": MergeMode.OVERRIDE_IF_EMPTY,
        "never_override": MergeMode.NEVER_OVERRIDE,
        "override_if_authoritative": MergeMode.OVERRIDE_IF_AUTHORITATIVE,
    }
    mode = mapping.get(rule.merge)
    if mode is None:
        raise DslLoadError(
            code="ENRICH_DSL_MERGE_POLICY_INVALID",
            message=f"Unknown merge policy: {rule.merge}",
            details={"rule": rule.name, "merge": rule.merge},
        )
    return MergePolicy(mode=mode)


def _strictness_for(rule: EnrichRule) -> StrictnessPolicy | None:
    if rule.on_error == "warn":
        return StrictnessPolicy(
            on_no_candidates=EnrichOutcome.WARNED,
            on_provider_error=EnrichOutcome.WARNED,
        )
    return StrictnessPolicy(
        on_no_candidates=EnrichOutcome.FAILED,
        on_provider_error=EnrichOutcome.FAILED,
    )


def _run_when_errors_for(rule: EnrichRule) -> RunWhenErrors:
    if rule.run_when_errors == "always":
        return RunWhenErrors.ALWAYS
    if rule.run_when_errors == "if_any":
        return RunWhenErrors.IF_ANY
    return RunWhenErrors.NEVER
