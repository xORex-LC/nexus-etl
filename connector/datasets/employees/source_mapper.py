from __future__ import annotations

from connector.domain.models import RowRef, ValidationErrorItem, EmployeeInput
from connector.domain.ports.sources import SourceMapper
from connector.domain.transform.map_result import MapResult
from connector.domain.transform.match_key import MatchKey, MatchKeyError, build_delimited_match_key
from connector.domain.transform.source_record import SourceRecord
from connector.datasets.employees.models import EmployeesRowPublic
from connector.datasets.employees.mapping_spec import EmployeesMappingSpec


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

    def __init__(self, spec: EmployeesMappingSpec | None = None) -> None:
        self.spec = spec or EmployeesMappingSpec()

    def map(self, raw: SourceRecord) -> MapResult[EmployeesRowPublic]:
        values = raw.values
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []

        row = EmployeesRowPublic(
            email=values.get("email"),
            last_name=values.get("last_name"),
            first_name=values.get("first_name"),
            middle_name=values.get("middle_name"),
            is_logon_disable=values.get("is_logon_disable"),
            user_name=values.get("user_name"),
            phone=values.get("phone"),
            personnel_number=values.get("personnel_number"),
            manager_id=values.get("manager_id"),
            organization_id=values.get("organization_id"),
            position=values.get("position"),
            avatar_id=values.get("avatar_id"),
            usr_org_tab_num=values.get("usr_org_tab_num"),
        )

        secret_candidates = self.spec.collect_secret_candidates(values)

        match_key: MatchKey | None = None
        try:
            match_key = build_delimited_match_key(
                self.spec.get_match_key_parts(row),
                strict=True,
            )
        except MatchKeyError:
            errors.append(
                ValidationErrorItem(code="MATCH_KEY_MISSING", field="matchKey", message="match_key cannot be built")
            )

        row_ref = RowRef(
            line_no=raw.line_no,
            row_id=raw.record_id,
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
