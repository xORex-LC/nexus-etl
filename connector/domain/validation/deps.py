from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from connector.domain.ports.lookups import IdentityLookupProtocol, OrgLookupProtocol, UserLookupProtocol

@dataclass
class ValidationDependencies:
    """
    Назначение:
        Описывает внешние зависимости валидатора (кэши/репозитории), чтобы
        отделить валидацию от конкретной реализации хранилища.

    Инварианты:
        - Все поля могут быть None, если конкретная проверка не нужна.
        - Объекты реализуют Protocol из protocols_lookup.py.
    """

    org_lookup: OrgLookupProtocol | None = None
    user_lookup: UserLookupProtocol | None = None
    matchkey_lookup: IdentityLookupProtocol | None = None

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
