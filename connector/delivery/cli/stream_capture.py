"""CLI stream capture — перехват stdout/stderr с redaction.

Модуль хранит CLI-специфичную механику перехвата stdout/stderr. Он дублирует
строки в исходный stream и в logger, но сам не конфигурирует logging backend:
это остаётся в `infra/logging/`.

Границы ответственности:
    - Захватывать stdout/stderr построчно без потери оригинального вывода.
    - Применять redaction к перехваченным строкам перед эмиссией в лог.
    - Сохранять семантику отсутствия задвоения console-mirror для stdout/stderr.

Вне ответственности:
    - Создание/конфигурация logger handlers.
    - Решение, какой логгер или какой уровень использовать для конкретной команды.
"""

from __future__ import annotations

import logging
from typing import Any
from typing import TextIO

from connector.infra.logging.redaction import LogRedactionEngine


class StdStreamToLogger:
    """Писать в logger построчно при перехвате stdout/stderr.

    Класс эмитит перехваченные строки через native structlog API. Correlation
    fields (`run_id`, `pipeline_run_id`, `component`) приходят из contextvars.
    """

    def __init__(
        self,
        logger: Any,
        level: int,
        component: str,
        *,
        redaction_engine: LogRedactionEngine | None = None,
    ) -> None:
        self.logger = logger
        self.level = level
        self.component = component
        self.redaction_engine = redaction_engine
        self.buffer = ""

    def write(self, value: str) -> int:
        """Накопить входной текст и эмитить завершённые строки в лог."""
        if not value:
            return 0
        self.buffer += value
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self._emit_if_not_blank(line)
        return len(value)

    def flush(self) -> None:
        """Сбросить хвостовой буфер в лог, если там есть содержимое."""
        self._emit_if_not_blank(self.buffer)
        self.buffer = ""

    def _emit_if_not_blank(self, line: str) -> None:
        if not line.strip():
            return
        sanitized = self._redact(line.rstrip())
        _dispatch_log(
            self.logger,
            self.level,
            sanitized,
            captured_stream=self.component,
        )

    def _redact(self, line: str) -> str:
        if self.redaction_engine is None:
            return line
        return self.redaction_engine.redact_text(line)


class TeeStream:
    """Дублировать запись в исходный stream и во вторичный stream-capture."""

    def __init__(self, primary: TextIO, secondary: StdStreamToLogger) -> None:
        self.primary = primary
        self.secondary = secondary

    def write(self, value: str) -> int:
        written = self.primary.write(value)
        self.secondary.write(value)
        return written

    def flush(self) -> None:
        self.primary.flush()
        self.secondary.flush()


__all__ = [
    "StdStreamToLogger",
    "TeeStream",
]


def _dispatch_log(logger: Any, level: int, event: str, **fields: Any) -> None:
    """Эмитить событие в structlog-compatible logger по числовому уровню."""
    if level >= logging.CRITICAL:
        logger.critical(event, **fields)
    elif level >= logging.ERROR:
        logger.error(event, **fields)
    elif level >= logging.WARNING:
        logger.warning(event, **fields)
    elif level >= logging.INFO:
        logger.info(event, **fields)
    else:
        logger.debug(event, **fields)
