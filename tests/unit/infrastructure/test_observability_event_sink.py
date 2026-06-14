"""Юнит-тесты bridge между ObservabilityEvent и structlog logger."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from connector.common.observability import (
    EventKind,
    EventOutcome,
    LogLevel,
    ObservabilityError,
    ObservabilityEvent,
)
from connector.infra.logging.event_sink import StructlogObservabilityEventSink

pytestmark = pytest.mark.unit


@dataclass
class _Logger:
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)

    def info(self, message: str, **kwargs: Any) -> None:
        self.calls.append(("info", message, kwargs))

    def error(self, message: str, **kwargs: Any) -> None:
        self.calls.append(("error", message, kwargs))

    def debug(self, message: str, **kwargs: Any) -> None:
        self.calls.append(("debug", message, kwargs))

    def warning(self, message: str, **kwargs: Any) -> None:
        self.calls.append(("warning", message, kwargs))

    def critical(self, message: str, **kwargs: Any) -> None:
        self.calls.append(("critical", message, kwargs))


def test_event_sink_emits_event_contract_as_structlog_kwargs() -> None:
    logger = _Logger()
    sink = StructlogObservabilityEventSink(logger=logger)

    sink.emit(
        ObservabilityEvent(
            action="stage-completed",
            message="Pipeline stage completed",
            fields={"stage_name": "match", "items_count": 3},
            level=LogLevel.INFO,
            outcome=EventOutcome.SUCCESS,
            kind=EventKind.METRIC,
            duration_ns=42,
        )
    )

    assert logger.calls == [
        (
            "info",
            "Pipeline stage completed",
            {
                "action": "stage-completed",
                "stage_name": "match",
                "items_count": 3,
                "outcome": "success",
                "kind": "metric",
                "duration_ns": 42,
            },
        )
    ]


def test_event_sink_adds_manual_error_fields_and_exception_object() -> None:
    logger = _Logger()
    sink = StructlogObservabilityEventSink(logger=logger)
    exc = RuntimeError("boom")

    sink.emit(
        ObservabilityEvent(
            action="stage-failed",
            message="Pipeline stage failed",
            level=LogLevel.ERROR,
            error=ObservabilityError(
                type="RuntimeError",
                message="boom",
                code="STAGE_FAILED",
            ),
        ),
        exc_info=exc,
    )

    assert logger.calls == [
        (
            "error",
            "Pipeline stage failed",
            {
                "action": "stage-failed",
                "error_type": "RuntimeError",
                "error_message": "boom",
                "error_code": "STAGE_FAILED",
                "exc_info": exc,
            },
        )
    ]


def test_event_sink_rejects_dotted_event_fields() -> None:
    logger = _Logger()
    sink = StructlogObservabilityEventSink(logger=logger)

    with pytest.raises(ValueError):
        sink.emit(
            ObservabilityEvent(
                action="bad-event",
                message="Bad event",
                fields={"event.action": "bad-event"},
            )
        )
