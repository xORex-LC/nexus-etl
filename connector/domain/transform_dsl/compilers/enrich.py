"""
Назначение:
    EnricherDsl: компиляция EnrichSpec в EnricherSpec (compiled).
    Compiled models: EnricherSpec, EnrichmentOperation, KeyRegistry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

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
from connector.domain.transform.common import CompiledCanonicalizer
from connector.domain.transform.providers import ProviderGateway
from connector.domain.transform.providers.registry import (
    exists_cache_by_field_canonicalized,
    lookup_cache_by_field_canonicalized,
)
from connector.domain.dsl.engine import TransformationEngine
from connector.domain.dsl.helpers import apply_ops
from connector.domain.dsl.issues import DslLoadError, DslSeverity
from connector.domain.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.dsl.specs import OperationCall, SourceOpsBlock
from connector.domain.transform_dsl.build_options import EnrichDslBuildOptions
from connector.domain.transform_dsl.compilers.canonicalization import CanonicalizationDsl
from connector.domain.transform_dsl.specs import (
    EnrichRule,
    EnrichSpec,
    MatchKeySpec,
    SecretsSpec,
)
from connector.domain.transform.common.values import read_value_path
from connector.domain.transform.ids.match_key import (
    MatchKeyError,
    build_delimited_match_key,
)

T = TypeVar("T")
D = TypeVar("D")

KeyBuilder = Callable[[TransformResult[T]], Any]
ValueBuilder = Callable[[TransformResult[T], D], Any]
PredicateBuilder = Callable[[TransformResult[T], D], bool]


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
    base_generator: ValueBuilder[T, D] | None = None
    condition: PredicateBuilder[T, D] | None = None
    append_generator: ValueBuilder[T, D] | None = None
    exists: Callable[[D, Any], Any] | None = None
    allow_if: Callable[[TransformResult[T], Any], bool] | None = None
    conflict_policy: "CompiledConflictPolicy | None" = None
    max_attempts: int = 3
    postprocess: Callable[[Any], Any] | None = None
    missing_error_code: str | None = None
    conflict_error_code: str | None = None
    error_field: str | None = None


@dataclass(frozen=True)
class CompiledConflictPolicy:
    """
    Назначение:
        Нормализованная runtime-политика exists-конфликта для enrich generate.

    Инварианты:
        - suffixes применяются к base value, а не к предыдущей попытке;
        - attempts соответствует числу допустимых кандидатов для стратегии.
    """

    strategy: str
    suffixes: tuple[str, ...] = ()
    attempts: int = 1


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
            for op_call in _iter_rule_op_calls(rule):
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

    Порядок операций:
        - сначала match_key;
        - затем lookup-операции, чтобы cache-backed значения могли стать входом для generate;
        - затем generate-операции в декларативном порядке.
    """

    try:
        if options is None:
            options = EnrichDslBuildOptions()
        if providers is None:
            providers = ProviderGateway.with_defaults()
        engine = TransformationEngine(registry)
        operations: list[EnrichmentOperation] = []
        for rule in (*enrich_spec.enrich.lookup, *enrich_spec.enrich.generate):
            _validate_rule_provider_contract(rule)

        match_key_spec = enrich_spec.enrich.match_key
        if match_key_spec is not None:
            operations.append(_build_match_key_operation(match_key_spec))
        elif options.require_match_key:
            raise DslLoadError(
                code="ENRICH_DSL_COMPILE_INVALID",
                message="enrich spec must define match_key",
            )

        secrets_spec = enrich_spec.enrich.secrets or SecretsSpec()
        for rule in enrich_spec.enrich.lookup:
            operations.append(_build_lookup_operation(rule, engine, providers))

        for rule in enrich_spec.enrich.generate:
            operations.append(
                _build_generate_operation(
                    rule,
                    engine,
                    secrets_spec,
                    providers,
                )
            )

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
        base_generator=_build_base_generator(rule, engine),
        condition=_build_condition(rule, engine),
        append_generator=_build_append_generator(rule, engine),
        exists=_build_exists(rule, providers),
        allow_if=_build_allow_if(rule, engine),
        conflict_policy=_build_conflict_policy(rule),
        max_attempts=_resolve_max_attempts(rule),
        missing_error_code=rule.missing_error_code,
        conflict_error_code=rule.conflict_error_code,
        error_field=rule.error_field or rule.target,
    )


def _build_rule_generator(rule: EnrichRule, engine: TransformationEngine):
    base_generator = _build_base_generator(rule, engine)

    def _generator(result, deps):
        return base_generator(result, deps)

    return _generator


