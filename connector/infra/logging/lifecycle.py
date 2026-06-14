"""Lifecycle logging adapters — семантические порты поверх generic event sink.

Адаптеры в этом модуле переводят runtime и pipeline lifecycle callbacks в значения
`ObservabilityEvent`. Они держат код оркестрации свободным от structlog kwargs,
ECS dotted keys и деталей taxonomy transport.

Границы ответственности:
    - Строить observability events для run и pipeline stage lifecycle.
    - Сохранять принятый event contract, размещая domain attributes в `fields`.

Вне ответственности:
    - Управление pipeline execution или command results.
    - Рендеринг финального ECS JSON document.
"""

from __future__ import annotations

from typing import Mapping

from connector.common.observability.events import (
    EventKind,
    EventOutcome,
    LogFieldValue,
    LogLevel,
    ObservabilityError,
    ObservabilityEvent,
)
from connector.common.observability.ports import (
    ObservabilityEventSink,
    PipelineLifecycleEvents,
    RuntimeLifecycleEvents,
)


class RuntimeLifecycleEventAdapter(RuntimeLifecycleEvents):
    """Публиковать command lifecycle events через observability sink."""

    def __init__(self, *, sink: ObservabilityEventSink) -> None:
        self._sink = sink

    def run_started(self, *, command_name: str) -> None:
        self._sink.emit(
            ObservabilityEvent(
                action="run-started",
                message="Command started",
                fields={"scope": "core", "command_name": command_name},
                level=LogLevel.INFO,
                kind=EventKind.EVENT,
            )
        )

    def run_completed(
        self,
        *,
        command_name: str,
        success: bool,
        duration_ns: int | None = None,
    ) -> None:
        self._sink.emit(
            ObservabilityEvent(
                action="run-completed",
                message="Command completed",
                fields={"scope": "core", "command_name": command_name},
                level=LogLevel.INFO,
                outcome=EventOutcome.SUCCESS if success else EventOutcome.FAILURE,
                kind=EventKind.EVENT,
                duration_ns=duration_ns,
            )
        )


class PipelineLifecycleEventAdapter(PipelineLifecycleEvents):
    """Публиковать pipeline stage lifecycle events через observability sink."""

    def __init__(self, *, sink: ObservabilityEventSink) -> None:
        self._sink = sink

    def stage_started(self, *, stage_name: str) -> None:
        self._sink.emit(
            ObservabilityEvent(
                action="stage-started",
                message="Pipeline stage started",
                fields={"stage_name": stage_name},
                level=LogLevel.INFO,
                kind=EventKind.EVENT,
            )
        )

    def stage_completed(
        self,
        *,
        stage_name: str,
        duration_ns: int,
        stats: Mapping[str, object] | None = None,
    ) -> None:
        fields: dict[str, LogFieldValue] = {"stage_name": stage_name}
        if stats is not None and "items" in stats:
            fields["items_count"] = _as_log_field_value(stats["items"])
        self._sink.emit(
            ObservabilityEvent(
                action="stage-completed",
                message="Pipeline stage completed",
                fields=fields,
                level=LogLevel.INFO,
                outcome=EventOutcome.SUCCESS,
                kind=EventKind.METRIC,
                duration_ns=duration_ns,
            )
        )

    def stage_failed(
        self,
        *,
        stage_name: str,
        exc: Exception,
        duration_ns: int,
    ) -> None:
        self._sink.emit(
            ObservabilityEvent(
                action="stage-failed",
                message="Pipeline stage failed",
                fields={"stage_name": stage_name},
                level=LogLevel.ERROR,
                outcome=EventOutcome.FAILURE,
                kind=EventKind.EVENT,
                duration_ns=duration_ns,
                error=ObservabilityError(
                    type=type(exc).__name__,
                    message=str(exc),
                ),
            ),
            exc_info=exc,
        )

    def stage_aborted(self, *, stage_name: str, duration_ns: int) -> None:
        self._sink.emit(
            ObservabilityEvent(
                action="stage-aborted",
                message="Pipeline stage aborted",
                fields={"stage_name": stage_name},
                level=LogLevel.DEBUG,
                outcome=EventOutcome.UNKNOWN,
                kind=EventKind.EVENT,
                duration_ns=duration_ns,
            )
        )


__all__ = [
    "PipelineLifecycleEventAdapter",
    "RuntimeLifecycleEventAdapter",
]


def _as_log_field_value(value: object) -> LogFieldValue:
    """Привести внешнее stats-значение к безопасному типу log field."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, tuple) and all(
        item is None or isinstance(item, (str, int, float, bool)) for item in value
    ):
        return value
    return str(value)
