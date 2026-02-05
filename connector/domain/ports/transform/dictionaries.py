from __future__ import annotations

from typing import Any, Protocol


class DictionaryProviderPort(Protocol):
    """
    Назначение:
        Порт доступа к справочникам (static/temporal).
    """

    def lookup(self, dict_name: str, key: str, at: Any | None = None) -> list[dict[str, Any]]: ...
    def contains(self, dict_name: str, value: str, at: Any | None = None) -> bool: ...
    def canonicalize(self, dict_name: str, value: str, at: Any | None = None) -> list[dict[str, Any]]: ...


__all__ = ["DictionaryProviderPort"]
