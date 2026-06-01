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

class StdStreamToLogger:
    """
    Назначение:
        Перехват stdout/stderr и логирование построчно.

    Входные данные:
        logger: logging.Logger
        level: int
        runId: str
        component: str
            Обычно 'stdout' или 'stderr'
    """

    def __init__(self, logger: logging.Logger, level: int, run_id: str, component: str):
        self.logger = logger
        self.level = level
        self.run_id = run_id
        self.component = component
        self.buffer = ""

    def write(self, s: str) -> int:
        if not s:
            return 0
        self.buffer += s
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                self.logger.log(self.level, line.rstrip(), extra={"runId": self.run_id, "component": self.component})
        return len(s)

    def flush(self) -> None:
        if self.buffer.strip():
            self.logger.log(self.level, self.buffer.rstrip(), extra={"runId": self.run_id, "component": self.component})
        self.buffer = ""

class TeeStream:
    """
    Назначение:
        Дублирует вывод: пишет в оригинальный stream и в stream-логгер.

    Входные данные:
        primary:
            Оригинальный sys.stdout/sys.stderr
        secondary:
            Объект, совместимый с stream (StdStreamToLogger)
    """

    def __init__(self, primary, secondary):
        self.primary = primary
        self.secondary = secondary

    def write(self, s: str) -> int:
        a = self.primary.write(s)
        self.secondary.write(s)
        return a

    def flush(self) -> None:
        self.primary.flush()
        self.secondary.flush()

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
