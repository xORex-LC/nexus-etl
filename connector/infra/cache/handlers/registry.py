from __future__ import annotations

from connector.infra.cache.handlers.base import CacheDatasetHandler


class CacheHandlerRegistry:
    """
    Назначение/ответственность:
        Реестр обработчиков кэша по датасетам.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, CacheDatasetHandler] = {}

    def register(self, handler: CacheDatasetHandler) -> None:
        self._handlers[handler.dataset] = handler

    def get(self, dataset: str) -> CacheDatasetHandler:
        if dataset not in self._handlers:
            raise ValueError(f"Unsupported cache dataset: {dataset}")
        return self._handlers[dataset]

    def list(self) -> list[CacheDatasetHandler]:
        return list(self._handlers.values())