def _build_base_generator(
    rule: EnrichRule, engine: TransformationEngine
) -> ValueBuilder:
    block = rule.build

    def _generator(result, deps):
        _ = deps
        if result.row is None:
            return None
        if block is not None:
            return _resolve_block_value(result, block, engine)
        return _resolve_rule_value(result, rule.source, rule.sources, rule.ops, engine)

    return _generator


def _build_condition(
    rule: EnrichRule, engine: TransformationEngine
) -> PredicateBuilder | None:
    block = rule.when
    if block is None:
        return None

    def _condition(result, deps):
        _ = deps
        if result.row is None:
            return False
        value = _resolve_block_value(result, block, engine)
        return bool(value)

    return _condition


def _build_append_generator(
    rule: EnrichRule, engine: TransformationEngine
) -> ValueBuilder | None:
    block = rule.then
    if block is None:
        return None

    def _append(result, deps):
        _ = deps
        if result.row is None:
            return None
        return _resolve_block_value(result, block, engine)

    return _append


def _build_conflict_policy(rule: EnrichRule) -> CompiledConflictPolicy | None:
    policy = rule.on_conflict
    if policy is None:
        return None
    suffixes = tuple(policy.suffixes)
    attempts = 1 if policy.strategy == "error" else 1 + len(suffixes)
    return CompiledConflictPolicy(
        strategy=policy.strategy,
        suffixes=suffixes,
        attempts=attempts,
    )


class _DslLookupProvider:
    """
    Назначение:
        Провайдер lookup-кандидатов, построенный из DSL-правила.
    """

    def __init__(
        self,
        rule: EnrichRule,
        engine: TransformationEngine,
        providers: ProviderGateway,
        canonicalizer: CompiledCanonicalizer | None = None,
    ) -> None:
        self.rule = rule
        self.engine = engine
        self.providers = providers
        self.canonicalizer = canonicalizer
        self.name = rule.provider.name if rule.provider else "dsl_lookup"

    def fetch(self, ctx, result, deps, key_values):  # noqa: ANN001
        _ = (ctx, key_values)
        if result.row is None:
            return []
        if not self.rule.provider:
            raise DslLoadError(
                code="ENRICH_DSL_LOOKUP_PROVIDER_MISSING",
                message=f"lookup rule '{self.rule.name}' requires provider",
                details={"rule": self.rule.name, "target": self.rule.target},
            )

        value = _resolve_rule_value(
            result,
            self.rule.source,
            self.rule.sources,
            [],
            None,
        )
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

        candidates = self._lookup_candidates(deps, value)

        result_values = []
        for candidate in candidates:
            resolved = read_value_path(
                candidate, self.rule.value_path or self.rule.target
            )
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

    def _lookup_candidates(self, deps, value):  # noqa: ANN001
        provider = self.rule.provider
        if provider is None:
            return []
        if self.canonicalizer is not None and provider.name == "cache.by_field":
            return lookup_cache_by_field_canonicalized(
                deps,
                value,
                args=provider.args,
                canonicalizer=self.canonicalizer,
            )
        return self.providers.lookup(
            provider.name,
            deps,
            value,
            args=provider.args,
        )


def _resolve_rule_value(
    result: TransformResult[Any],
    source: str | None,
    sources: list[str] | None,
    ops: list[OperationCall],
    engine: TransformationEngine | None,
) -> Any:
    row = result.row
    if row is None:
        return None
    if sources:
        value = [_read_result_path(result, name) for name in sources]
    elif source:
        value = _read_result_path(result, source)
    else:
        value = None
    if not ops or engine is None:
        return value
    resolved, op_issues = apply_ops(engine, value, ops)
    if any(issue.severity == DslSeverity.ERROR for issue in op_issues):
        return None
    return resolved


def _resolve_block_value(
    result: TransformResult[Any], block: SourceOpsBlock, engine: TransformationEngine
) -> Any:
    return _resolve_rule_value(result, block.source, block.sources, block.ops, engine)


def _read_result_path(result: TransformResult[Any], path: str) -> Any:
    """
    Назначение:
        Прочитать enrich source-path из compiled runtime context.

    Поддерживает:
        - `match_key` как значение из TransformResult;
        - `meta.<path>` как доступ к enrich meta;
        - обычные row-path через `read_value_path`.
    """
    if path == "match_key":
        return result.match_key.value if result.match_key is not None else None
    if path.startswith("meta."):
        return read_value_path(result.meta, path.split("meta.", 1)[1])
    row = result.row
    if row is None:
        return None
    return read_value_path(row, path)


def _iter_rule_op_calls(rule: EnrichRule) -> list[OperationCall]:
    ops = list(rule.ops)
    for block in (rule.build, rule.when, rule.then):
        if block is not None:
            ops.extend(block.ops)
    return ops
    return None


