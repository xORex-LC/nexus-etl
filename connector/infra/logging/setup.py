"""Legacy logging setup — совместимый stdlib adapter до полного switch-over на structlog

Модуль сохраняет текущий per-command logging API, который ещё используется
оркестратором и рядом команд. Новая structlog-модель живёт в соседних модулях
`infra/logging/runtime.py` и `delivery/cli/stream_capture.py`; здесь остаётся
только backward-compatible façade до поздней фазы миграции.

Responsibilities:
    - Поддерживать legacy `create_command_logger()`/`log_event()` call-sites.
    - Давать совместимый текстовый file+console logger без смены поведения.

Out of scope:
    - Новая structlog-конфигурация observability runtime.
    - Bind/clear contextvars и per-component observability layout.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TextIO

class EnsureFieldsFilter(logging.Filter):
    """
    Назначение:
        Гарантирует наличие полей runId и component в LogRecord,
        чтобы форматтер не падал KeyError.

    Входные данные:
        runId: str
            Идентификатор запуска.
        defaultComponent: str
            Компонент по умолчанию, если не задан.
    """

    def __init__(self, run_id: str, default_component: str = "core"):
        super().__init__()
        self.run_id = run_id
        self.default_component = default_component

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "runId"):
            record.runId = self.run_id
        if not hasattr(record, "component"):
            record.component = self.default_component
        return True

class DropCapturedStdStreamsFilter(logging.Filter):
    """
    Назначение:
        Не зеркалировать на консоль перехваченные stdout/stderr.

        Перехваченный вывод уже попадает в оригинальный stream напрямую через
        TeeStream. Без этого фильтра console-mirror handler печатал бы его второй
        раз (TeeStream -> StdStreamToLogger -> logger -> console_handler -> stream),
        давая дубль. Структурные события (comp=topology/core/...) проходят.
    """

    _CAPTURED_COMPONENTS = frozenset({"stdout", "stderr"})

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "component", None) not in self._CAPTURED_COMPONENTS


def map_log_level(level_name: str) -> int:
    """
    Назначение:
        Преобразует строковый уровень логирования в logging level.

    Входные данные:
        level_name: str
            ERROR|WARN|INFO|DEBUG

    Выходные данные:
        int
    """
    value = (level_name or "").strip().upper()
    if value == "ERROR":
        return logging.ERROR
    if value == "WARN":
        return logging.WARNING
    if value == "INFO":
        return logging.INFO
    if value == "DEBUG":
        return logging.DEBUG
    raise ValueError(f"Unsupported log level: {level_name}")

def create_command_logger(
    command_name: str,
    log_dir: str | Path,
    run_id: str,
    log_level: str,
    mirror_to_console: bool = False,
    console_stream: TextIO | None = None,
) -> tuple[logging.Logger, str]:
    """
    Назначение:
        Создаёт логгер для конкретной команды и возвращает путь к log-файлу.

    Входные данные:
        command_name: str
        log_dir: str
        run_id: str
        log_level: str

    Выходные данные:
        (logger, log_file_path)
    """
    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)

    log_file_path = str(log_dir_path / f"{command_name}_{run_id}.log")

    logger_name = f"nexus.{command_name}.{run_id}"
    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    logger.propagate = False
    logger.addFilter(EnsureFieldsFilter(run_id, "app"))

    level = map_log_level(log_level)
    logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s runId=%(runId)s comp=%(component)s msg=%(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(EnsureFieldsFilter(run_id=run_id))
    logger.addHandler(file_handler)

    if mirror_to_console:
        console_handler = logging.StreamHandler(console_stream)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(EnsureFieldsFilter(run_id=run_id))
        console_handler.addFilter(DropCapturedStdStreamsFilter())
        logger.addHandler(console_handler)

    return logger, log_file_path

def log_event(logger: logging.Logger, level: int, run_id: str, component: str, message: str) -> None:
    """
    Назначение:
        Унифицированная запись событий с runId/component.

    Входные данные:
        logger: logging.Logger
        level: int
        run_id: str
        component: str
        message: str
    """
    logger.log(level, message, extra={"runId": run_id, "component": component})


__all__ = ["DropCapturedStdStreamsFilter", "EnsureFieldsFilter", "create_command_logger", "log_event", "map_log_level"]
