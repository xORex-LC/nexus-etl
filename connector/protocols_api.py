from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class ApiClientProtocol(Protocol):
    """
    Назначение:
        Общий контракт для HTTP-клиента Ankey API.

    Контракт:
        - getJson(path, params) -> Any
        - getPagedItems(path, pageSize, maxPages) -> iterator
    """

    def getJson(self, path: str, params: dict[str, Any] | None = None) -> Any: ...
    def getPagedItems(self, path: str, pageSize: int, maxPages: int) -> Any: ...

@runtime_checkable
class UserApiProtocol(Protocol):
    """
    Назначение:
        Контракт для операций над пользователями в Ankey API.
    """

    def upsertUser(self, resourceId: str, payload: dict[str, Any]) -> tuple[int, Any]: ...

__all__ = ["ApiClientProtocol", "UserApiProtocol"]
