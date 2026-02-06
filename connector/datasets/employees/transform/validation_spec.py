from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from connector.domain.models import DiagnosticStage, DiagnosticItem
from connector.domain.transform.dsl.loader import load_sink_spec_for_dataset
from connector.domain.validation.deps import ValidationDependencies
from connector.domain.validation.row_rules import validate_email
from connector.domain.validation.validator import FieldRule, ValidationRule, ValidationSpec
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow


FieldValidator = Callable[[Any, NormalizedEmployeesRow, ValidationDependencies, Callable[..., DiagnosticItem]], None]


def _validate_email(
    value: Any,
    row: NormalizedEmployeesRow,
    __: ValidationDependencies,
    add_error: Callable[..., DiagnosticItem],
) -> None:
    if value is None:
        return
    if not validate_email(str(value)):
        add_error(
            stage=DiagnosticStage.VALIDATE,
            code="INVALID_EMAIL",
            field="email",
            message="email has invalid format",
        )


def _validate_avatar_id(
    value: Any,
    row: NormalizedEmployeesRow,
    __: ValidationDependencies,
    add_error: Callable[..., DiagnosticItem],
) -> None:
    if value is not None and str(value).strip() != "":
        add_error(
            stage=DiagnosticStage.VALIDATE,
            code="INVALID_AVATAR_ID",
            field="avatarId",
            message="avatarId must be empty or null",
        )


def _validate_positive_int(field: str) -> FieldValidator:
    def _inner(
        value: Any,
        row: NormalizedEmployeesRow,
        __: ValidationDependencies,
        add_error: Callable[..., DiagnosticItem],
    ) -> None:
        if value is None:
            return
        if not isinstance(value, int) or value <= 0:
            add_error(
                stage=DiagnosticStage.VALIDATE,
                code="INVALID_INT",
                field=field,
                message=f"{field} must be an integer > 0",
            )

    return _inner


def _validate_org_reference(
    value: Any,
    row: NormalizedEmployeesRow,
    __: ValidationDependencies,
    add_error: Callable[..., DiagnosticItem],
) -> None:
    # Resolver может заменить строковое имя/код организации на _ouid после валидации.
    if value is None:
        return
    if isinstance(value, int):
        if value <= 0:
            add_error(
                stage=DiagnosticStage.VALIDATE,
                code="INVALID_INT",
                field="organization_id",
                message="organization_id must be an integer > 0",
            )
        return
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return
        numeric = raw.lstrip("+-")
        if numeric.isdigit():
            try:
                parsed = int(raw)
            except ValueError:
                return
            if parsed <= 0:
                add_error(
                    stage=DiagnosticStage.VALIDATE,
                    code="INVALID_INT",
                    field="organization_id",
                    message="organization_id must be an integer > 0",
                )


def _build_rules() -> tuple[ValidationRule[NormalizedEmployeesRow], ...]:
    required_fields = _required_fields_from_sink_spec()
    rules: list[ValidationRule[NormalizedEmployeesRow]] = []
    for attr, field in required_fields:
        validators: tuple[FieldValidator, ...] = ()
        if attr == "email":
            validators = (_validate_email,)
        elif attr == "organization_id":
            validators = (_validate_org_reference,)
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


def _required_fields_from_sink_spec() -> tuple[tuple[str, str], ...]:
    sink_spec = load_sink_spec_for_dataset("employees")
    required_fields: list[tuple[str, str]] = []
    for field in sink_spec.sink.fields:
        # Nullable fields can be empty by contract and should not be marked required.
        if not field.required or field.nullable:
            continue
        required_fields.append((field.name, field.target or field.name))
    return tuple(required_fields)


@dataclass(frozen=True)
class EmployeesValidationSpec(ValidationSpec[NormalizedEmployeesRow]):
    """
    Назначение:
        Спецификация правил валидации для employees.
    """

    rules: tuple[ValidationRule[NormalizedEmployeesRow], ...] = _build_rules()
