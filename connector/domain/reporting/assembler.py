"""
Назначение:
    Сборка финального отчёта из execution context (DEC-001).

Граница ответственности:
    - Собирает immutable snapshot из контекста.
    - Применяет enrichers детерминированно по фиксированному порядку.
    - Не пишет артефакты на диск.
"""

from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from connector.domain.reporting.context import IReportContext
from connector.domain.reporting.models import ReportEnvelope


@runtime_checkable
class IReportEnricher(Protocol):
    """
    Назначение:
        Контракт enrich-компонента для финального envelope.
    """

    def enrich(self, envelope: ReportEnvelope) -> None: ...


class CompositeReportEnricher(IReportEnricher):
    """
    Назначение:
        Композиция enrichers с детерминированным порядком применения.
    """

    def __init__(self, enrichers: Iterable[IReportEnricher] | None = None) -> None:
        self._enrichers = tuple(enrichers or ())

    def enrich(self, envelope: ReportEnvelope) -> None:
        for enricher in self._enrichers:
            enricher.enrich(envelope)


class ReportAssembler:
    """
    Назначение:
        Собрать финальный ReportEnvelope из контекста выполнения.
    """

    def __init__(
        self,
        *,
        context: IReportContext,
        enricher: IReportEnricher | None = None,
    ) -> None:
        self._context = context
        self._enricher = enricher or CompositeReportEnricher()

    def assemble(self) -> ReportEnvelope:
        envelope = self._context.snapshot()
        self._enricher.enrich(envelope)
        return envelope
