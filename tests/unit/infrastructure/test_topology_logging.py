"""Юнит-тесты topology logging seam и общей console mirror policy."""

from __future__ import annotations

import io
import logging

import pytest

from connector.infra.logging.setup import create_command_logger
from connector.infra.logging.topology import LegacyLogEventSink

pytestmark = pytest.mark.unit


def test_legacy_log_event_sink_writes_topology_component_and_logfmt(
    tmp_path,
) -> None:
    logger, log_path = create_command_logger(
        command_name="match",
        log_dir=tmp_path,
        run_id="run-1",
        log_level="INFO",
    )
    sink = LegacyLogEventSink(logger=logger, run_id="run-1")

    sink.emit(
        level=logging.INFO,
        event="bootstrap.start",
        payload={"dataset": "organizations", "require_target": True},
    )

    contents = log_path and open(log_path, encoding="utf-8").read()
    assert "comp=topology" in contents
    assert "event=bootstrap.start" in contents
    assert "dataset=organizations" in contents
    assert "require_target=true" in contents


def test_create_command_logger_skips_console_mirror_when_disabled(tmp_path) -> None:
    buffer = io.StringIO()
    logger, _ = create_command_logger(
        command_name="match",
        log_dir=tmp_path,
        run_id="run-1",
        log_level="INFO",
        mirror_to_console=False,
        console_stream=buffer,
    )

    logger.info("silent console", extra={"runId": "run-1", "component": "test"})

    assert buffer.getvalue() == ""


def test_create_command_logger_mirrors_to_original_console_stream(tmp_path) -> None:
    buffer = io.StringIO()
    logger, _ = create_command_logger(
        command_name="match",
        log_dir=tmp_path,
        run_id="run-1",
        log_level="INFO",
        mirror_to_console=True,
        console_stream=buffer,
    )

    logger.info("mirrored", extra={"runId": "run-1", "component": "test"})

    assert "mirrored" in buffer.getvalue()


def test_console_mirror_drops_captured_stdout_stderr(tmp_path) -> None:
    buffer = io.StringIO()
    logger, _ = create_command_logger(
        command_name="match",
        log_dir=tmp_path,
        run_id="run-1",
        log_level="INFO",
        mirror_to_console=True,
        console_stream=buffer,
    )

    # Перехваченный stdout/stderr уже выведен напрямую через TeeStream — на консоль не зеркалим.
    logger.info("captured noise", extra={"runId": "run-1", "component": "stdout"})
    logger.error("captured err", extra={"runId": "run-1", "component": "stderr"})
    # Структурное событие проходит.
    logger.info("topology event", extra={"runId": "run-1", "component": "topology"})

    mirrored = buffer.getvalue()
    assert "topology event" in mirrored
    assert "captured noise" not in mirrored
    assert "captured err" not in mirrored
