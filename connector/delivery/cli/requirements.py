from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Requirements:
    """
    Назначение:
        Декларативные требования команды к окружению/опциям.
    """

    requires_source: bool = False
    requires_api: bool = False
    requires_cache: bool = False
    requires_secrets: bool = False
    requires_dataset: bool = False
    requires_vault_init: bool = False
    requires_dictionaries: bool = False
