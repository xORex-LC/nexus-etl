"""
Назначение:
    Контракты и правила матчинга/резолва.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from connector.domain.models import Identity
from connector.domain.transform.matcher.context import MatchContext

BuildIdentity = Callable[[Any, MatchContext], Identity]
BuildLinks = Callable[[Any, MatchContext], dict[str, Identity]]
BuildDesiredState = Callable[[Any, MatchContext], dict[str, Any]]
BuildSourceRef = Callable[[Identity], dict[str, Any]]
DiffPolicy = Callable[[dict[str, Any] | None, dict[str, Any]], dict[str, Any]]
SecretFieldsPolicy = Callable[[str, dict[str, Any], dict[str, Any] | None], list[str]]
MergePolicy = Callable[[dict[str, Any] | None, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class SourceDedupRules:
    """
    Назначение:
        Политики source-dedup на match-стадии (до DSL).

    Пояснение:
        Dedup-key строится канонически как `dataset:identity_primary:identity_value`.
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
class MatchingRules:
    """
    Назначение:
        Набор правил сопоставления для matcher (dataset‑специфика).
    """

    identity_rules: tuple[IdentityRule, ...]
    ignored_fields: set[str] = field(default_factory=set)
    build_links: BuildLinks | None = None
    source_dedup: SourceDedupRules = field(default_factory=SourceDedupRules)
    fuzzy: "FuzzyScoringRules" = field(default_factory=lambda: FuzzyScoringRules())


@dataclass(frozen=True)
class FuzzyScoringRules:
    """
    Назначение:
        Настройки fuzzy+scoring режима матчинга (MVP до DSL).
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
        """
        Назначение:
            Провалидировать runtime-параметры fuzzy/scoring до выполнения матчинга.
        """
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
class ResolveRules:
    """
    Назначение:
        Набор правил разрешения для resolver (dataset‑специфика).

    Пояснения:
        merge_policy применяется до link-resolve и diff.
        Рекомендуемый контракт:
            - принимать existing и desired_state,
            - возвращать новый desired_state,
            - не удалять явно заданные значения,
            - использовать existing только как источник дефолтов.
        Важно:
            если merge_policy задан, оптимизация skip по fingerprint отключается.
    """

    build_desired_state: BuildDesiredState
    build_source_ref: BuildSourceRef | None = None
    diff_policy: DiffPolicy | None = None
    secret_fields_for_op: SecretFieldsPolicy | None = None
    merge_policy: MergePolicy | None = None


@dataclass(frozen=True)
class LinkKeyRule:
    """
    Назначение:
        Правило извлечения ключа для link-resolve.
    """

    name: str
    field: str


@dataclass(frozen=True)
class LinkFieldRule:
    """
    Назначение:
        Правило resolve для одного link-поля.
    """

    field: str
    target_dataset: str
    resolve_keys: tuple[LinkKeyRule, ...]
    dedup_rules: tuple[tuple[str, ...], ...] = ()
    target_id_field: str = "_id"
    coerce: str | None = None
    on_unresolved: str = "pending"


@dataclass(frozen=True)
class LinkRules:
    """
    Назначение:
        Набор link-правил для resolver (dataset-специфика).
    """

    fields: tuple[LinkFieldRule, ...] = ()
