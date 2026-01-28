from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from connector.datasets.employees.extract.models import EmployeesRowPublic


@dataclass(frozen=True)
class EmployeesMappingSpec:
    """
    Назначение:
        Схема маппинга employees (match_key, секреты).
    """

    match_key_fields: tuple[str, ...] = (
        "last_name",
        "first_name",
        "middle_name",
        "personnel_number",
    )
    required_fields: tuple[tuple[str, str], ...] = (
        ("email", "email"),
        ("last_name", "lastName"),
        ("first_name", "firstName"),
        ("middle_name", "middleName"),
        ("is_logon_disable", "isLogonDisable"),
        ("user_name", "userName"),
        ("phone", "phone"),
        ("password", "password"),
        ("personnel_number", "personnelNumber"),
        ("organization_id", "organization_id"),
        ("position", "position"),
        ("usr_org_tab_num", "usrOrgTabNum"),
    )
    secret_fields: tuple[str, ...] = ("password",)

    def get_match_key_parts(self, row: EmployeesRowPublic) -> list[str | None]:
        return [getattr(row, field, None) for field in self.match_key_fields]

    def collect_secret_candidates(self, values: Mapping[str, Any] | Any) -> dict[str, str]:
        candidates: dict[str, str] = {}
        for field in self.secret_fields:
            if isinstance(values, Mapping):
                value = values.get(field)
            else:
                value = getattr(values, field, None)
            if self._is_present(value):
                candidates[field] = str(value)
        return candidates

    @staticmethod
    def _is_present(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip() != ""
        return True
