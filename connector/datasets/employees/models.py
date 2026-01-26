from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EmployeesRowPublic:
    """
    Назначение:
        Публичная форма строки employees без секретов (sink-shape).
    """

    email: str | None
    last_name: str | None
    first_name: str | None
    middle_name: str | None
    is_logon_disable: bool | None
    user_name: str | None
    phone: str | None
    personnel_number: str | None
    manager_id: str | int | None
    organization_id: int | None
    position: str | None
    avatar_id: str | None
    usr_org_tab_num: str | None
    resource_id: str | None = None
