from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NormalizedEmployeesRow:
    """
    Назначение:
        Нормализованная строка employees (типизированные значения).
    """
    # TODO(DSL): Transitional typed row. Remove when all stages use DSL/JSON schemas end-to-end.

    email: str | None
    last_name: str | None
    first_name: str | None
    middle_name: str | None
    is_logon_disable: bool | None
    user_name: str | None
    phone: str | None
    password: str | None
    personnel_number: str | None
    manager_id: str | int | None
    organization_id: int | str | None
    position: str | None
    avatar_id: str | None
    usr_org_tab_num: str | None
    target_id: str | None = None
