"""
Назначение:
    Доменные порты кэша.
"""

from __future__ import annotations

from typing import Protocol


class IdentityRepository(Protocol):
    """
    Назначение/ответственность:
        Доступ к identity_index (служебные ключи резолва).
    """

    def upsert_identity(self, dataset: str, identity_key: str, resolved_id: str) -> None: ...

    def find_candidates(self, dataset: str, identity_key: str) -> list[str]: ...

    def set_runtime_state(
        self,
        scope: str,
        dataset: str,
        state_key: str,
        state_value: str,
    ) -> None: ...

    def get_runtime_state(
        self,
        scope: str,
        dataset: str,
        state_key: str,
    ) -> str | None: ...

    def clear_runtime_scope(self, scope: str) -> None: ...
