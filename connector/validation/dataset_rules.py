from __future__ import annotations

from typing import Any

from ..models import EmployeeInput, ValidationErrorItem, ValidationRowResult
from .deps import DatasetValidationState, ValidationDependencies

class MatchKeyUniqueRule:
    """
    Назначение:
        Проверяет возможность построить match_key и его уникальность в CSV.
    """

    def apply(
        self,
        employee: EmployeeInput,
        result: ValidationRowResult,
        state: DatasetValidationState,
        deps: ValidationDependencies,
    ) -> None:
        if not result.match_key_complete:
            result.errors.append(
                ValidationErrorItem(code="MATCH_KEY_MISSING", field="matchKey", message="match_key cannot be built")
            )
            return
        prev_line = state.matchkey_seen.get(result.match_key)
        if prev_line is not None:
            result.errors.append(
                ValidationErrorItem(code="DUPLICATE_MATCHKEY", field="matchKey", message=f"duplicate of line {prev_line}")
            )
            return
        state.matchkey_seen[result.match_key] = result.line_no

class UsrOrgTabUniqueRule:
    """
    Назначение:
        Проверяет уникальность usr_org_tab_num в рамках CSV.
    """

    def apply(
        self,
        employee: EmployeeInput,
        result: ValidationRowResult,
        state: DatasetValidationState,
        deps: ValidationDependencies,
    ) -> None:
        if not result.usr_org_tab_num:
            return
        prev_line = state.usr_org_tab_seen.get(result.usr_org_tab_num)
        if prev_line is not None:
            result.errors.append(
                ValidationErrorItem(
                    code="DUPLICATE_USR_ORG_TAB_NUM", field="usrOrgTabNum", message=f"duplicate of line {prev_line}"
                )
            )
            return
        state.usr_org_tab_seen[result.usr_org_tab_num] = result.line_no

class OrgExistsRule:
    """
    Назначение:
        Проверяет наличие организации в внешнем источнике (кэш) при указанном org_lookup.
    """

    def apply(
        self,
        employee: EmployeeInput,
        result: ValidationRowResult,
        state: DatasetValidationState,
        deps: ValidationDependencies,
    ) -> None:
        if deps.org_lookup is None:
            return
        if employee.organization_id is None:
            return
        org_exists = deps.org_lookup.get_org_by_id(employee.organization_id)
        if org_exists is None:
            result.errors.append(
                ValidationErrorItem(
                    code="ORG_NOT_FOUND", field="organization_id", message="organization_id not found in cache"
                )
            )
