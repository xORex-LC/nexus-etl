"""Observability-порты topology — transport-neutral seam для runtime событий.

Определяет узкий sink-контракт, через который topology bootstrap и связанные
use case-слои публикуют lifecycle/build/readiness события. Порт не знает о
конкретном logging backend и допускает как legacy stdlib adapter, так и
будущий structured sink.

Зона ответственности:
    - Принимать topology runtime события с уровнем и именем event-а
    - Давать дешёвую проверку доступности DEBUG/INFO веток

Вне области ответственности:
    - Форматирование сообщений под конкретный backend
    - Хранение topology snapshots или report context
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class TopologyEventSink(Protocol):
    """Узкий runtime seam для topology lifecycle-событий."""

    def enabled(self, level: int) -> bool: ...

    def emit(
        self,
        *,
        level: int,
        event: str,
        payload: Mapping[str, Any],
    ) -> None: ...

