from __future__ import annotations

import getpass
from typing import Dict, Tuple

from connector.domain.ports.secrets import SecretProviderProtocol

Key = Tuple[str, str, str | None, int | None]


class PromptSecretProvider(SecretProviderProtocol):
    """
    Назначение:
        Интерктивный провайдер секретов через stdin (getpass), с кэшированием по ключу.
    Ограничения:
        - Требует TTY.
        - Не подходит для автоматических сценариев.
    """

    def __init__(self):
        self._cache: Dict[Key, str] = {}

    def get_secret(
        self,
        *,
        dataset: str,
        field: str,
        row_id: str | None = None,
        line_no: int | None = None,
        source_ref: dict | None = None,
        target_id: str | None = None,
        run_id: str | None = None,
    ) -> str | None:
        key: Key = (dataset, field, row_id, line_no)
        if key in self._cache:
            return self._cache[key]
        prompt = f"Enter secret for {dataset}.{field}"
        if row_id:
            prompt += f" (row {row_id})"
        try:
            value = getpass.getpass(prompt + ": ")
        except Exception:
            return None
        if value:
            self._cache[key] = value
            return value
        return None
