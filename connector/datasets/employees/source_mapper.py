from __future__ import annotations

from typing import Any

from connector.domain.models import CsvRow, RowRef, ValidationErrorItem, EmployeeInput
from connector.domain.ports.sources import SourceMapper
from connector.domain.transform.map_result import MapResult
from connector.domain.transform.match_key import MatchKey, build_delimited_match_key
from connector.domain.validation.row_rules import FIELD_RULES
from connector.datasets.employees.models import EmployeesRowPublic


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    return str(value).strip() != ""


def to_employee_input(row: EmployeesRowPublic, secret_candidates: dict[str, str]) -> EmployeeInput:
    """
    Назначение:
        Временный адаптер в legacy EmployeeInput.
    """
    # TODO: remove legacy EmployeeInput once pipeline is migrated to public rows.
    password = secret_candidates.get("password")
    return EmployeeInput(
        email=row.email,
        last_name=row.last_name,
        first_name=row.first_name,
        middle_name=row.middle_name,
        is_logon_disable=row.is_logon_disable,
        user_name=row.user_name,
        phone=row.phone,
        password=password,
        personnel_number=row.personnel_number,
        manager_id=row.manager_id,
        organization_id=row.organization_id,
        position=row.position,
        avatar_id=row.avatar_id,
        usr_org_tab_num=row.usr_org_tab_num,
    )


class EmployeesSourceMapper(SourceMapper[EmployeesRowPublic]):
    """
    Назначение/ответственность:
        Маппинг CSV-строки сотрудников в публичную каноническую форму.
    """

    def __init__(self, rules=FIELD_RULES) -> None:
        self.rules = rules

    def _collect_fields(
        self, csv_row: CsvRow
    ) -> tuple[dict[str, Any], list[ValidationErrorItem], list[ValidationErrorItem]]:
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []
        values: dict[str, Any] = {}
        for rule in self.rules:
            values[rule.name] = rule.apply(csv_row.values, errors, warnings)
        return values, errors, warnings

    def map(self, raw: CsvRow) -> MapResult[EmployeesRowPublic]:
        values, errors, warnings = self._collect_fields(raw)

        row = EmployeesRowPublic(
            email=values.get("email"),
            last_name=values.get("lastName"),
            first_name=values.get("firstName"),
            middle_name=values.get("middleName"),
            is_logon_disable=values.get("isLogonDisable"),
            user_name=values.get("userName"),
            phone=values.get("phone"),
            personnel_number=values.get("personnelNumber"),
            manager_id=values.get("managerId"),
            organization_id=values.get("organization_id"),
            position=values.get("position"),
            avatar_id=values.get("avatarId"),
            usr_org_tab_num=values.get("usrOrgTabNum"),
        )

        secret_candidates: dict[str, str] = {}
        password = values.get("password")
        if _is_present(password):
            secret_candidates["password"] = str(password)

        match_key: MatchKey | None = None
        if all(
            _is_present(part)
            for part in (row.last_name, row.first_name, row.middle_name, row.personnel_number)
        ):
            match_key = build_delimited_match_key(
                [row.last_name, row.first_name, row.middle_name, row.personnel_number]
            )
        else:
            errors.append(
                ValidationErrorItem(code="MATCH_KEY_MISSING", field="matchKey", message="match_key cannot be built")
            )

        row_ref = RowRef(
            line_no=raw.file_line_no,
            row_id=f"line:{raw.file_line_no}",
            identity_primary="match_key",
            identity_value=match_key.value if match_key else None,
        )

        return MapResult(
            row_ref=row_ref,
            row=row,
            match_key=match_key,
            secret_candidates=secret_candidates,
            errors=errors,
            warnings=warnings,
        )
