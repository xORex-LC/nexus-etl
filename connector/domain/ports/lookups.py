from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from connector.domain.models import MatchResult

@runtime_checkable
class OrgLookupProtocol(Protocol):
    """
    Назначение:
        Абстракция для получения организаций при валидации.

    Контракт:
        - get_org_by_id(ouid: int) -> dict | None
            Возвращает словарь организации или None, если не найдено.
    """

    def get_org_by_id(self, ouid: int) -> dict[str, Any] | None: ...

@runtime_checkable
class UserLookupProtocol(Protocol):
    """
    Назначение:
        Абстракция для поиска пользователя при валидации (например, менеджера).

    Контракт:
        - get_user_by_id(user_id: int) -> dict | None
            Возвращает словарь пользователя или None, если не найдено.
    """

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None: ...

@runtime_checkable
class MatchKeyLookupProtocol(Protocol):
    """
    Назначение:
        Абстракция для поиска пользователя по match_key при глобальных проверках.

    Контракт:
        - match_by_key(match_key: str, include_deleted: bool) -> MatchResult
            Возвращает типизированный результат сопоставления.
    """

    def match_by_key(self, match_key: str, include_deleted: bool) -> MatchResult: ...

__all__ = ["OrgLookupProtocol", "UserLookupProtocol", "MatchKeyLookupProtocol", "MatchResult"]
