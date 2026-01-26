from __future__ import annotations

from connector.domain.models import DiagnosticStage, RowRef, ValidationErrorItem
from connector.domain.ports.sources import SourceMapper
from connector.domain.transform.result import TransformResult
from connector.domain.transform.match_key import MatchKey, MatchKeyError, build_delimited_match_key
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
        )

        secret_candidates = self.spec.collect_secret_candidates(normalized)

        match_key: MatchKey | None = None
        try:
            match_key = build_delimited_match_key(
                self.spec.get_match_key_parts(row),
                strict=True,
            )
        except MatchKeyError:
            errors.append(
                ValidationErrorItem(
                    stage=DiagnosticStage.MAP,
                    code="MATCH_KEY_MISSING",
                    field="matchKey",
                    message="match_key cannot be built",
                )
            )

        row_ref = RowRef(
            line_no=record.line_no,
            row_id=record.record_id,
            identity_primary="match_key",
            identity_value=match_key.value if match_key else None,
        )

        return TransformResult(
            record=record,
            row=row,
            row_ref=row_ref,
            match_key=match_key,
            secret_candidates=secret_candidates,
            errors=errors,
            warnings=warnings,
        )
