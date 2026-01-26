from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Generic, Protocol, TypeVar

from connector.domain.models import DiagnosticStage, RowRef, ValidationErrorItem, ValidationRowResult
from connector.domain.validation.deps import DatasetValidationState, ValidationDependencies
from connector.domain.validation.validated_row import ValidationRow
from connector.domain.transform.result import TransformResult

T = TypeVar("T")


class ValidationRule(Protocol[T]):
    """
    Назначение:
        Контракт правила валидации для строки конкретного датасета.
    """

    name: str

    def apply(
        self,
        row: T,
        result: ValidationRowResult,
        deps: ValidationDependencies,
        state: DatasetValidationState,
    ) -> None: ...


class ValidationSpec(Protocol[T]):
    """
    Назначение:
        Контракт набора правил валидации для датасета.
    """

    rules: tuple[ValidationRule[T], ...]


FieldValidator = Callable[[Any, Any, ValidationDependencies, DatasetValidationState, list[ValidationErrorItem]], None]


@dataclass(frozen=True)
class FieldRule(Generic[T]):
    """
    Назначение:
        Правило валидации для конкретного поля датасета.
    """

    name: str
    attr: str
    field: str
    required: bool = False
    validators: tuple[FieldValidator, ...] = ()

    def apply(
        self,
        row: T,
        result: ValidationRowResult,
        deps: ValidationDependencies,
        state: DatasetValidationState,
    ) -> None:
        value = getattr(row, self.attr, None)
        is_empty = value is None or (isinstance(value, str) and value.strip() == "")
        if self.required and is_empty:
            secret_value = result.secret_candidates.get(self.attr)
            if secret_value is None or str(secret_value).strip() == "":
                result.errors.append(
                    ValidationErrorItem(
                        stage=DiagnosticStage.VALIDATE,
                        code="REQUIRED_FIELD_MISSING",
                        field=self.field,
                        message=f"{self.field} is required",
                    )
                )
                return
        for validator in self.validators:
            validator(value, row, deps, state, result.errors)


class Validator(Generic[T]):
    """
    Назначение/ответственность:
        Валидирует обогащенный TransformResult по правилам ValidationSpec.
    """

    def __init__(self, spec: ValidationSpec[T], deps: ValidationDependencies) -> None:
        self.spec = spec
        self.deps = deps
        self.state = DatasetValidationState(matchkey_seen={}, usr_org_tab_seen={})

    def validate(self, enriched: TransformResult[T]) -> TransformResult[ValidationRow[T]]:
        row = enriched.row
        if row is None and not enriched.errors:
            raise ValueError("Validation received empty row without errors")

        match_key_value = enriched.match_key.value if enriched.match_key else ""
        row_ref = enriched.row_ref or RowRef(
            line_no=enriched.record.line_no,
            row_id=enriched.record.record_id,
            identity_primary="match_key",
            identity_value=match_key_value or None,
        )
        result = ValidationRowResult(
            line_no=enriched.record.line_no,
            match_key=match_key_value,
            match_key_complete=enriched.match_key is not None,
            usr_org_tab_num=getattr(row, "usr_org_tab_num", None),
            row_ref=row_ref,
            secret_candidates=enriched.secret_candidates,
            errors=[*enriched.errors],
            warnings=[],
        )
        if row is not None and not result.errors:
            for rule in self.spec.rules:
                rule.apply(row, result, self.deps, self.state)
        return TransformResult(
            record=enriched.record,
            row=ValidationRow(row=row, validation=result),
            row_ref=row_ref,
            match_key=enriched.match_key,
            secret_candidates=enriched.secret_candidates,
            errors=result.errors,
            warnings=[],
        )


def logValidationFailure(
    logger,
    run_id: str,
    context: str,
    result: ValidationRowResult,
    report_item_index: int | None,
    errors: list[ValidationErrorItem] | None = None,
    warnings: list[ValidationErrorItem] | None = None,
) -> None:
    """
    Назначение:
        Логирует информацию о невалидной строке CSV.
    """
    eff_errors = errors if errors is not None else result.errors
    eff_warnings = warnings if warnings is not None else result.warnings

    codes: list[str] = []
    codes.extend(e.code for e in eff_errors)
    codes.extend(w.code for w in eff_warnings)
    code_str = ",".join(sorted(set(codes))) if codes else "none"
    index_str = (
        str(report_item_index)
        if report_item_index is not None
        else f"line:{result.line_no} (not stored: limit reached)"
    )
    logger.log(
        logging.WARNING,
        f"invalid row line={result.line_no} report_item_index={index_str} errors={code_str}",
        extra={"runId": run_id, "component": context},
    )
