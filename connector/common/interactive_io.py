"""Interactive IO gate — координация prompt-режима и console observability

Модуль хранит минимальное process-local состояние, которое сообщает runtime,
что команда временно вошла в интерактивный prompt-режим. В этот момент console
mirror и stream-capture должны замолчать, чтобы не вмешиваться в диалог с
оператором.

Responsibilities:
    - Держать reentrant-счётчик активных интерактивных секций.
    - Отдавать context manager для временного подавления console/capture mirror.
    - Быть безопасным для повторных вложенных prompt-вызовов.

Out of scope:
    - Самостоятельный ввод значений у пользователя.
    - Конфигурация logging handlers или маршрутизация логов.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock


class InteractiveIoGate:
    """Координировать временное подавление console/capture mirror для prompt-ов.

    Gate не знает, кто именно запрашивает ввод. Он только даёт общий флаг
    "сейчас идёт интерактивная секция", который используют console sink и
    stream-capture, чтобы не логировать prompt-текст обратно в терминал.

    Invariants:
        - Счётчик активных секций никогда не уходит в отрицательные значения.
        - Вложенные prompt-секции поддерживаются через reentrant counter.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._active_depth = 0

    @contextmanager
    def suppress_observability_mirror(self) -> Iterator[None]:
        """Временно пометить поток выполнения как интерактивный prompt-режим."""
        with self._lock:
            self._active_depth += 1
        try:
            yield
        finally:
            with self._lock:
                self._active_depth = max(0, self._active_depth - 1)

    def is_active(self) -> bool:
        """Вернуть `True`, если сейчас активна хотя бы одна prompt-секция."""
        with self._lock:
            return self._active_depth > 0


__all__ = ["InteractiveIoGate"]
