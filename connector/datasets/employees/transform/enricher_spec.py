from __future__ import annotations

import uuid
from dataclasses import dataclass

from connector.domain.models import DiagnosticStage, Identity, MatchStatus, ValidationErrorItem
from connector.domain.transform.enricher import EnrichRule, EnricherSpec
from connector.domain.transform.match_key import MatchKey, MatchKeyError, build_delimited_match_key
from connector.datasets.employees.transform.enrich_deps import EmployeesEnrichDependencies
from connector.datasets.employees.extract.mapping_spec import EmployeesMappingSpec
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow
from connector.domain.validation.row_rules import normalize_whitespace


@dataclass(frozen=True)
class BuildMatchKeyRule(EnrichRule[NormalizedEmployeesRow, EmployeesEnrichDependencies]):
    name: str = "build_match_key"

    def apply(self, result, deps, errors, warnings) -> None:
        _ = deps
        _ = warnings
        spec = EmployeesMappingSpec()
        try:
            match_key = build_delimited_match_key(spec.get_match_key_parts(result.row), strict=True)
        except MatchKeyError:
            errors.append(
                ValidationErrorItem(
                    stage=DiagnosticStage.ENRICH,
                    code="MATCH_KEY_MISSING",
                    field="matchKey",
                    message="match_key cannot be built",
                )
            )
            return
        result.match_key = match_key


@dataclass(frozen=True)
class ManagerLookupRule(EnrichRule[NormalizedEmployeesRow, EmployeesEnrichDependencies]):
    name: str = "manager_lookup"

    def apply(self, result, deps, errors, warnings) -> None:
        _ = warnings
        if result.row.manager_id is None:
            return
        if isinstance(result.row.manager_id, int):
            return
        if deps.identity_lookup is None:
            errors.append(
                ValidationErrorItem(
                    stage=DiagnosticStage.ENRICH,
                    code="MANAGER_LOOKUP_MISSING",
                    field="managerId",
                    message="identity lookup is not configured",
                )
            )
            return
        match_key_value = normalize_whitespace(str(result.row.manager_id))
        if not match_key_value:
            return
        identity = Identity(primary="match_key", values={"match_key": match_key_value})
        lookup = deps.identity_lookup.match(identity, include_deleted=False)
        if lookup.status == MatchStatus.CONFLICT:
            errors.append(
                ValidationErrorItem(
                    stage=DiagnosticStage.ENRICH,
                    code="MANAGER_CONFLICT",
                    field="managerId",
                    message="multiple managers found for match_key",
                )
            )
            return
        if lookup.status != MatchStatus.MATCHED or not lookup.candidate:
            errors.append(
                ValidationErrorItem(
                    stage=DiagnosticStage.ENRICH,
                    code="MANAGER_NOT_FOUND",
                    field="managerId",
                    message="manager not found in cache",
                )
            )
            return
        manager_ouid = lookup.candidate.get("_ouid")
        if manager_ouid is None:
            errors.append(
                ValidationErrorItem(
                    stage=DiagnosticStage.ENRICH,
                    code="MANAGER_OUID_MISSING",
                    field="managerId",
                    message="manager has no _ouid",
                )
            )
            return
        result.row.manager_id = int(manager_ouid)


@dataclass(frozen=True)
class OrganizationLookupRule(EnrichRule[NormalizedEmployeesRow, EmployeesEnrichDependencies]):
    name: str = "organization_lookup"

    def apply(self, result, deps, errors, warnings) -> None:
        _ = warnings
        org_id = result.row.organization_id
        if org_id is None:
            return
        org = deps.find_org_by_ouid(int(org_id))
        if org is None:
            errors.append(
                ValidationErrorItem(
                    stage=DiagnosticStage.ENRICH,
                    code="ORG_NOT_FOUND",
                    field="organization_id",
                    message="organization_id not found in cache",
                )
            )


@dataclass(frozen=True)
class ResourceIdRule(EnrichRule[NormalizedEmployeesRow, EmployeesEnrichDependencies]):
    name: str = "resource_id"
    max_attempts: int = 3

    def apply(self, result, deps, errors, warnings) -> None:
        _ = warnings
        resource_id = result.row.resource_id
        attempts = 0
        while attempts < self.max_attempts:
            if not resource_id:
                resource_id = str(uuid.uuid4())
            existing = deps.find_user_by_id(resource_id)
            if existing is None:
                result.row.resource_id = resource_id
                return
            resource_id = None
            attempts += 1
        errors.append(
            ValidationErrorItem(
                stage=DiagnosticStage.ENRICH,
                code="RESOURCE_ID_CONFLICT",
                field="resource_id",
                message="unable to generate unique resource_id",
            )
        )


@dataclass(frozen=True)
class UsrOrgTabNumRule(EnrichRule[NormalizedEmployeesRow, EmployeesEnrichDependencies]):
    name: str = "usr_org_tab_num"
    max_attempts: int = 3

    def apply(self, result, deps, errors, warnings) -> None:
        _ = warnings
        tab_num = normalize_whitespace(result.row.usr_org_tab_num)
        attempts = 0
        while attempts < self.max_attempts:
            if not tab_num:
                tab_num = f"TAB-{uuid.uuid4().hex[:8]}"
            existing = deps.find_user_by_usr_org_tab_num(tab_num)
            if existing is None:
                result.row.usr_org_tab_num = tab_num
                return
            if result.match_key is not None and existing.get("match_key") == result.match_key.value:
                result.row.usr_org_tab_num = tab_num
                return
            tab_num = None
            attempts += 1
        errors.append(
            ValidationErrorItem(
                stage=DiagnosticStage.ENRICH,
                code="USR_ORG_TAB_CONFLICT",
                field="usrOrgTabNum",
                message="unable to generate unique usr_org_tab_num",
            )
        )


@dataclass(frozen=True)
class PasswordRule(EnrichRule[NormalizedEmployeesRow, EmployeesEnrichDependencies]):
    name: str = "password"

    def apply(self, result, deps, errors, warnings) -> None:
        _ = deps
        _ = warnings
        password = result.secret_candidates.get("password")
        if password:
            return
        generated = uuid.uuid4().hex
        result.secret_candidates["password"] = generated


@dataclass(frozen=True)
class EmployeesEnricherSpec(EnricherSpec[NormalizedEmployeesRow, EmployeesEnrichDependencies]):
    """
    Назначение:
        Спецификация правил обогащения для employees.
    """

    rules: tuple[EnrichRule[NormalizedEmployeesRow, EmployeesEnrichDependencies], ...] = (
        BuildMatchKeyRule(),
        ManagerLookupRule(),
        OrganizationLookupRule(),
        ResourceIdRule(),
        UsrOrgTabNumRule(),
        PasswordRule(),
    )
