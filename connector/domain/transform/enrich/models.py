"""
Назначение:
    Модели и политики enrich.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from connector.domain.models import DiagnosticItem


class EnrichOutcome(str, Enum):
    """
    Стандартные исходы операции enrich.
    """

    APPLIED = "APPLIED"
    SKIPPED = "SKIPPED"
    WARNED = "WARNED"
    FAILED = "FAILED"
    NEEDS_RESOLVE = "NEEDS_RESOLVE"


class RunWhenErrors(str, Enum):
    """
    Политика запуска операции при наличии ошибок до enrich.
    """

    NEVER = "NEVER"
    ONLY_NON_FATAL = "ONLY_NON_FATAL"
    ALWAYS = "ALWAYS"


class EnrichOperationType(str, Enum):
    """
    Тип операции enrich.
    """

    COMPUTE = "COMPUTE"
    FILL_MISSING = "FILL_MISSING"
    LOOKUP = "LOOKUP"
    GENERATE = "GENERATE"
    MEMBERSHIP = "MEMBERSHIP"


class MergeMode(str, Enum):
    """
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
    Политика слияния значений поля.
    """

    mode: str = MergeMode.FILL_ONLY_IF_EMPTY


@dataclass(frozen=True)
class StrictnessPolicy:
    """
    Политика реакции на ключевые ситуации enrich.
    """

    on_missing_key: str = EnrichOutcome.SKIPPED
    on_no_candidates: str = EnrichOutcome.SKIPPED
    on_ambiguous: str = EnrichOutcome.NEEDS_RESOLVE
    on_provider_error: str = EnrichOutcome.WARNED


@dataclass(frozen=True)
class CandidateValue:
    """
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
    Результат разрешения конфликтов кандидатов.
    """

    status: str
    selected: CandidateValue | None
    candidates: list[CandidateValue]
    reason: str | None = None


@dataclass(frozen=True)
class EnrichEvent:
    """
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
    Контекст выполнения enrich (run-level).
    """

    dataset: str
    run_id: str | None = None
    as_of: Any | None = None
