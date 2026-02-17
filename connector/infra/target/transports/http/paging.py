"""Протокол и вспомогательные функции для HTTP-пагинации."""

from __future__ import annotations

from typing import Any, Protocol

from connector.infra.target.transports.http.request_builder import HttpRequest


class HttpPagingStrategy(Protocol):
    """
    Стратегия постраничного чтения для HTTP-транспорта.

    Контракт:
        - build_paged_request: добавляет в базовый запрос параметры конкретной
          страницы (номер, размер, cursor и т.д.) — не мутирует base_req.
        - extract_items: извлекает список элементов из тела ответа.
          Поднимает ValueError, если формат ответа не распознан.
    """

    def build_paged_request(
        self,
        base_req: HttpRequest,
        page: int,
        batch_size: int,
    ) -> HttpRequest: ...

    def extract_items(self, body: Any) -> list[Any]:
        """Вернуть список элементов из body. Raises: ValueError."""
        ...


