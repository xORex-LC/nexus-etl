from __future__ import annotations

from datetime import datetime, timezone


def getNowIso() -> str:
    """
    Назначение:
        Возвращает текущее время в ISO 8601 с timezone.

    Выходные данные:
        str
            Например: 2026-01-11T18:22:10+01:00
    """
    return datetime.now().astimezone().isoformat()


def getUtcNowIso() -> str:
    """
    Назначение:
        Возвращает текущее время в UTC ISO 8601.

    Выходные данные:
        str
            Например: 2026-01-11T17:22:10+00:00
    """
    return datetime.now(timezone.utc).isoformat()


def getDurationMs(startMonotonic: float, endMonotonic: float) -> int:
    """
    Назначение:
        Считает длительность в миллисекундах по monotonic timestamps.

    Входные данные:
        startMonotonic: float
        endMonotonic: float

    Выходные данные:
        int
            Длительность в миллисекундах.
    """
    return int((endMonotonic - startMonotonic) * 1000)