def _build_exists(rule: EnrichRule, providers: ProviderGateway):
    if not rule.exists:
        return None

    canonicalizer = _compile_provider_canonicalizer(rule.exists.provider)

    def _exists(deps, value):
        if canonicalizer is not None and rule.exists is not None:
            if rule.exists.provider.name == "cache.exists_by_field":
                return exists_cache_by_field_canonicalized(
                    deps,
                    value,
                    args=rule.exists.provider.args,
                    canonicalizer=canonicalizer,
                )
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


def _resolve_max_attempts(rule: EnrichRule) -> int:
    if rule.on_conflict and rule.on_conflict.strategy == "retry_with_suffixes":
        return 1 + len(rule.on_conflict.suffixes)
    return rule.max_attempts or 3


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
    provider = _DslLookupProvider(
        rule,
        engine,
        providers,
        _compile_provider_canonicalizer(rule.provider),
    )
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


def _validate_rule_provider_contract(rule: EnrichRule) -> None:
    _validate_provider_canonicalization(rule)
    _validate_exists_canonicalization(rule)


def _compile_provider_canonicalizer(
    provider,  # noqa: ANN001
) -> CompiledCanonicalizer | None:
    if provider is None or provider.canonicalization is None:
        return None
    return CanonicalizationDsl().compile(provider.canonicalization).python


def _validate_provider_canonicalization(rule: EnrichRule) -> None:
    provider = rule.provider
    if provider is None or provider.canonicalization is None:
        return
    if provider.name != "cache.by_field":
        raise DslLoadError(
            code="ENRICH_DSL_COMPILE_INVALID",
            message=(
                f"lookup rule '{rule.name}' declares canonicalization for unsupported "
                f"provider '{provider.name}'"
            ),
            details={"rule": rule.name, "provider": provider.name},
        )
    if str(provider.args.get("mode", "exact")) != "exact":
        raise DslLoadError(
            code="ENRICH_DSL_COMPILE_INVALID",
            message=(
                f"lookup rule '{rule.name}' canonicalized cache lookup supports only "
                "mode='exact'"
            ),
            details={"rule": rule.name, "provider": provider.name},
        )


def _validate_exists_canonicalization(rule: EnrichRule) -> None:
    exists_ref = rule.exists
    if exists_ref is None or exists_ref.provider.canonicalization is None:
        return
    if exists_ref.provider.name != "cache.exists_by_field":
        raise DslLoadError(
            code="ENRICH_DSL_COMPILE_INVALID",
            message=(
                f"generate rule '{rule.name}' declares canonicalization for unsupported "
                f"exists provider '{exists_ref.provider.name}'"
            ),
            details={"rule": rule.name, "provider": exists_ref.provider.name},
        )
    if str(exists_ref.provider.args.get("mode", "exact")) != "exact":
        raise DslLoadError(
            code="ENRICH_DSL_COMPILE_INVALID",
            message=(
                f"generate rule '{rule.name}' canonicalized cache exists supports only "
                "mode='exact'"
            ),
            details={"rule": rule.name, "provider": exists_ref.provider.name},
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
    legacy_policy = (
        StrictnessPolicy(
            on_no_candidates=EnrichOutcome.WARNED,
            on_provider_error=EnrichOutcome.WARNED,
        )
        if rule.on_error == "warn"
        else StrictnessPolicy(
            on_no_candidates=EnrichOutcome.FAILED,
            on_provider_error=EnrichOutcome.FAILED,
        )
    )

    return StrictnessPolicy(
        on_missing_key=_map_strictness_outcome(
            rule.on_missing_key,
            fallback=legacy_policy.on_missing_key,
        ),
        on_no_candidates=_map_strictness_outcome(
            rule.on_no_candidates,
            fallback=legacy_policy.on_no_candidates,
        ),
        on_ambiguous=_map_strictness_outcome(
            rule.on_ambiguous,
            fallback=legacy_policy.on_ambiguous,
        ),
        on_provider_error=_map_strictness_outcome(
            rule.on_provider_error,
            fallback=legacy_policy.on_provider_error,
        ),
    )


def _map_strictness_outcome(raw: str | None, *, fallback: str) -> str:
    if raw is None:
        return fallback
    mapping = {
        "skip": EnrichOutcome.SKIPPED,
        "warn": EnrichOutcome.WARNED,
        "error": EnrichOutcome.FAILED,
        "needs_resolve": EnrichOutcome.NEEDS_RESOLVE,
    }
    return mapping.get(raw, fallback)


def _run_when_errors_for(rule: EnrichRule) -> RunWhenErrors:
    if rule.run_when_errors == "always":
        return RunWhenErrors.ALWAYS
    if rule.run_when_errors == "if_any":
        return RunWhenErrors.IF_ANY
    return RunWhenErrors.NEVER
