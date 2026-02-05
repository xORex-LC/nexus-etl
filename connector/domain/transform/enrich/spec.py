"""
Назначение:
    Спецификация enrich (операции, политики, ключи).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

from connector.domain.models import DiagnosticItem
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.enrich.models import (
    EnrichOperationType,
    MergePolicy,
    RunWhenErrors,
    StrictnessPolicy,
)
from connector.domain.transform.enrich.providers import CandidateProvider

T = TypeVar("T")
D = TypeVar("D")

KeyBuilder = Callable[[TransformResult[T]], Any]


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
