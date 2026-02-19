"""
Назначение:
    Transform DSL: спецификации match-стадии.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from connector.domain.dsl.specs._base import DslBaseModel


class MatchRule(DslBaseModel):
    """
    Назначение:
        Декларативное правило построения identity для matcher.
    """

    name: str
    fields: list[str]
    primary: str | None = None

    @model_validator(mode="after")
    def _validate_fields(self) -> "MatchRule":
        if not self.fields:
            raise ValueError("match.identity_rules[].fields must not be empty")
        if self.primary and self.primary not in self.fields:
            raise ValueError("match.identity_rules[].primary must belong to fields")
        return self


class SourceDedupSpec(DslBaseModel):
    """
    Назначение:
        DSL-конфигурация source-dedup политики matcher.
    """

    enabled: bool = True
    on_duplicate: Literal["warn", "error"] = "warn"
    on_conflict: Literal["warn", "error"] = "error"


class FuzzySpec(DslBaseModel):
    """
    Назначение:
        DSL-конфигурация fuzzy/scoring matcher.
    """

    enabled: bool = False
    blocking_keys: list[str] = Field(default_factory=list)
    comparators: dict[str, Literal["exact", "casefold", "similarity"]] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)
    accept_threshold: float = 0.90
    review_threshold: float = 0.70
    tie_delta: float = 0.05
    max_candidates: int = 50
    top_k: int = 3
    score_round: int = 4

    @model_validator(mode="after")
    def _validate_thresholds(self) -> "FuzzySpec":
        if not 0.0 <= float(self.accept_threshold) <= 1.0:
            raise ValueError("match.fuzzy.accept_threshold must be within [0.0, 1.0]")
        if not 0.0 <= float(self.review_threshold) <= 1.0:
            raise ValueError("match.fuzzy.review_threshold must be within [0.0, 1.0]")
        if float(self.review_threshold) > float(self.accept_threshold):
            raise ValueError("match.fuzzy.review_threshold must be <= match.fuzzy.accept_threshold")
        if float(self.tie_delta) < 0.0:
            raise ValueError("match.fuzzy.tie_delta must be >= 0.0")
        if int(self.max_candidates) < 1:
            raise ValueError("match.fuzzy.max_candidates must be >= 1")
        if int(self.top_k) < 1:
            raise ValueError("match.fuzzy.top_k must be >= 1")
        if int(self.score_round) < 0:
            raise ValueError("match.fuzzy.score_round must be >= 0")
        for field_name, weight in self.weights.items():
            numeric = float(weight)
            if numeric < 0.0:
                raise ValueError(f"match.fuzzy.weights[{field_name!r}] must be >= 0.0")

        comparator_fields = set(self.comparators.keys())
        weight_fields = set(self.weights.keys())
        if comparator_fields != weight_fields:
            only_comparators = sorted(comparator_fields - weight_fields)
            only_weights = sorted(weight_fields - comparator_fields)
            raise ValueError(
                "match.fuzzy.comparators and match.fuzzy.weights must define the same fields; "
                f"comparators_only={only_comparators}, weights_only={only_weights}"
            )
        return self


class MatchBlock(DslBaseModel):
    identity_rules: list[MatchRule] = Field(default_factory=list)
    ignored_fields: list[str] = Field(default_factory=list)
    source_dedup: SourceDedupSpec = Field(default_factory=SourceDedupSpec)
    fuzzy: FuzzySpec = Field(default_factory=FuzzySpec)

    @model_validator(mode="after")
    def _validate_identity_rules(self) -> "MatchBlock":
        if not self.identity_rules:
            raise ValueError("match.identity_rules must not be empty")
        return self


class MatchSpec(DslBaseModel):
    dataset: str
    match: MatchBlock
