"""
Назначение:
    Контракты для источников кандидатов enrich.
"""

from __future__ import annotations

from typing import Any, Generic, Protocol, TypeVar

from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.enrich.models import CandidateValue, EnrichContext

T = TypeVar("T")
D = TypeVar("D")


class CandidateProvider(Protocol, Generic[T, D]):
    """
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
