from __future__ import annotations

from typing import Protocol


class IdentityRepository(Protocol):
    """
    Назначение/ответственность:
        Доступ к identity_index (служебные ключи резолва).
    """

    def upsert_identity(self, dataset: str, identity_key: str, resolved_id: str) -> None: ...

    def find_candidates(self, dataset: str, identity_key: str) -> list[str]: ...
