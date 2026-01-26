from __future__ import annotations

from connector.domain.models import ValidationErrorItem
from connector.domain.ports.sources import SourceMapper
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
from connector.datasets.employees.models import EmployeesRowPublic
from connector.datasets.employees.normalized import NormalizedEmployeesRow
from connector.datasets.employees.mapping_spec import EmployeesMappingSpec


class EmployeesSourceMapper(SourceMapper[NormalizedEmployeesRow, EmployeesRowPublic]):
    """
    Назначение/ответственность:
        Маппинг CSV-строки сотрудников в публичную каноническую форму.
    """

    def __init__(self, spec: EmployeesMappingSpec | None = None) -> None:
        self.spec = spec or EmployeesMappingSpec()

    def map(self, record: SourceRecord, normalized: NormalizedEmployeesRow) -> TransformResult[EmployeesRowPublic]:
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []

        row = EmployeesRowPublic(
            email=normalized.email,
            last_name=normalized.last_name,
            first_name=normalized.first_name,
            middle_name=normalized.middle_name,
            is_logon_disable=normalized.is_logon_disable,
            user_name=normalized.user_name,
            phone=normalized.phone,
            personnel_number=normalized.personnel_number,
            manager_id=normalized.manager_id,
            organization_id=normalized.organization_id,
            position=normalized.position,
            avatar_id=normalized.avatar_id,
            usr_org_tab_num=normalized.usr_org_tab_num,
            resource_id=None,
        )

        secret_candidates = self.spec.collect_secret_candidates(normalized)

        return TransformResult(
            record=record,
            row=row,
            row_ref=None,
            match_key=None,
            secret_candidates=secret_candidates,
            errors=errors,
            warnings=warnings,
        )
