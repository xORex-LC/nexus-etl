from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from connector.domain.models import DiagnosticStage, ValidationErrorItem
from connector.domain.validation.deps import DatasetValidationState, ValidationDependencies
from connector.domain.validation.row_rules import validate_email
from connector.domain.validation.validator import FieldRule, ValidationRule, ValidationSpec
from connector.datasets.employees.mapping_spec import EmployeesMappingSpec
from connector.datasets.employees.normalized import NormalizedEmployeesRow


FieldValidator = Callable[
    [Any, NormalizedEmployeesRow, ValidationDependencies, DatasetValidationState, list[ValidationErrorItem]],
    None,
]


def _validate_email(
    value: Any,
    _: NormalizedEmployeesRow,
    __: ValidationDependencies,
    ___: DatasetValidationState,
    errors: list[ValidationErrorItem],
) -> None:
    if value is None:
        return
    if not validate_email(str(value)):
        errors.append(
            ValidationErrorItem(
                stage=DiagnosticStage.VALIDATE,
                code="INVALID_EMAIL",
                field="email",
                message="email has invalid format",
            )
        )


def _validate_avatar_id(
    value: Any,
    _: NormalizedEmployeesRow,
    __: ValidationDependencies,
    ___: DatasetValidationState,
    errors: list[ValidationErrorItem],
) -> None:
    if value is not None and str(value).strip() != "":
        errors.append(
            ValidationErrorItem(
                stage=DiagnosticStage.VALIDATE,
                code="INVALID_AVATAR_ID",
                field="avatarId",
                message="avatarId must be empty or null",
            )
        )


def _validate_positive_int(field: str) -> FieldValidator:
    def _inner(
        value: Any,
        _: NormalizedEmployeesRow,
        __: ValidationDependencies,
        ___: DatasetValidationState,
        errors: list[ValidationErrorItem],
    ) -> None:
        if value is None:
            return
        if not isinstance(value, int) or value <= 0:
            errors.append(
                ValidationErrorItem(
                    stage=DiagnosticStage.VALIDATE,
                    code="INVALID_INT",
                    field=field,
                    message=f"{field} must be an integer > 0",
                )
            )

    return _inner


def _validate_org_exists(
    value: Any,
    _: NormalizedEmployeesRow,
    deps: ValidationDependencies,
    __: DatasetValidationState,
    errors: list[ValidationErrorItem],
) -> None:
    if value is None or deps.org_lookup is None:
        return
    org_exists = deps.org_lookup.get_org_by_id(value)
    if org_exists is None:
        errors.append(
            ValidationErrorItem(
                stage=DiagnosticStage.VALIDATE,
                code="ORG_NOT_FOUND",
                field="organization_id",
                message="organization_id not found in cache",
            )
        )


def _build_rules() -> tuple[ValidationRule[NormalizedEmployeesRow], ...]:
    mapping_spec = EmployeesMappingSpec()
    rules: list[ValidationRule[NormalizedEmployeesRow]] = []
    for attr, field in mapping_spec.required_fields:
        validators: tuple[FieldValidator, ...] = ()
        if attr == "email":
            validators = (_validate_email,)
        elif attr == "organization_id":
            validators = (_validate_positive_int("organization_id"), _validate_org_exists)
        rules.append(
            FieldRule(
                name=attr,
                attr=attr,
                field=field,
                required=True,
                validators=validators,
            )
        )
    rules.append(
        FieldRule(
            name="avatar_id",
            attr="avatar_id",
            field="avatarId",
            required=False,
            validators=(_validate_avatar_id,),
        )
    )
    return tuple(rules)


@dataclass(frozen=True)
class EmployeesValidationSpec(ValidationSpec[NormalizedEmployeesRow]):
    """
    Назначение:
        Спецификация правил валидации для employees.
    """

    rules: tuple[ValidationRule[NormalizedEmployeesRow], ...] = _build_rules()
