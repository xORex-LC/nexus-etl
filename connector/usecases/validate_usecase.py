from __future__ import annotations

import logging

from connector.domain.validation.validator import Validator
from connector.domain.validation.validated_row import ValidationRow
from connector.domain.transform.core.result import TransformResult
from connector.domain.models import RowRef
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.transform.core.result_processor import TransformResultProcessor
from connector.domain.transform.stages.stages import ValidateStage


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
        stage = ValidateStage(validator, catalog)
        for validated in stage.run(enriched_source):
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
        report.set_meta(dataset=dataset, items_limit=self.report_items_limit)

        def payload_builder(result: TransformResult):
            row = result.row
            if isinstance(row, ValidationRow):
                return row.row
            return None

        processor = TransformResultProcessor(
            report=report,
            include_items=self.include_valid_items,
            context_key="validate",
            ok_label="valid_rows",
            failed_label="failed_rows",
            payload_builder=payload_builder,
        )

        for validated in self.iter_validated(enriched_source, validator, catalog=catalog):
            validation_row: ValidationRow | None = validated.row
            validation = validation_row.validation if validation_row else None
            errors = validation.errors if validation else validated.errors
            warnings = validation.warnings if validation else validated.warnings

            row_ref = validation.row_ref if validation else None
            if row_ref is None and validated.row_ref is not None:
                row_ref = validated.row_ref
            if row_ref is None:
                row_ref = RowRef(
                    line_no=validated.record.line_no,
                    row_id=validated.record.record_id,
                    identity_primary=None,
                    identity_value=None,
                )

            processor.process(
                validated,
                row_ref=row_ref,
                errors_override=errors,
                warnings_override=warnings,
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

        return processor.finalize()

    # NOTE: итератор без ошибок вынесен в iter_ok(stage.run(...))
