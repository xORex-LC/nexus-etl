from __future__ import annotations

import logging
from pathlib import Path

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

    def __init__(self, runId: str, defaultComponent: str = "core"):
        super().__init__()
        self.runId = runId
        self.defaultComponent = defaultComponent

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "runId"):
            record.runId = self.runId
        if not hasattr(record, "component"):
            record.component = self.defaultComponent
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

    def __init__(self, logger: logging.Logger, level: int, runId: str, component: str):
        self.logger = logger
        self.level = level
        self.runId = runId
        self.component = component
        self.buffer = ""

    def write(self, s: str) -> int:
        if not s:
            return 0
        self.buffer += s
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                self.logger.log(self.level, line.rstrip(), extra={"runId": self.runId, "component": self.component})
        return len(s)

    def flush(self) -> None:
        if self.buffer.strip():
            self.logger.log(self.level, self.buffer.rstrip(), extra={"runId": self.runId, "component": self.component})
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

def mapLogLevel(levelName: str) -> int:
    """
    Назначение:
        Преобразует строковый уровень логирования в logging level.

    Входные данные:
        levelName: str
            ERROR|WARN|INFO|DEBUG

    Выходные данные:
        int
    """
    value = (levelName or "").strip().upper()
    if value == "ERROR":
        return logging.ERROR
    if value == "WARN":
        return logging.WARNING
    if value == "INFO":
        return logging.INFO
    if value == "DEBUG":
        return logging.DEBUG
    raise ValueError(f"Unsupported log level: {levelName}")

def createCommandLogger(commandName: str, logDir: str, runId: str, logLevel: str) -> tuple[logging.Logger, str]:
    """
    Назначение:
        Создаёт логгер для конкретной команды и возвращает путь к log-файлу.

    Входные данные:
        commandName: str
        logDir: str
        runId: str
        logLevel: str

    Выходные данные:
        (logger, logFilePath)
    """
    Path(logDir).mkdir(parents=True, exist_ok=True)

    logFilePath = str(Path(logDir) / f"{commandName}_{runId}.log")

    loggerName = f"syncEmployees.{commandName}.{runId}"
    logger = logging.getLogger(loggerName)
    logger.handlers.clear()
    logger.propagate = False

    level = mapLogLevel(logLevel)
    logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s runId=%(runId)s comp=%(component)s msg=%(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    fileHandler = logging.FileHandler(logFilePath, encoding="utf-8")
    fileHandler.setLevel(level)
    fileHandler.setFormatter(formatter)
    fileHandler.addFilter(EnsureFieldsFilter(runId=runId))
    logger.addHandler(fileHandler)

    return logger, logFilePath

def logEvent(logger: logging.Logger, level: int, runId: str, component: str, message: str) -> None:
    """
    Назначение:
        Унифицированная запись событий с runId/component.

    Входные данные:
        logger: logging.Logger
        level: int
        runId: str
        component: str
        message: str
    """
    logger.log(level, message, extra={"runId": runId, "component": component})