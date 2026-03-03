from __future__ import annotations

from connector.domain.reporting.assembler import ReportAssembler
from connector.domain.reporting.context import InMemoryReportContext, asdict_envelope
from connector.domain.reporting.events import AddItemEvent, FinishEvent, SetContextEvent, SetMetaEvent
from connector.domain.reporting.sink import IReportSink, ReportSink


class _SpySink(IReportSink):
    def __init__(self, context: InMemoryReportContext) -> None:
        self._context = context
        self.events: list[str] = []

    def emit(self, event) -> None:
        self.events.append(type(event).__name__)
        self._context.append(event)


def test_sink_emit_is_single_ingestion_entrypoint() -> None:
    context = InMemoryReportContext(run_id="run-emit", command="mapping")
    sink = _SpySink(context)
    sink.emit(SetMetaEvent(items_limit=3))
    sink.emit(SetContextEvent(name="runtime", value={"log_file": "test.log"}))
    sink.emit(
        AddItemEvent(
            status="OK",
            row_ref=None,
            payload=None,
            errors=(),
            warnings=(),
            meta={"k": "v"},
            store=True,
            preaggregated=False,
        )
    )
    sink.emit(FinishEvent(duration_ms=12))

    assert sink.events == [
        "SetMetaEvent",
        "SetContextEvent",
        "AddItemEvent",
        "FinishEvent",
    ]


def test_context_uses_bounded_memory_for_row_items_with_large_stream() -> None:
    context = InMemoryReportContext(run_id="run-bounded", command="mapping")
    sink = ReportSink(context)
    sink.emit(SetMetaEvent(items_limit=10))

    for _ in range(100_000):
        sink.emit(
            AddItemEvent(
                status="OK",
                row_ref=None,
                payload=None,
                errors=(),
                warnings=(),
                meta={},
                store=True,
            )
        )

    envelope = context.snapshot()
    assert envelope.summary.rows_total == 100_000
    assert len(envelope.items) == 10
    assert envelope.meta.items_truncated is True


def test_assembler_is_deterministic_for_equal_event_streams() -> None:
    context_a = InMemoryReportContext(run_id="run-a", command="normalize", started_at="2026-03-02T00:00:00Z")
    context_b = InMemoryReportContext(run_id="run-a", command="normalize", started_at="2026-03-02T00:00:00Z")
    sink_a = ReportSink(context_a)
    sink_b = ReportSink(context_b)

    events = [
        SetMetaEvent(items_limit=2),
        SetContextEvent(
            name="input",
            value={"csv_path": "employees.csv"},
        ),
        AddItemEvent(
            status="OK",
            row_ref=None,
            payload={"id": "1"},
            errors=(),
            warnings=(),
            meta={"stage": "MAP"},
            store=True,
        ),
        FinishEvent(finished_at="2026-03-02T00:00:00Z", duration_ms=42),
    ]

    for event in events:
        sink_a.emit(event)
        sink_b.emit(event)

    envelope_a = ReportAssembler(context=context_a).assemble()
    envelope_b = ReportAssembler(context=context_b).assemble()

    assert asdict_envelope(envelope_a) == asdict_envelope(envelope_b)
