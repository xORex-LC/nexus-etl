from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, Any

from connector.domain.error_codes import ErrorCode


@dataclass(frozen=True)
class TargetPageResult:
    """
    Назначение:
        Нормализованный результат чтения страницы из целевой системы.

    Контракт:
        - ok=True -> items обязателен (список)
        - ok=False -> items=None и заполнены error_* поля
    """

    ok: bool
    page: int
    items: list[dict[str, Any]] | None
    error_code: ErrorCode | None = None
    error_message: str | None = None
    error_details: dict[str, Any] | None = None


class TargetPagedReaderProtocol(Protocol):
    """
    Назначение/ответственность:
        Порт чтения постраничных данных из целевой системы.
    Взаимодействия:
        Используется cache-refresh usecase; реализации скрывают транспорт и формат API.
    """

    def iter_pages(
        self,
        path: str,
        page_size: int,
        max_pages: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterable[TargetPageResult]:
        """
        Назначение:
            Итеративно возвращать страницы данных.
        Контракт:
            - Возвращает последовательность TargetPageResult без исключений наружу.
        """
        ...
