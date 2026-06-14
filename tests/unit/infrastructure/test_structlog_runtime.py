"""Юнит-тесты нового structlog runtime и связанных observability-механик."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
import structlog
from structlog.stdlib import ProcessorFormatter

from connector.common.interactive_io import InteractiveIoGate
from connector.common.observability import (
    LogLevel,
    ObservabilityLayout,
    ObservabilityLayoutPolicy,
    ObservabilityRedactionPolicy,
    ObservabilityError,
    ObservabilityEvent,
    ServiceComponent,
)
from connector.common.runtime_paths import RuntimePathOverrides, detect_runtime_paths
from connector.config.models import (
    ComponentLoggingConfig,
    ConsoleLoggingSinkConfig,
    FileLoggingSinkConfig,
    LoggingConfig,
    LoggingSinksConfig,
)
from connector.delivery.cli.stream_capture import StdStreamToLogger
from connector.infra.logging.ecs import ecs_transform
from connector.infra.logging.event_sink import StructlogObservabilityEventSink
from connector.infra.logging.redaction import LogRedactionEngine
from connector.infra.logging.runtime import (
    DailySizeRotatingFileHandler,
    bind_observability_context,
    build_structured_logging_runtime,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _restore_logging_runtime_state() -> Iterator[None]:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    original_propagate = root_logger.propagate

    yield

    root_logger.handlers.clear()
    for handler in original_handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(original_level)
    root_logger.propagate = original_propagate
    structlog.reset_defaults()


def _layout(tmp_path: Path) -> ObservabilityLayout:
    runtime_paths = detect_runtime_paths(
        overrides=RuntimePathOverrides(
            runtime_root=Path.cwd(),
            cache_root=tmp_path / "var" / "cache",
            logs_root=tmp_path / "var" / "logs",
            reports_root=tmp_path / "reports",
            plans_root=tmp_path / "var" / "plans",
        ),
    )
    return ObservabilityLayout(
        runtime_paths=runtime_paths,
        policy=ObservabilityLayoutPolicy(partition_by_component=True, clock="utc"),
    )


def _json_line(buffer: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]


def _formatter_processors(runtime) -> list[object]:
    handler = runtime.handler_stack.console_handler
    assert handler is not None
    formatter = handler.formatter
    assert isinstance(formatter, ProcessorFormatter)
    return list(formatter.processors)


class _TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_structlog_runtime_writes_json_to_stderr_with_correlation_fields(
    tmp_path: Path,
) -> None:
    stderr = io.StringIO()
    runtime = build_structured_logging_runtime(
        config=LoggingConfig(
            sinks=LoggingSinksConfig(
                file=FileLoggingSinkConfig(enabled=False),
                console=ConsoleLoggingSinkConfig(
                    enabled=True, stream="stderr", format="json"
                ),
            )
        ),
        layout=_layout(tmp_path),
        redaction_engine=LogRedactionEngine(ObservabilityRedactionPolicy()),
        component=ServiceComponent.MAPPER,
        stderr_stream=stderr,
        root_logger_name="",
        app_version="1.2.3",
        git_rev="abc123",
    )
    bind_observability_context(
        run_id="run-1",
        pipeline_run_id="pipe-1",
        component=ServiceComponent.MAPPER,
        dataset="employees",
    )

    runtime.get_logger(
        ServiceComponent.MAPPER,
        logger_name="tests.runtime.mapper.child",
    ).info("row processed", row_ref="r-1")

    payload = _json_line(stderr)[0]
    assert payload["message"] == "row processed"
    assert payload["trace.id"] == "run-1"
    assert payload["labels.pipeline_run_id"] == "pipe-1"
    assert payload["service.type"] == "mapper"
    assert payload["event.dataset"] == "employees"
    assert payload["log.level"] == "info"
    assert payload["labels.schema_version"] == "1.0"
    assert payload["service.version"] == "1.2.3"
    assert payload["labels.git_rev"] == "abc123"
    assert payload["log.logger"] == "tests.runtime.mapper.child"
    runtime.close()


def test_json_formatter_processor_order_places_ecs_after_processor_cleanup(
    tmp_path: Path,
) -> None:
    runtime = build_structured_logging_runtime(
        config=LoggingConfig(
            sinks=LoggingSinksConfig(
                file=FileLoggingSinkConfig(enabled=False),
                console=ConsoleLoggingSinkConfig(
                    enabled=True, stream="stderr", format="json"
                ),
            )
        ),
        layout=_layout(tmp_path),
        redaction_engine=LogRedactionEngine(ObservabilityRedactionPolicy()),
        component=ServiceComponent.MAPPER,
        stderr_stream=io.StringIO(),
        root_logger_name="",
    )

    processors = _formatter_processors(runtime)

    assert processors.index(
        ProcessorFormatter.remove_processors_meta
    ) < processors.index(ecs_transform)
    assert processors[-2] is ecs_transform
    runtime.close()


def test_text_formatter_does_not_enable_ecs_transform(tmp_path: Path) -> None:
    runtime = build_structured_logging_runtime(
        config=LoggingConfig(
            sinks=LoggingSinksConfig(
                file=FileLoggingSinkConfig(enabled=False),
                console=ConsoleLoggingSinkConfig(
                    enabled=True, stream="stderr", format="text"
                ),
            )
        ),
        layout=_layout(tmp_path),
        redaction_engine=LogRedactionEngine(ObservabilityRedactionPolicy()),
        component=ServiceComponent.MAPPER,
        stderr_stream=io.StringIO(),
        root_logger_name="",
    )

    assert ecs_transform not in _formatter_processors(runtime)
    runtime.close()


def test_event_sink_preserves_exception_traceback_outside_except_frame(
    tmp_path: Path,
) -> None:
    stderr = io.StringIO()
    runtime = build_structured_logging_runtime(
        config=LoggingConfig(
            sinks=LoggingSinksConfig(
                file=FileLoggingSinkConfig(enabled=False),
                console=ConsoleLoggingSinkConfig(
                    enabled=True, stream="stderr", format="json"
                ),
            )
        ),
        layout=_layout(tmp_path),
        redaction_engine=LogRedactionEngine(ObservabilityRedactionPolicy()),
        component=ServiceComponent.PLANNER,
        stderr_stream=stderr,
        root_logger_name="",
    )
    try:
        raise RuntimeError("outside-frame")
    except RuntimeError as raised:
        exc = raised

    sink = StructlogObservabilityEventSink(
        logger=runtime.get_logger(
            ServiceComponent.PLANNER,
            logger_name="tests.runtime.exception.sink",
        )
    )
    sink.emit(
        ObservabilityEvent(
            action="stage-failed",
            message="Pipeline stage failed",
            level=LogLevel.ERROR,
            error=ObservabilityError(
                type="RuntimeError",
                message="outside-frame",
            ),
        ),
        exc_info=exc,
    )

    payload = _json_line(stderr)[0]
    assert payload["error.type"] == "RuntimeError"
    assert payload["error.message"] == "outside-frame"
    assert '"exc_type": "RuntimeError"' in str(payload["error.stack_trace"])
    assert '"exc_value": "outside-frame"' in str(payload["error.stack_trace"])
    runtime.close()


def test_structlog_runtime_json_output_preserves_cyrillic_without_ascii_escape(
    tmp_path: Path,
) -> None:
    stderr = io.StringIO()
    runtime = build_structured_logging_runtime(
        config=LoggingConfig(
            sinks=LoggingSinksConfig(
                file=FileLoggingSinkConfig(enabled=True, format="json"),
                console=ConsoleLoggingSinkConfig(
                    enabled=True, stream="stderr", format="json"
                ),
            )
        ),
        layout=_layout(tmp_path),
        redaction_engine=LogRedactionEngine(ObservabilityRedactionPolicy()),
        component=ServiceComponent.MAPPER,
        stderr_stream=stderr,
        root_logger_name="",
    )
    bind_observability_context(
        run_id="run-ru",
        pipeline_run_id="pipe-ru",
        component=ServiceComponent.MAPPER,
    )

    runtime.get_logger(
        ServiceComponent.MAPPER,
        logger_name="tests.runtime.mapper.cyrillic",
    ).info("Привет мир", field="Отдел геодезического контроля")

    console_text = stderr.getvalue()
    assert "\\u041f" not in console_text
    assert "Привет мир" in console_text
    assert "Отдел геодезического контроля" in console_text

    log_path = runtime.current_log_file_path()
    assert log_path is not None
    file_text = Path(log_path).read_text(encoding="utf-8")
    assert "\\u041f" not in file_text
    assert "Привет мир" in file_text
    assert "Отдел геодезического контроля" in file_text
    runtime.close()


def test_structlog_runtime_writes_human_console_text_with_colored_level(
    tmp_path: Path,
) -> None:
    stderr = _TtyStringIO()
    runtime = build_structured_logging_runtime(
        config=LoggingConfig(
            sinks=LoggingSinksConfig(
                file=FileLoggingSinkConfig(enabled=False),
                console=ConsoleLoggingSinkConfig(
                    enabled=True, stream="stderr", format="text"
                ),
            )
        ),
        layout=_layout(tmp_path),
        redaction_engine=LogRedactionEngine(ObservabilityRedactionPolicy()),
        component=ServiceComponent.VAULT,
        stderr_stream=stderr,
        root_logger_name="",
    )
    bind_observability_context(
        run_id="run-1",
        pipeline_run_id="pipe-1",
        component=ServiceComponent.VAULT,
    )

    runtime.get_logger(
        ServiceComponent.VAULT,
        logger_name="tests.runtime.vault.console",
    ).info("Command started", scope="core")

    line = stderr.getvalue().strip()
    assert "\033[32m[INFO]\033[0m vault core: Command started" in line
    assert " | run_id=run-1" in line
    assert " | pipeline_run_id=pipe-1" in line
    runtime.close()


def test_daily_size_handler_appends_same_day_and_switches_on_new_day(
    tmp_path: Path,
) -> None:
    current = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    logger = logging.getLogger("tests.daily-size")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)

    handler = DailySizeRotatingFileHandler(
        layout=_layout(tmp_path),
        component=ServiceComponent.APPLIER,
        max_bytes=1000,
        backup_count=2,
        clock=lambda: current,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

    logger.info("first")
    logger.info("second")
    first_path = tmp_path / "var" / "logs" / "applier" / "2026-06-04_applier.log"
    assert first_path.read_text(encoding="utf-8").splitlines() == ["first", "second"]

    current = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    logger.info("third")
    second_path = tmp_path / "var" / "logs" / "applier" / "2026-06-05_applier.log"
    assert second_path.read_text(encoding="utf-8").splitlines() == ["third"]
    handler.close()


def test_daily_size_handler_rolls_within_same_day(tmp_path: Path) -> None:
    logger = logging.getLogger("tests.roll-size")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)

    handler = DailySizeRotatingFileHandler(
        layout=_layout(tmp_path),
        component=ServiceComponent.ENRICHER,
        max_bytes=20,
        backup_count=2,
        clock=lambda: datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc),
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

    logger.info("0123456789")
    logger.info("abcdefghij")
    active = tmp_path / "var" / "logs" / "enricher" / "2026-06-04_enricher.log"
    backup = tmp_path / "var" / "logs" / "enricher" / "2026-06-04_enricher.1.log"

    assert active.exists()
    assert backup.exists()
    assert backup.read_text(encoding="utf-8").splitlines() == ["0123456789"]
    assert active.read_text(encoding="utf-8").splitlines() == ["abcdefghij"]
    handler.close()


def test_component_override_allows_debug_only_for_selected_component(
    tmp_path: Path,
) -> None:
    stderr = io.StringIO()
    runtime = build_structured_logging_runtime(
        config=LoggingConfig(
            level="INFO",
            components={
                ServiceComponent.ENRICHER: ComponentLoggingConfig(level="DEBUG")
            },
            sinks=LoggingSinksConfig(
                file=FileLoggingSinkConfig(enabled=False),
                console=ConsoleLoggingSinkConfig(
                    enabled=True, stream="stderr", format="json"
                ),
            ),
        ),
        layout=_layout(tmp_path),
        redaction_engine=LogRedactionEngine(ObservabilityRedactionPolicy()),
        component=ServiceComponent.MAPPER,
        stderr_stream=stderr,
        root_logger_name="",
    )
    bind_observability_context(
        run_id="run-1",
        pipeline_run_id="pipe-1",
        component=ServiceComponent.MAPPER,
    )

    runtime.get_logger(
        ServiceComponent.MAPPER, logger_name="tests.runtime.component.mapper"
    ).debug("drop-me")
    runtime.get_logger(
        ServiceComponent.ENRICHER, logger_name="tests.runtime.component.enricher"
    ).debug("keep-me")

    payloads = _json_line(stderr)
    assert [payload["message"] for payload in payloads] == ["keep-me"]
    runtime.close()


def test_console_mirror_is_suppressed_during_interactive_prompt_but_file_sink_keeps_event(
    tmp_path: Path,
) -> None:
    stderr = io.StringIO()
    interactive_io_gate = InteractiveIoGate()
    runtime = build_structured_logging_runtime(
        config=LoggingConfig(
            sinks=LoggingSinksConfig(
                file=FileLoggingSinkConfig(enabled=True, format="json"),
                console=ConsoleLoggingSinkConfig(
                    enabled=True, stream="stderr", format="json"
                ),
            )
        ),
        layout=_layout(tmp_path),
        redaction_engine=LogRedactionEngine(ObservabilityRedactionPolicy()),
        component=ServiceComponent.MAPPER,
        stderr_stream=stderr,
        root_logger_name="",
        interactive_io_gate=interactive_io_gate,
    )
    bind_observability_context(
        run_id="run-2",
        pipeline_run_id="pipe-2",
        component=ServiceComponent.MAPPER,
    )
    logger = runtime.get_logger(
        ServiceComponent.MAPPER,
        logger_name="tests.runtime.prompt.mirror",
    )

    with interactive_io_gate.suppress_observability_mirror():
        logger.info("hidden from console", scope="interactive")

    assert stderr.getvalue() == ""
    log_path = runtime.current_log_file_path()
    assert log_path is not None
    assert "hidden from console" in Path(log_path).read_text(encoding="utf-8")
    runtime.close()


def test_redaction_covers_kwargs_regex_traceback_foreign_and_capture(
    tmp_path: Path,
) -> None:
    stderr = io.StringIO()
    redaction_engine = LogRedactionEngine(
        ObservabilityRedactionPolicy(enabled=True, keys=("password", "token", "secret"))
    )
    runtime = build_structured_logging_runtime(
        config=LoggingConfig(
            sinks=LoggingSinksConfig(
                file=FileLoggingSinkConfig(enabled=False),
                console=ConsoleLoggingSinkConfig(
                    enabled=True, stream="stderr", format="json"
                ),
            )
        ),
        layout=_layout(tmp_path),
        redaction_engine=redaction_engine,
        component=ServiceComponent.APPLIER,
        stderr_stream=stderr,
        root_logger_name="",
    )
    bind_observability_context(
        run_id="run-2",
        pipeline_run_id="pipe-2",
        component=ServiceComponent.APPLIER,
    )

    logger = runtime.get_logger(
        ServiceComponent.APPLIER,
        logger_name="tests.runtime.redaction.app",
    )
    logger.info(
        "token=event-secret",
        password="kw-secret",
        details={"secret": "nested-secret"},
        note="password=string-secret",
    )
    try:
        raise RuntimeError("token=trace-secret")
    except RuntimeError:
        logger.exception("password=exception-secret")

    logging.getLogger("tests.runtime.redaction.foreign").error(
        "foreign token=foreign-secret"
    )

    capture_logger = runtime.get_logger(
        ServiceComponent.APPLIER,
        logger_name="tests.runtime.redaction.capture",
    )
    capture_stream = StdStreamToLogger(
        capture_logger,
        logging.INFO,
        "stdout",
        redaction_engine=redaction_engine,
    )
    capture_stream.write("password=captured-secret\n")
    capture_stream.flush()

    raw_output = stderr.getvalue()
    assert "kw-secret" not in raw_output
    assert "event-secret" not in raw_output
    assert "trace-secret" not in raw_output
    assert "foreign-secret" not in raw_output
    assert "captured-secret" not in raw_output
    assert "***" in raw_output
    payloads = _json_line(stderr)
    assert any(payload["message"] == "foreign token=***" for payload in payloads)
    assert any(payload["message"] == "password=***" for payload in payloads)
    runtime.close()
