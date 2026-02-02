from __future__ import annotations

import logging
from dataclasses import asdict

from connector.common.sanitize import maskSecretsInObject
from connector.domain.validation.validator import Validator
from connector.domain.validation.validated_row import ValidationRow
from connector.domain.transform.result import TransformResult
from connector.domain.models import RowRef, DiagnosticStage
from connector.domain.diagnostics.boundary import diagnostic_boundary
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode


class ValidateUseCase:
    """
    Назначение/ответственность:
        Use-case для валидации обогащенных строк (enrich -> validate).
    """

    def __init__(
        self,
        report_items_limit: int,
        include_valid_items: bool,
    ) -> None:
        self.report_items_limit = report_items_limit
        self.include_valid_items = include_valid_items

    def iter_validated(
        self,
        enriched_source,
        validator: Validator,
        *,
        catalog: ErrorCatalog,
    ):
        """
        Назначение:
            Итератор валидированных строк без формирования отчета.
        """
        for enriched in enriched_source:
            boundary_errors: list = []
            validated = None
            with diagnostic_boundary(
                stage=DiagnosticStage.VALIDATE,
                catalog=catalog,
                sink=boundary_errors,
                record_ref=enriched.row_ref,
            ):
                validated = validator.validate(enriched)
            if boundary_errors:
                yield TransformResult(
                    record=enriched.record,
                    row=None,
                    row_ref=enriched.row_ref,
                    match_key=enriched.match_key,
                    meta=enriched.meta,
                    secret_candidates=enriched.secret_candidates,
                    errors=[*enriched.errors, *boundary_errors],
                    warnings=[*enriched.warnings],
                )
                continue
            if validated is None:
                yield TransformResult(
                    record=enriched.record,
                    row=None,
                    row_ref=enriched.row_ref,
                    match_key=enriched.match_key,
                    meta=enriched.meta,
                    secret_candidates=enriched.secret_candidates,
                    errors=[*enriched.errors],
                    warnings=[*enriched.warnings],
                )
                continue
            validation_row = validated.row
            if validation_row is None:
                yield validated
                continue
            validation = validation_row.validation
            if not validation.errors:
                validated.errors = validation.errors
                validated.warnings = validation.warnings
            yield validated

    def run(
        self,
        enriched_source,
        validator: Validator,
        dataset: str,
        logger: logging.Logger,
        run_id: str,
        report,
        log_failure,
        catalog: ErrorCatalog,
    ) -> CommandResult:
        rows_total = 0
        valid_rows = 0
        failed_rows = 0
        warning_rows = 0

        report.set_meta(dataset=dataset, items_limit=self.report_items_limit)

        for validated in self.iter_validated(enriched_source, validator, catalog=catalog):
            rows_total += 1
            validation_row: ValidationRow | None = validated.row
            validation = validation_row.validation if validation_row else None
            errors = validation.errors if validation else validated.errors
            warnings = validation.warnings if validation else validated.warnings

            status = "FAILED" if errors else "OK"
            if errors:
                failed_rows += 1
            else:
                valid_rows += 1
            if warnings:
                warning_rows += 1

            should_store = status == "FAILED" or self.include_valid_items
            row_ref = validation.row_ref if validation else None
            if row_ref is None:
                row_ref = RowRef(
                    line_no=validated.record.line_no,
                    row_id=validated.record.record_id,
                    identity_primary=None,
                    identity_value=None,
                )
            row_payload = asdict(validation_row.row) if should_store and validation_row and validation_row.row is not None else None
            report.add_item(
                status=status,
                row_ref=row_ref,
                payload=maskSecretsInObject(row_payload) if row_payload else None,
                errors=errors,
                warnings=warnings,
                meta={"match_key": validation.match_key if validation else None},
                store=should_store,
            )

            if errors:
                log_failure(
                    logger,
                    run_id,
                    "validate",
                    validation,
                    None,
                    errors=errors,
                    warnings=warnings,
                )

        report.set_context(
            "validate",
            {
                "rows_total": rows_total,
                "valid_rows": valid_rows,
                "failed_rows": failed_rows,
                "warnings_rows": warning_rows,
            },
        )
        result = CommandResult()
        if failed_rows > 0:
            result.add_code(SystemErrorCode.DATA_INVALID)
        else:
            result.add_code(SystemErrorCode.OK)
        return result

    def iter_validated_ok(
        self,
        enriched_source,
        validator: Validator,
        *,
        catalog: ErrorCatalog,
    ):
        """
        Назначение:
            Итератор валидированных строк без ошибок (для matcher).
        """
        for validated in self.iter_validated(enriched_source, validator, catalog=catalog):
            validation_row: ValidationRow | None = validated.row
            if validation_row is None:
                continue
            if validation_row.validation.errors:
                continue
            yield validated
