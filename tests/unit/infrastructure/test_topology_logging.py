"""Юнит-тесты native topology logging и stream-capture observability."""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog

from connector.common.interactive_io import InteractiveIoGate
from connector.common.observability import (
    ObservabilityLayout,
    ObservabilityLayoutPolicy,
    ObservabilityRedactionPolicy,
    ServiceComponent,
)
from connector.common.runtime_paths import RuntimePathOverrides, detect_runtime_paths
from connector.config.models import (
    ConsoleLoggingSinkConfig,
    FileLoggingSinkConfig,
    LoggingConfig,
    LoggingSinksConfig,
)
from connector.delivery.cli.stream_capture import StdStreamToLogger
from connector.infra.logging.redaction import LogRedactionEngine
from connector.infra.logging.runtime import (
    bind_observability_context,
    build_structured_logging_runtime,
)
from connector.infra.logging.topology import StructlogTopologyEventSink

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


def _runtime(
    tmp_path: Path,
    *,
    stderr: io.StringIO | None = None,
    console_enabled: bool = False,
    file_enabled: bool = True,
):
    return build_structured_logging_runtime(
        config=LoggingConfig(
            sinks=LoggingSinksConfig(
                file=FileLoggingSinkConfig(enabled=file_enabled, format="text"),
                console=ConsoleLoggingSinkConfig(
                    enabled=console_enabled,
                    stream="stderr",
                    format="text",
                ),
            )
        ),
        layout=_layout(tmp_path),
        redaction_engine=LogRedactionEngine(ObservabilityRedactionPolicy()),
        component=ServiceComponent.MATCHER,
        stderr_stream=stderr,
        root_logger_name="",
    )


def test_structlog_topology_event_sink_writes_scope_and_fields(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    bind_observability_context(
        run_id="run-1",
        pipeline_run_id="pipe-1",
        component=ServiceComponent.MATCHER,
        dataset="organizations",
    )
    logger = runtime.get_logger(
        ServiceComponent.MATCHER,
        logger_name="tests.topology.match",
    )
    sink = StructlogTopologyEventSink(logger=logger)

    sink.emit(
        level=logging.INFO,
        event="bootstrap.start",
        payload={"dataset": "organizations", "require_target": True},
    )

    log_path = runtime.current_log_file_path()
    assert log_path is not None
    contents = Path(log_path).read_text(encoding="utf-8")
    assert "scope=topology |" in contents
    assert "event=bootstrap.start" in contents
    assert "dataset=organizations |" in contents
    assert "require_target=true" in contents
    runtime.close()


def test_console_sink_skips_stderr_when_disabled(tmp_path: Path) -> None:
    stderr = io.StringIO()
    runtime = _runtime(
        tmp_path, stderr=stderr, console_enabled=False, file_enabled=False
    )
    logger = runtime.get_logger(
        ServiceComponent.MATCHER,
        logger_name="tests.topology.console.disabled",
    )

    logger.info("silent console", scope="test")

    assert stderr.getvalue() == ""
    runtime.close()


def test_console_sink_writes_to_configured_stderr_stream(tmp_path: Path) -> None:
    stderr = io.StringIO()
    runtime = _runtime(
        tmp_path, stderr=stderr, console_enabled=True, file_enabled=False
    )
    logger = runtime.get_logger(
        ServiceComponent.MATCHER,
        logger_name="tests.topology.console.enabled",
    )

    logger.info("mirrored", scope="test")

    assert "[INFO] matcher test: mirrored" in stderr.getvalue()
    runtime.close()


def test_stream_capture_emits_native_structured_field(tmp_path: Path) -> None:
    stderr = io.StringIO()
    runtime = _runtime(
        tmp_path, stderr=stderr, console_enabled=True, file_enabled=False
    )
    logger = runtime.get_logger(
        ServiceComponent.MATCHER,
        logger_name="tests.topology.capture",
    )
    capture = StdStreamToLogger(logger, logging.INFO, "stdout")

    capture.write("captured line\n")
    capture.flush()

    captured = stderr.getvalue()
    assert "[INFO] matcher: captured line" in captured
    assert " | captured_stream=stdout" in captured
    runtime.close()


def test_stream_capture_skips_prompt_output_while_interactive_gate_is_active(
    tmp_path: Path,
) -> None:
    stderr = io.StringIO()
    interactive_io_gate = InteractiveIoGate()
    runtime = _runtime(
        tmp_path, stderr=stderr, console_enabled=True, file_enabled=False
    )
    logger = runtime.get_logger(
        ServiceComponent.MATCHER,
        logger_name="tests.topology.capture.prompt",
    )
    capture = StdStreamToLogger(
        logger,
        logging.INFO,
        "stdout",
        interactive_io_gate=interactive_io_gate,
    )

    with interactive_io_gate.suppress_observability_mirror():
        capture.write("Введите пароль: ")
        capture.flush()

    assert "Введите пароль" not in stderr.getvalue()
    runtime.close()
