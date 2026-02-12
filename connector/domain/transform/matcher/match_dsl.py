"""
Назначение:
    Компиляция MatchSpec (DSL) в runtime-контракт MatchingRules.
"""

from __future__ import annotations

from connector.domain.models import Identity
from connector.domain.dsl.build_options import MatchDslBuildOptions
from connector.domain.dsl.issues import DslLoadError
from connector.domain.transform.matcher.rules import (
    FuzzyScoringRules,
    IdentityRule,
    MatchingRules,
    SourceDedupRules,
)
from connector.domain.dsl.specs import MatchRule, MatchSpec


class MatchDsl:
    """
    Назначение/ответственность:
        Компилирует MatchSpec в MatchingRules без изменения matcher-core.
    """

    def __init__(self, *, options: MatchDslBuildOptions | None = None) -> None:
        self.options = options or MatchDslBuildOptions()

    def compile(self, spec: MatchSpec) -> MatchingRules:
        """
        Назначение:
            Скомпилировать MatchSpec в MatchingRules.
        """
        try:
            identity_rules = tuple(_build_identity_rule(rule) for rule in spec.match.identity_rules)
            if not identity_rules:
                raise DslLoadError(
                    code="MATCH_DSL_COMPILE_INVALID",
                    message="match.identity_rules must not be empty",
                )
            if self.options.require_primary_identity_rule:
                missing_primary = [rule.name for rule in spec.match.identity_rules if not rule.primary]
                if missing_primary:
                    raise DslLoadError(
                        code="MATCH_DSL_COMPILE_INVALID",
                        message=(
                            "match.identity_rules[].primary is required by build options; missing for: "
                            + ", ".join(missing_primary)
                        ),
                    )
            source_dedup = SourceDedupRules(
                enabled=spec.match.source_dedup.enabled,
                on_duplicate=spec.match.source_dedup.on_duplicate,
                on_conflict=spec.match.source_dedup.on_conflict,
            )
            fuzzy = FuzzyScoringRules(
                enabled=spec.match.fuzzy.enabled,
                blocking_keys=tuple(spec.match.fuzzy.blocking_keys),
                comparators=dict(spec.match.fuzzy.comparators),
                weights=dict(spec.match.fuzzy.weights),
                accept_threshold=spec.match.fuzzy.accept_threshold,
                review_threshold=spec.match.fuzzy.review_threshold,
                tie_delta=spec.match.fuzzy.tie_delta,
                max_candidates=spec.match.fuzzy.max_candidates,
                top_k=spec.match.fuzzy.top_k,
                score_round=spec.match.fuzzy.score_round,
            )
            return MatchingRules(
                identity_rules=identity_rules,
                ignored_fields=set(spec.match.ignored_fields),
                source_dedup=source_dedup,
                fuzzy=fuzzy,
            )
        except DslLoadError:
            raise
        except Exception as exc:
            raise DslLoadError(
                code="MATCH_DSL_COMPILE_INVALID",
                message=f"Failed to compile match DSL: {exc}",
            ) from exc


def _build_identity_rule(rule: MatchRule) -> IdentityRule:
    fields = tuple(rule.fields)
    primary = rule.primary or rule.name or fields[0]

    def _build_identity(row, match_context) -> Identity:
        values: dict[str, str] = {}
        for field_name in fields:
            value = _read_identity_value(field_name, row=row, match_context=match_context)
            values[field_name] = "" if value is None else str(value)
        return Identity(primary=primary, values=values)

    return IdentityRule(name=rule.name, build_identity=_build_identity)


def _read_identity_value(field_name: str, *, row, match_context):
    if hasattr(match_context, field_name):
        return getattr(match_context, field_name)
    if row is not None and hasattr(row, field_name):
        return getattr(row, field_name)
    return None


__all__ = ["MatchDsl"]
