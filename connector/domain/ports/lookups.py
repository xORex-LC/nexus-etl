from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from connector.domain.models import Identity, MatchResult, MatchStatus

@runtime_checkable
class LookupProtocol(Protocol):
    """
    Назначение:
        Унифицированный порт поиска сущностей в кэше/хранилище.
    """

    def get_by_id(self, entity: str, value: Any) -> dict[str, Any] | None: ...
    def match(self, identity: Identity, include_deleted: bool) -> MatchResult: ...

__all__ = ["LookupProtocol", "MatchResult", "MatchStatus", "Identity"]
