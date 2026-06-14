"""Порты наблюдаемости — узкие event-интерфейсы, нейтральные к runtime.

Протоколы здесь являются общими контрактами для producers событий наблюдаемости.
Они держат оркестрацию приложения независимой от structlog, file handlers и ECS rendering,
но позволяют delivery-коду эмитить lifecycle intentions.

Границы ответственности:
    - Определять внутренний generic event sink contract.
    - Определять узкие lifecycle-контракты для зон по мере необходимости.

Вне ответственности:
    - Реализация event emission.
    - Форматирование или сериализация log records.
"""

from __future__ import annotations

from typing import Mapping, Protocol

from connector.common.observability.events import ObservabilityEvent


class ObservabilityEventSink(Protocol):
    """Внутренний транспорт для намерений observability-событий."""

    def emit(self, event: ObservabilityEvent, *, exc_info: object = None) -> None: ...


class RuntimeLifecycleEvents(Protocol):
    """Узкий контракт наблюдаемости для lifecycle команды или запуска."""

    def run_started(self, *, command_name: str) -> None: ...

    def run_completed(
        self,
        *,
        command_name: str,
        success: bool,
        duration_ns: int | None = None,
    ) -> None: ...


class PipelineLifecycleEvents(Protocol):
    """Узкий контракт наблюдаемости для lifecycle стадий pipeline."""

    def stage_started(self, *, stage_name: str) -> None: ...

    def stage_completed(
        self,
        *,
        stage_name: str,
        duration_ns: int,
        stats: Mapping[str, object] | None = None,
    ) -> None: ...

    def stage_failed(
        self,
        *,
        stage_name: str,
        exc: Exception,
        duration_ns: int,
    ) -> None: ...

    def stage_aborted(self, *, stage_name: str, duration_ns: int) -> None: ...


__all__ = [
    "ObservabilityEventSink",
    "PipelineLifecycleEvents",
    "RuntimeLifecycleEvents",
]
