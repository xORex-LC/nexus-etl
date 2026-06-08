"""Structlog runtime — процессорная конфигурация, stderr/file sinks.

Модуль реализует новую prod-модель логирования для observability. Здесь
собираются structlog processors, stdlib bridge для foreign-логов и файловый
daily+size sink. Он остаётся infra-слоем: orchestrator только инициализирует
runtime и получает готовый logger/session, не зная деталей handler stack.

Границы ответственности:
    - Конфигурировать structlog и stdlib bridge один раз на runtime-экземпляр.
    - Создавать stderr/file handler stack с единым JSON/text renderer.
    - Выдавать component-aware structlog logger для команд.

Вне ответственности:
    - Привязка bind/clear contextvars в CLI orchestrator.
    - Оркестрация report/plan artifact lifecycle.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import socket
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, TextIO

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars
from structlog.processors import JSONRenderer
from structlog.tracebacks import ExceptionDictTransformer
from structlog.stdlib import ProcessorFormatter

from connector.common.interactive_io import InteractiveIoGate
from connector.common.observability import ObservabilityLayout, ServiceComponent
from connector.config.models import LoggingConfig, LogLevelName
from .redaction import LogRedactionEngine

if TYPE_CHECKING:
    from connector.common.observability import ComponentIdentity

_LOG_SCHEMA_VERSION = "1.0"
_HOSTNAME = socket.gethostname()
_PID = os.getpid()


@dataclass(frozen=True)
class LoggingRuntimeMeta:
    """Дополнительные runtime-поля, общие для всех записей данного runtime."""

    app_version: str | None = None
    git_rev: str | None = None


def _coerce_log_level(level_name: str) -> int:
    normalized = level_name.strip().upper()
    mapping = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported log level: {level_name}") from exc


def _add_schema_version(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    event_dict.setdefault("schema_version", _LOG_SCHEMA_VERSION)
    return event_dict


def _build_runtime_meta_processor(
    runtime_meta: LoggingRuntimeMeta,
) -> Callable[[Any, str, dict[str, Any]], dict[str, Any]]:
    def _add_runtime_meta(
        _logger: Any,
        _method_name: str,
        event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        event_dict.setdefault("host", _HOSTNAME)
        event_dict.setdefault("pid", _PID)
        if runtime_meta.app_version is not None:
            event_dict.setdefault("app_version", runtime_meta.app_version)
        if runtime_meta.git_rev is not None:
            event_dict.setdefault("git_rev", runtime_meta.git_rev)
        return event_dict

    return _add_runtime_meta


class _JsonTextRenderer:
    """Рендерить event_dict в logfmt-подобный текст для файлового sink."""

    def __call__(
        self, _logger: Any, _method_name: str, event_dict: dict[str, Any]
    ) -> str:
        rendered_parts: list[str] = []
        for key, value in event_dict.items():
            rendered_parts.append(f"{key}={self._format_value(value)}")
        return " ".join(rendered_parts)

    def _format_value(self, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            if value == "":
                return '""'
            if any(char.isspace() for char in value) or "=" in value:
                return json.dumps(value, ensure_ascii=False)
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True)


class _InteractiveConsoleSuppressFilter(logging.Filter):
    """Подавлять console mirror, пока команда находится в интерактивном prompt-режиме."""

    def __init__(self, interactive_io_gate: InteractiveIoGate) -> None:
        super().__init__()
        self._interactive_io_gate = interactive_io_gate

    def filter(self, record: logging.LogRecord) -> bool:
        _ = record
        return not self._interactive_io_gate.is_active()


class DailySizeRotatingFileHandler(logging.Handler):
    """Писать в дневной файл компонента и роллить его по размеру.

    Invariants:
        - Активный файл всегда называется `<date>_<component>.log`.
        - Size-roll создаёт бэкапы `<date>_<component>.<n>.log` внутри того же каталога.
        - Все операции открытия/ротации сериализуются локом handler-а.
    """

    terminator = "\n"

    def __init__(
        self,
        *,
        layout: ObservabilityLayout,
        component: ServiceComponent | ComponentIdentity,
        max_bytes: int,
        backup_count: int,
        clock: Callable[[], datetime] | None = None,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__()
        self._layout = layout
        self._component = component
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._encoding = encoding
        self._stream: TextIO | None = None
        self._current_path: Path | None = None
        self._lock_stream: TextIO | None = None
        self._lock = threading.RLock()

    @property
    def current_path(self) -> Path | None:
        """Вернуть путь к текущему активному файлу, если он уже открыт."""
        return self._current_path

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            with self._lock:
                active_path = self._layout.log_file(self._component, now=self._clock())
                with self._acquire_process_lock(active_path):
                    self._ensure_stream(active_path)
                    self._maybe_roll_by_size(active_path, message)
                    assert self._stream is not None
                    self._stream.write(message + self.terminator)
                    self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            if self._lock_stream is not None:
                self._lock_stream.close()
                self._lock_stream = None
            self._current_path = None
        super().close()

    def _ensure_stream(self, active_path: Path) -> None:
        if self._current_path == active_path and self._stream is not None:
            return
        if self._stream is not None:
            self._stream.close()
        active_path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = active_path.open("a", encoding=self._encoding)
        self._current_path = active_path

    def _maybe_roll_by_size(self, active_path: Path, message: str) -> None:
        if self._max_bytes <= 0 or self._stream is None:
            return
        current_size = active_path.stat().st_size if active_path.exists() else 0
        projected_size = current_size + len(
            (message + self.terminator).encode(self._encoding)
        )
        if current_size == 0 or projected_size <= self._max_bytes:
            return
        self._stream.close()
        self._rotate_size(active_path)
        self._stream = active_path.open("a", encoding=self._encoding)
        self._current_path = active_path

    def _rotate_size(self, active_path: Path) -> None:
        if self._backup_count > 0:
            for index in range(self._backup_count, 0, -1):
                source = self._backup_path(active_path, index)
                target = self._backup_path(active_path, index + 1)
                if target.exists():
                    target.unlink()
                if source.exists():
                    source.replace(target)
            first_backup = self._backup_path(active_path, 1)
            if first_backup.exists():
                first_backup.unlink()
            if active_path.exists():
                active_path.replace(first_backup)
            overflow = self._backup_path(active_path, self._backup_count + 1)
            if overflow.exists():
                overflow.unlink()
            return
        if active_path.exists():
            active_path.unlink()

    def _backup_path(self, active_path: Path, index: int) -> Path:
        return active_path.with_name(f"{active_path.stem}.{index}{active_path.suffix}")

    @contextlib.contextmanager
    def _acquire_process_lock(self, active_path: Path):
        lock_path = active_path.with_name(f"{active_path.name}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self._lock_stream is None or Path(self._lock_stream.name) != lock_path:
            if self._lock_stream is not None:
                self._lock_stream.close()
            self._lock_stream = lock_path.open("a+", encoding="utf-8")
        assert self._lock_stream is not None
        fcntl.flock(self._lock_stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(self._lock_stream.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class StructlogHandlerStack:
    """Держать handler stack, сконфигурированный для structlog runtime."""

    console_handler: logging.Handler | None
    file_handler: DailySizeRotatingFileHandler | None
    root_logger: logging.Logger

    def close(self) -> None:
        """Отвязать handlers от root logger и закрыть ресурсы."""
        handlers = [
            handler
            for handler in (self.console_handler, self.file_handler)
            if handler is not None
        ]
        for handler in handlers:
            self.root_logger.removeHandler(handler)
            handler.close()


@dataclass(frozen=True)
class StructuredLoggingRuntime:
    """Инкапсулировать новый structlog runtime для изолированных фаз observability.

    Runtime владеет только конфигурацией логирования. Он не знает о CLI
    orchestration, но умеет выдавать service-component логгер и clean-up для
    handler stack, чтобы тесты и будущий DI `Resource` могли управлять lifecycle.
    """

    config: LoggingConfig
    layout: ObservabilityLayout
    component: ServiceComponent
    handler_stack: StructlogHandlerStack
    redaction_engine: LogRedactionEngine
    runtime_meta: LoggingRuntimeMeta = LoggingRuntimeMeta()

    def get_logger(
        self,
        component: ServiceComponent,
        *,
        logger_name: str | None = None,
    ) -> structlog.stdlib.BoundLogger:
        """Вернуть component-aware logger с filtering wrapper по уровню компонента."""
        stdlib_logger = logging.getLogger(logger_name or f"nexus.{component.value}")
        stdlib_logger.setLevel(logging.NOTSET)
        wrapper_class = structlog.make_filtering_bound_logger(
            self._level_for_component(component)
        )
        return structlog.wrap_logger(
            stdlib_logger,
            wrapper_class=wrapper_class,
            processors=_build_structlog_processors(self.runtime_meta),
            cache_logger_on_first_use=False,
        ).bind(component=component.value)

    def current_log_file_path(self) -> str | None:
        """Вернуть активный log file path либо ожидаемый путь текущего дня."""
        if self.handler_stack.file_handler is None:
            return None
        current = self.handler_stack.file_handler.current_path
        if current is not None:
            return str(current)
        return str(self.layout.log_file(self.component))

    def close(self) -> None:
        """Закрыть handler stack и сбросить contextvars."""
        self.handler_stack.close()
        clear_observability_context()

    def _level_for_component(self, component: ServiceComponent) -> int:
        override = self.config.components.get(component)
        level_name: LogLevelName = (
            override.level if override is not None else self.config.level
        )
        return _coerce_log_level(level_name)


def bind_observability_context(
    *,
    run_id: str,
    pipeline_run_id: str,
    component: ServiceComponent,
    dataset: str | None = None,
) -> None:
    """Привязать сквозной observability-контекст через contextvars."""
    payload: dict[str, Any] = {
        "run_id": run_id,
        "pipeline_run_id": pipeline_run_id,
        "component": component.value,
    }
    if dataset is not None:
        payload["dataset"] = dataset
    bind_contextvars(**payload)


def clear_observability_context() -> None:
    """Сбросить contextvars после завершения выполнения команды."""
    clear_contextvars()


def build_structured_logging_runtime(
    *,
    config: LoggingConfig,
    layout: ObservabilityLayout,
    redaction_engine: LogRedactionEngine,
    component: ServiceComponent,
    stderr_stream: TextIO | None = None,
    root_logger_name: str = "",
    clock: Callable[[], datetime] | None = None,
    app_version: str | None = None,
    git_rev: str | None = None,
    interactive_io_gate: InteractiveIoGate | None = None,
) -> StructuredLoggingRuntime:
    """Сконфигурировать structlog runtime для одного service-component."""
    runtime_meta = LoggingRuntimeMeta(app_version=app_version, git_rev=git_rev)
    root_logger = logging.getLogger(root_logger_name)
    root_logger.handlers.clear()
    root_logger.setLevel(logging.NOTSET)
    root_logger.propagate = False

    handler_stack = _build_handler_stack(
        config=config,
        layout=layout,
        redaction_engine=redaction_engine,
        component=component,
        root_logger=root_logger,
        stderr_stream=stderr_stream,
        clock=clock,
        runtime_meta=runtime_meta,
        interactive_io_gate=interactive_io_gate,
    )
    structlog.configure(
        processors=_build_structlog_processors(runtime_meta),
        wrapper_class=structlog.make_filtering_bound_logger(
            _coerce_log_level(config.level)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    return StructuredLoggingRuntime(
        config=config,
        layout=layout,
        component=component,
        handler_stack=handler_stack,
        redaction_engine=redaction_engine,
        runtime_meta=runtime_meta,
    )


def _build_structlog_processors(runtime_meta: LoggingRuntimeMeta) -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_schema_version,
        _build_runtime_meta_processor(runtime_meta),
        ProcessorFormatter.wrap_for_formatter,
    ]


def _build_formatter(
    *,
    redaction_engine: LogRedactionEngine,
    renderer: Any,
    runtime_meta: LoggingRuntimeMeta,
) -> ProcessorFormatter:
    return ProcessorFormatter(
        foreign_pre_chain=_build_structlog_processors(runtime_meta)[:-1],
        processors=[
            structlog.processors.ExceptionRenderer(ExceptionDictTransformer()),
            redaction_engine.processor,
            ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )


def _build_handler_stack(
    *,
    config: LoggingConfig,
    layout: ObservabilityLayout,
    redaction_engine: LogRedactionEngine,
    component: ServiceComponent,
    root_logger: logging.Logger,
    stderr_stream: TextIO | None,
    clock: Callable[[], datetime] | None,
    runtime_meta: LoggingRuntimeMeta,
    interactive_io_gate: InteractiveIoGate | None,
) -> StructlogHandlerStack:
    console_handler: logging.Handler | None = None
    file_handler: DailySizeRotatingFileHandler | None = None

    if config.sinks.console.enabled:
        console_stream = (
            stderr_stream
            if stderr_stream is not None
            else _resolve_console_stream(config.sinks.console.stream)
        )
        console_handler = logging.StreamHandler(console_stream)
        console_handler.setLevel(logging.NOTSET)
        console_handler.setFormatter(
            _build_formatter(
                redaction_engine=redaction_engine,
                renderer=JSONRenderer()
                if config.sinks.console.format == "json"
                else _JsonTextRenderer(),
                runtime_meta=runtime_meta,
            )
        )
        if interactive_io_gate is not None:
            console_handler.addFilter(
                _InteractiveConsoleSuppressFilter(interactive_io_gate)
            )
        root_logger.addHandler(console_handler)

    if config.sinks.file.enabled:
        file_handler = DailySizeRotatingFileHandler(
            layout=layout,
            component=component,
            max_bytes=config.sinks.file.max_bytes,
            backup_count=config.sinks.file.retention_backups,
            clock=clock,
        )
        file_handler.setLevel(logging.NOTSET)
        file_handler.setFormatter(
            _build_formatter(
                redaction_engine=redaction_engine,
                renderer=JSONRenderer()
                if config.sinks.file.format == "json"
                else _JsonTextRenderer(),
                runtime_meta=runtime_meta,
            )
        )
        root_logger.addHandler(file_handler)

    return StructlogHandlerStack(
        console_handler=console_handler,
        file_handler=file_handler,
        root_logger=root_logger,
    )


def _resolve_console_stream(stream_name: str) -> TextIO:
    if stream_name == "stderr":
        return sys.stderr
    if stream_name == "stdout":
        return sys.stdout
    raise ValueError(f"Unsupported console stream: {stream_name}")


__all__ = [
    "DailySizeRotatingFileHandler",
    "StructuredLoggingRuntime",
    "StructlogHandlerStack",
    "bind_observability_context",
    "build_structured_logging_runtime",
    "clear_observability_context",
]
