from __future__ import annotations

from datetime import datetime, timezone

def get_now_iso() -> str:
    """
    Назначение:
        Возвращает текущее время в ISO 8601 с timezone.

    Выходные данные:
        str
            Например: 2026-01-11T18:22:10+01:00
    """
    return datetime.now().astimezone().isoformat()

def get_utc_now_iso() -> str:
    """
    Назначение:
        Возвращает текущее время в UTC ISO 8601.

    Выходные данные:
        str
            Например: 2026-01-11T17:22:10+00:00
    """
    return datetime.now(timezone.utc).isoformat()

def get_duration_ms(start_monotonic: float, end_monotonic: float) -> int:
    """
    Назначение:
        Считает длительность в миллисекундах по monotonic timestamps.

    Входные данные:
        start_monotonic: float
        end_monotonic: float

    Выходные данные:
        int
            Длительность в миллисекундах.
    """
    return int((end_monotonic - start_monotonic) * 1000)