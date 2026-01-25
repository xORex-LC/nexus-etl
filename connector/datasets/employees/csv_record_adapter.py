from __future__ import annotations

from typing import Any

from connector.domain.models import CsvRow, ValidationErrorItem
from connector.domain.transform.source_record import SourceRecord
from connector.domain.transform.collect_result import CollectResult
from connector.datasets.employees.field_rules import FIELD_RULES


class EmployeesCsvRecordAdapter:
    """
    Назначение:
        Преобразует CsvRow сотрудников в SourceRecord с каноническими ключами.
    """

    def __init__(self, rules=FIELD_RULES) -> None:
        self.rules = rules

    def collect(self, csv_row: CsvRow) -> CollectResult:
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []
        values: dict[str, Any] = {}
        for rule in self.rules:
            values[rule.name] = rule.apply(csv_row.values, errors, warnings)

        record = SourceRecord(
            line_no=csv_row.file_line_no,
            record_id=f"line:{csv_row.file_line_no}",
            values=_to_canonical_keys(values),
        )
        return CollectResult(record=record, errors=errors, warnings=warnings)


def _to_canonical_keys(values: dict[str, Any]) -> dict[str, Any]:
    return {
        "email": values.get("email"),
        "last_name": values.get("lastName"),
        "first_name": values.get("firstName"),
        "middle_name": values.get("middleName"),
        "is_logon_disable": values.get("isLogonDisable"),
        "user_name": values.get("userName"),
        "phone": values.get("phone"),
        "password": values.get("password"),
        "personnel_number": values.get("personnelNumber"),
        "manager_id": values.get("managerId"),
        "organization_id": values.get("organization_id"),
        "position": values.get("position"),
        "avatar_id": values.get("avatarId"),
        "usr_org_tab_num": values.get("usrOrgTabNum"),
    }
