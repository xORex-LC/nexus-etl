"""
Назначение:
    MatchDsl: компиляция MatchSpec в MatchingRules.
    Compiled models: MatchingRules, IdentityRule, SourceDedupRules, FuzzyScoringRules.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from connector.domain.models import Identity
from connector.domain.transform.matcher.context import MatchContext
from connector.domain.dsl.issues import DslLoadError
from connector.domain.transform_dsl.build_options import MatchDslBuildOptions
from connector.domain.transform_dsl.specs import MatchRule, MatchSpec

BuildIdentity = Callable[[Any, MatchContext], Identity]
BuildLinks = Callable[[Any, MatchContext], dict[str, Identity]]


# ========== COMPILED MODELS ==========


@dataclass(frozen=True)
class SourceDedupRules:
    """
    Назначение:
        Политики source-dedup на match-стадии.
    """

    enabled: bool = True
    on_duplicate: str = "warn"
    on_conflict: str = "error"


@dataclass(frozen=True)
class IdentityRule:
    """
    Назначение:
        Правило построения identity для matcher.
    """

    name: str
    build_identity: BuildIdentity


@dataclass(frozen=True)
class FuzzyScoringRules:
    """
    Назначение:
        Настройки fuzzy+scoring режима матчинга.
    """

    enabled: bool = False
    blocking_keys: tuple[str, ...] = ()
    comparators: dict[str, str] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)
    accept_threshold: float = 0.90
    review_threshold: float = 0.70
    tie_delta: float = 0.05
    max_candidates: int = 50
    top_k: int = 3
    score_round: int = 4

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.accept_threshold) <= 1.0:
            raise ValueError("fuzzy.accept_threshold must be within [0.0, 1.0]")
        if not 0.0 <= float(self.review_threshold) <= 1.0:
            raise ValueError("fuzzy.review_threshold must be within [0.0, 1.0]")
        if float(self.review_threshold) > float(self.accept_threshold):
            raise ValueError("fuzzy.review_threshold must be <= fuzzy.accept_threshold")
        if float(self.tie_delta) < 0.0:
            raise ValueError("fuzzy.tie_delta must be >= 0.0")
        if int(self.max_candidates) < 1:
            raise ValueError("fuzzy.max_candidates must be >= 1")
        if int(self.top_k) < 1:
            raise ValueError("fuzzy.top_k must be >= 1")
        if int(self.score_round) < 0:
            raise ValueError("fuzzy.score_round must be >= 0")

        for field_name, weight in self.weights.items():
            numeric = float(weight)
            if not math.isfinite(numeric):
                raise ValueError(f"fuzzy.weights[{field_name!r}] must be finite")
            if numeric < 0.0:
                raise ValueError(f"fuzzy.weights[{field_name!r}] must be >= 0.0")


@dataclass(frozen=True)
class MatchingRules:
    """
    Назначение:
        Набор правил сопоставления для matcher (dataset‑специфика).
    """

    identity_rules: tuple[IdentityRule, ...]
    ignored_fields: set[str] = field(default_factory=set)
    build_links: BuildLinks | None = None
    source_dedup: SourceDedupRules = field(default_factory=SourceDedupRules)
    fuzzy: FuzzyScoringRules = field(default_factory=FuzzyScoringRules)


# ========== COMPILER ==========


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
        value = getattr(match_context, field_name)
        if value not in (None, ""):
            return value
    if isinstance(row, dict):
        return row.get(field_name)
    if row is not None and hasattr(row, field_name):
        return getattr(row, field_name)
    return None
