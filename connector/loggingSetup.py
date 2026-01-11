from __future__ import annotations

import logging
from pathlib import Path
from typing import TextIO


class StdStreamToLogger(TextIO):
    """
    Назначение:
        Перехват stdout/stderr и отправка текста в logging.
        Требование ТЗ: транслировать stdout/stderr в лог файл.

    Входные данные:
        logger: logging.Logger
            Логгер команды.
        level: int
            Уровень логирования для перенаправленного текста.

    Выходные данные:
        Объект-стрим, совместимый с sys.stdout/sys.stderr.
    """

    def __init__(self, logger: logging.Logger, level: int):
        self.logger = logger
        self.level = level
        self.buffer = ""

    def write(self, s: str) -> int:
        if not s:
            return 0
        self.buffer += s
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                self.logger.log(self.level, line.rstrip())
        return len(s)

    def flush(self) -> None:
        if self.buffer.strip():
            self.logger.log(self.level, self.buffer.rstrip())
        self.buffer = ""


def mapLogLevel(levelName: str) -> int:
    """
    Назначение:
        Преобразует строковый уровень логирования в logging level.

    Входные данные:
        levelName: str
            ERROR|WARN|INFO|DEBUG

    Выходные данные:
        int
            logging.ERROR / logging.WARNING / logging.INFO / logging.DEBUG
    """
    value = levelName.strip().upper()
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
            Например: "import", "validate", "check-api", "cache-refresh"
        logDir: str
            Каталог логов.
        runId: str
            Идентификатор запуска.
        logLevel: str
            ERROR/WARN/INFO/DEBUG

    Выходные данные:
        (logger, logFilePath)

    Алгоритм:
        - Создать файл: <logDir>/<commandName>_<runId>.log
        - Добавить FileHandler с форматером, включающим runId.
        - Установить уровень логирования.
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
    logger.addHandler(fileHandler)

    return logger, logFilePath


def logEvent(logger: logging.Logger, level: int, runId: str, component: str, message: str) -> None:
    """
    Назначение:
        Унифицированная запись событий с обязательными полями runId/component.

    Входные данные:
        logger: logging.Logger
        level: int
        runId: str
        component: str
        message: str

    Выходные данные:
        None
    """
    logger.log(level, message, extra={"runId": runId, "component": component})