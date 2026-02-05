"""
Назначение:
    Сборка EnricherSpec из DSL-спецификаций.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from connector.domain.transform.enrich.models import (
    CandidateValue,
    EnrichOperationType,
    EnrichOutcome,
    MergeMode,
    MergePolicy,
    RunWhenErrors,
    StrictnessPolicy,
)
from connector.domain.transform.enrich.spec import EnricherSpec, EnrichmentOperation, KeyRegistry
from connector.domain.transform.dsl.engine import TransformationEngine
from connector.domain.transform.dsl.issues import DslSeverity
from connector.domain.transform.dsl.registry import OperationRegistry
from connector.domain.transform.dsl.specs import EnrichRule, EnrichSpec, MatchKeySpec, SecretsSpec
from connector.domain.transform.ids.match_key import MatchKeyError, build_delimited_match_key


@dataclass(frozen=True)
class EnrichDslBuildOptions:
    """
    Назначение:
        Настройки сборки EnricherSpec из DSL.
    """

    require_match_key: bool = False


def build_enricher_spec_from_dsl(
    enrich_spec: EnrichSpec,
    *,
    registry: OperationRegistry,
    options: EnrichDslBuildOptions | None = None,
) -> EnricherSpec:
    """
    Назначение:
        Построить EnricherSpec из EnrichSpec (DSL).
    """

    if options is None:
        options = EnrichDslBuildOptions()
    engine = TransformationEngine(registry)
    operations: list[EnrichmentOperation] = []

    match_key_spec = enrich_spec.enrich.match_key
    if match_key_spec is not None:
        operations.append(_build_match_key_operation(match_key_spec))
    elif options.require_match_key:
        raise ValueError("enrich spec must define match_key")

    secrets_spec = enrich_spec.enrich.secrets or SecretsSpec()
    for rule in enrich_spec.enrich.generate:
        operations.append(
            _build_generate_operation(
                rule,
                engine,
                secrets_spec,
            )
        )

    for rule in enrich_spec.enrich.lookup:
        operations.append(_build_lookup_operation(rule, engine))

    return EnricherSpec(
        operations=tuple(operations),
        key_registry=KeyRegistry(builders={}),
    )


def _build_match_key_operation(match_key_spec: MatchKeySpec) -> EnrichmentOperation:
    def _build_match_key(result, deps) -> dict[str, Any] | None:
        _ = deps
        row = result.row
        if row is None:
            return None
        parts: list[str | None] = []
        for field in match_key_spec.fields:
            parts.append(_read_row_value(row, field))
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
        exists=_build_exists(rule),
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
            outcome = engine.apply(value, rule.ops)
            if any(issue.severity == DslSeverity.ERROR for issue in outcome.issues):
                return None
            return outcome.value
        return value

    return _generator


class _DslLookupProvider:
    """
    Назначение:
        Провайдер lookup-кандидатов, построенный из DSL-правила.
    """

    def __init__(self, rule: EnrichRule, engine: TransformationEngine) -> None:
        self.rule = rule
        self.engine = engine
        self.name = rule.lookup or "dsl_lookup"

    def fetch(self, ctx, result, deps, key_values):  # noqa: ANN001
        _ = (ctx, key_values)
        row = result.row
        if row is None:
            return []
        if not self.rule.lookup:
            raise AttributeError("lookup rule missing 'lookup' method")
        func = getattr(deps, self.rule.lookup, None)
        if func is None:
            raise AttributeError(f"deps missing method '{self.rule.lookup}'")

        value = _read_rule_value(row, self.rule)
        if self.rule.ops:
            outcome = self.engine.apply(value, self.rule.ops)
            if any(issue.severity == DslSeverity.ERROR for issue in outcome.issues):
                raise ValueError("lookup key ops failed")
            value = outcome.value

        if value is None or value == "":
            return []

        found = func(value)
        if found is None:
            return []
        if isinstance(found, list):
            candidates = found
        else:
            candidates = [found]

        result_values = []
        for candidate in candidates:
            resolved = _read_value_path(candidate, self.rule.value_path or self.rule.target)
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
        return [_read_row_value(row, name) for name in rule.sources]
    if rule.source:
        return _read_row_value(row, rule.source)
    return None


def _read_row_value(row: Any, name: str | None) -> Any:
    if name is None:
        return None
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _read_value_path(candidate: Any, path: str | None) -> Any:
    if path is None:
        return None
    current = candidate
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, Mapping):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def _build_exists(rule: EnrichRule):
    if not rule.exists:
        return None

    def _exists(deps, value):
        func = getattr(deps, rule.exists, None)
        if func is None:
            raise AttributeError(f"deps missing method '{rule.exists}'")
        return func(value)

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


def _build_lookup_operation(rule: EnrichRule, engine: TransformationEngine) -> EnrichmentOperation:
    if not rule.lookup:
        raise ValueError("lookup rule requires 'lookup' method")
    merge_policy = _merge_policy_for(rule)
    strictness = _strictness_for(rule)
    run_when_errors = _run_when_errors_for(rule)
    provider = _DslLookupProvider(rule, engine)
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
        raise ValueError(f"Unknown merge policy: {rule.merge}")
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
