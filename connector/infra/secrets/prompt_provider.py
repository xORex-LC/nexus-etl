from __future__ import annotations

import contextlib
import getpass
from collections.abc import Callable
from typing import Dict, Tuple

from connector.common.interactive_io import InteractiveIoGate
from connector.domain.ports.secrets.provider import SecretProviderProtocol

Key = Tuple[str, str, str | None, int | None]
PromptFn = Callable[[str], str]


class PromptSecretProvider(SecretProviderProtocol):
    """
    Назначение:
        Интерктивный провайдер секретов через stdin (getpass), с кэшированием по ключу.
    Ограничения:
        - Требует TTY.
        - Не подходит для автоматических сценариев.
    """

    def __init__(
        self,
        *,
        prompt_secret: PromptFn | None = None,
        interactive_io_gate: InteractiveIoGate | None = None,
    ) -> None:
        self._cache: Dict[Key, str] = {}
        self._prompt_secret = prompt_secret or getpass.getpass
        self._interactive_io_gate = interactive_io_gate

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
            with self._prompt_gate():
                value = self._prompt_secret(prompt + ": ")
        except Exception:
            return None
        if value:
            self._cache[key] = value
            return value
        return None

    def _prompt_gate(self):
        if self._interactive_io_gate is None:
            return contextlib.nullcontext()
        return self._interactive_io_gate.suppress_observability_mirror()
