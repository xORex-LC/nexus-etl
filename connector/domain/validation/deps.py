from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from connector.domain.ports.lookups import LookupProtocol

@dataclass
class ValidationDependencies:
    """
    Назначение:
        Описывает внешние зависимости валидатора (кэши/репозитории), чтобы
        отделить валидацию от конкретной реализации хранилища.

    Инварианты:
        - Все поля могут быть None, если конкретная проверка не нужна.
        - Объекты реализуют LookupProtocol.
    """

    org_lookup: LookupProtocol | None = None
    user_lookup: LookupProtocol | None = None
    identity_lookup: LookupProtocol | None = None

@dataclass
class DatasetValidationState:
    """
    Назначение:
        Держатель состояния для глобальных проверок (уникальности и т.п.).

    Инварианты:
        - matchkey_seen и usr_org_tab_seen обновляются по мере обработки строк.
    """

    matchkey_seen: dict[str, int]
    usr_org_tab_seen: dict[str, int]
