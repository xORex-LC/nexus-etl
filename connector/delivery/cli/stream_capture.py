"""CLI stream capture — перехват stdout/stderr с зеркалированием и redaction

Модуль хранит CLI-специфичную механику перехвата stdout/stderr. Он дублирует
строки в исходный stream и в logger, но сам не конфигурирует logging backend:
это остаётся в `infra/logging/`.

Responsibilities:
    - Захватывать stdout/stderr построчно без потери оригинального вывода.
    - Применять redaction к перехваченным строкам перед эмиссией в лог.
    - Сохранять семантику отсутствия задвоения console-mirror для stdout/stderr.

Out of scope:
    - Создание/конфигурация logger handlers.
    - Решение, какой логгер или какой уровень использовать для конкретной команды.
"""

from __future__ import annotations

import logging
from typing import TextIO

from connector.infra.logging.redaction import LogRedactionEngine


class DropCapturedStdStreamsFilter(logging.Filter):
    """Отсекать console-mirror для уже перехваченных stdout/stderr сообщений."""

    _CAPTURED_COMPONENTS = frozenset({"stdout", "stderr"})

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "component", None) not in self._CAPTURED_COMPONENTS


class StdStreamToLogger:
    """Писать в logger построчно при перехвате stdout/stderr.

    Класс остаётся совместимым с legacy stdlib logger call-sites: он вызывает
    `logger.log(..., extra={...})`, но добавляет redaction перед эмиссией.
    """

    def __init__(
        self,
        logger: logging.Logger,
        level: int,
        run_id: str,
        component: str,
        *,
        redaction_engine: LogRedactionEngine | None = None,
    ) -> None:
        self.logger = logger
        self.level = level
        self.run_id = run_id
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
        self.logger.log(
            self.level,
            sanitized,
            extra={"runId": self.run_id, "component": self.component},
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
    "DropCapturedStdStreamsFilter",
    "StdStreamToLogger",
    "TeeStream",
]
