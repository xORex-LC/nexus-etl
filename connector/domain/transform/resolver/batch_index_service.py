"""
Назначение:
    In-memory реализация IBatchIndexService.

    InMemoryBatchIndexService хранит batch-индекс resolved-id,
    построенный ResolveContextStage, и предоставляет его ResolveStage
    per-record во время resolve-прохода.

Жизненный цикл:
    - Singleton в рамках одного PipelineRunContext.
    - set_index() вызывается ровно один раз за прогон (в ResolveContextStage).
    - get() вызывается N раз (по числу записей в ResolveStage).
    - При следующем прогоне set_index() перезаписывает индекс атомарно.
"""

from __future__ import annotations


class InMemoryBatchIndexService:
    """
    Назначение:
        In-memory batch-индекс: `{lookup_key: [resolved_id, ...]}`.

    Инварианты:
        - get() бросает RuntimeError если set_index() не вызывался.
        - set_index() атомарно заменяет предыдущий индекс.
    """

    def __init__(self) -> None:
        self._index: dict[str, list[str]] | None = None

    def set_index(self, index: dict[str, list[str]]) -> None:
        self._index = index

    def get(self) -> dict[str, list[str]]:
        if self._index is None:
            raise RuntimeError("IBatchIndexService.get() called before set_index()")
        return self._index


__all__ = ["InMemoryBatchIndexService"]
