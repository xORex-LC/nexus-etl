"""
Назначение:
    Event sinks для записи в report execution context (DEC-001).

Граница ответственности:
    - Принимает события от продюсеров и передаёт их в IReportContext.
    - Не принимает решений о сериализации и хранении артефактов.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from connector.domain.reporting.context import IReportContext
from connector.domain.reporting.events import ActivityMetricEvent, ReportEvent


@runtime_checkable
class IReportSink(Protocol):
    """
    Назначение:
        Единая публичная точка записи событий для продюсеров.
    """

    def emit(self, event: ReportEvent) -> None: ...


@runtime_checkable
class IActivitySink(Protocol):
    """
    Назначение:
        Фасад для подсистемной телеметрии (без знания report-domain событий).
    """

    def emit_activity(self, name: str, payload: Mapping[str, Any]) -> None: ...


class ReportSink(IReportSink, IActivitySink):
    """
    Назначение:
        Command-scoped sink, делегирующий события в report context.
    """

    def __init__(self, context: IReportContext) -> None:
        self._context = context

    def emit(self, event: ReportEvent) -> None:
        self._context.append(event)

    def emit_activity(self, name: str, payload: Mapping[str, Any]) -> None:
        self.emit(ActivityMetricEvent(name=name, payload=dict(payload)))


class NullActivitySink(IActivitySink):
    """
    Назначение:
        No-op sink для сценариев без activity tracing.
    """

    def emit_activity(self, name: str, payload: Mapping[str, Any]) -> None:
        return None
