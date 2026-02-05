from __future__ import annotations

import uuid
from dataclasses import dataclass

from connector.domain.transform.enricher import (
    EnrichOperationType,
    EnrichOutcome,
    EnricherSpec,
    EnrichmentOperation,
    KeyRegistry,
    MergeMode,
    MergePolicy,
    RunWhenErrors,
    StrictnessPolicy,
)
from connector.domain.transform.ids.match_key import MatchKeyError, build_delimited_match_key
from connector.domain.transform.ids.target_id import TargetIdMode, TargetIdPolicy
from connector.domain.validation.row_rules import normalize_whitespace
from connector.datasets.employees.extract.mapping_spec import EmployeesMappingSpec
from connector.datasets.employees.transform.enrich_deps import EmployeesEnrichDependencies
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow


def _build_match_key(result, deps) -> dict[str, str] | None:
    _ = deps
    if result.row is None:
        return None
    spec = EmployeesMappingSpec()
    try:
        match_key = build_delimited_match_key(spec.get_match_key_parts(result.row), strict=True)
    except MatchKeyError:
        return None
    return {"match_key": match_key.value}


def _build_target_id_policy() -> TargetIdPolicy[EmployeesEnrichDependencies]:
    """
    Назначение:
        Политика формирования target_id для employees.
    """
    return TargetIdPolicy(
        field_name="target_id",
        mode=TargetIdMode.REQUIRED,
        allow_source_value=True,
        generator=lambda: str(uuid.uuid4()),
        exists=lambda deps, value: deps.find_user_by_target_id(value) is not None,
        max_attempts=3,
    )


def _target_id_generator(result, deps) -> str | None:
    row = result.row
    if row is None:
        return None
    policy = _build_target_id_policy()
    if policy.mode == TargetIdMode.NONE:
        return None
    current = getattr(row, policy.field_name, None)
    if current is not None and policy.allow_source_value:
        candidate = str(current).strip() or None
        if candidate:
            return candidate
    if policy.generator is None:
        if policy.mode == TargetIdMode.REQUIRED:
            return None
        return None
    return policy.generator()


def _usr_org_tab_num_generator(result, deps) -> str | None:
    _ = deps
    row = result.row
    if row is None:
        return None
    current = normalize_whitespace(row.usr_org_tab_num)
    if current:
        return current
    return f"TAB-{uuid.uuid4().hex[:8]}"


def _usr_org_tab_allow_if(result, existing: dict) -> bool:
    if result.match_key is None:
        return False
    return existing.get("match_key") == result.match_key.value


def _password_generator(result, deps) -> str | None:
    _ = deps
    existing = result.secret_candidates.get("password")
    if existing:
        return existing
    return uuid.uuid4().hex


def _build_key_registry() -> KeyRegistry[NormalizedEmployeesRow]:
    return KeyRegistry(builders={})


@dataclass(frozen=True)
class EmployeesEnricherSpec(EnricherSpec[NormalizedEmployeesRow, EmployeesEnrichDependencies]):
    """
    Назначение:
        Спецификация операций enrich для employees.
    """

    # TODO(dicts): здесь добавлять dictionary-операции (lookup/canonicalize/membership),
    # используя deps.dictionaries. Пример:
    # EnrichmentOperation(
    #     name="department_name",
    #     op_type=EnrichOperationType.LOOKUP,
    #     targets=("department_name",),
    #     required_keys=("department_code",),
    #     providers=(DepartmentDictionaryProvider(),),
    # )
    operations: tuple[EnrichmentOperation[NormalizedEmployeesRow, EmployeesEnrichDependencies], ...] = (
        EnrichmentOperation(
            name="build_match_key",
            op_type=EnrichOperationType.COMPUTE,
            targets=("match_key",),
            run_when_errors=RunWhenErrors.ALWAYS,
            strictness=StrictnessPolicy(on_provider_error=EnrichOutcome.FAILED),
            compute=_build_match_key,
            missing_error_code="MATCH_KEY_MISSING",
            error_field="matchKey",
        ),
        EnrichmentOperation(
            name="target_id",
            op_type=EnrichOperationType.GENERATE,
            targets=("target_id",),
            merge_policy=MergePolicy(mode=MergeMode.RECOMPUTE_ALWAYS),
            strictness=StrictnessPolicy(on_no_candidates=EnrichOutcome.FAILED, on_provider_error=EnrichOutcome.FAILED),
            generator=_target_id_generator,
            exists=lambda deps, value: deps.find_user_by_target_id(value),
            max_attempts=_build_target_id_policy().max_attempts,
            missing_error_code="TARGET_ID_MISSING",
            conflict_error_code="TARGET_ID_CONFLICT",
            error_field="target_id",
        ),
        EnrichmentOperation(
            name="usr_org_tab_num",
            op_type=EnrichOperationType.GENERATE,
            targets=("usr_org_tab_num",),
            merge_policy=MergePolicy(mode=MergeMode.RECOMPUTE_ALWAYS),
            strictness=StrictnessPolicy(on_no_candidates=EnrichOutcome.FAILED, on_provider_error=EnrichOutcome.FAILED),
            generator=_usr_org_tab_num_generator,
            exists=lambda deps, value: deps.find_user_by_usr_org_tab_num(value),
            allow_if=_usr_org_tab_allow_if,
            max_attempts=3,
            conflict_error_code="USR_ORG_TAB_CONFLICT",
            error_field="usrOrgTabNum",
        ),
        EnrichmentOperation(
            name="password",
            op_type=EnrichOperationType.GENERATE,
            targets=("secret:password",),
            merge_policy=MergePolicy(mode=MergeMode.FILL_ONLY_IF_EMPTY),
            strictness=StrictnessPolicy(on_no_candidates=EnrichOutcome.WARNED),
            generator=_password_generator,
        ),
    )
    key_registry: KeyRegistry[NormalizedEmployeesRow] = _build_key_registry()
