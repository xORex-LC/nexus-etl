from __future__ import annotations

import logging
from dataclasses import asdict

from connector.common.sanitize import maskSecretsInObject
from connector.domain.validation.pipeline import DatasetValidator, RowValidator
from connector.domain.validation.validated_row import ValidationRow


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
        record_source,
        row_validator: RowValidator,
        dataset_validator: DatasetValidator,
    ):
        """
        Назначение:
            Итератор валидированных строк без формирования отчета.
        """
        for collected in record_source:
            map_result = row_validator.map_only(collected)
            validated = row_validator.validate_enriched(map_result)
            validation_row = validated.row
            if validation_row is None:
                yield validated
                continue
            validation = validation_row.validation
            if not validation.errors:
                dataset_validator.validate(validation_row.row, validation)
                validated.errors = validation.errors
                validated.warnings = validation.warnings
            yield validated

    def run(
        self,
        record_source,
        row_validator: RowValidator,
        dataset_validator: DatasetValidator,
        dataset: str,
        logger: logging.Logger,
        run_id: str,
        report,
        log_failure,
    ) -> int:
        rows_total = 0
        valid_rows = 0
        failed_rows = 0
        warning_rows = 0

        report.meta.dataset = dataset
        report.meta.report_items_limit = self.report_items_limit

        for validated in self.iter_validated(record_source, row_validator, dataset_validator):
            rows_total += 1
            validation_row: ValidationRow | None = validated.row
            validation = validation_row.validation if validation_row else None
            errors = validation.errors if validation else validated.errors
            warnings = validation.warnings if validation else validated.warnings

            status = "valid" if not errors else "invalid"
            if errors:
                failed_rows += 1
            else:
                valid_rows += 1
            if warnings:
                warning_rows += 1

            should_store = status == "invalid" or self.include_valid_items
            if should_store and len(report.items) < self.report_items_limit:
                row_ref = validation.row_ref if validation else None
                fallback_line_no = validated.record.line_no
                row_payload = asdict(validation_row.row) if validation_row and validation_row.row is not None else None
                item = {
                    "row_id": row_ref.row_id if row_ref else f"line:{fallback_line_no}",
                    "line_no": row_ref.line_no if row_ref else fallback_line_no,
                    "match_key": validation.match_key if validation else None,
                    "status": status,
                    "row": row_payload,
                    "errors": [e.__dict__ for e in errors],
                    "warnings": [w.__dict__ for w in warnings],
                }
                report.items.append(maskSecretsInObject(item))
            elif should_store:
                report.meta.items_truncated = True

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

        report.meta.csv_rows_total = rows_total
        report.meta.csv_rows_processed = rows_total
        report.summary.failed = failed_rows
        report.summary.warnings = warning_rows
        report.summary.skipped = 0
        report.summary.by_dataset = report.summary.by_dataset or {}
        report.summary.by_dataset[dataset] = {
            "rows_total": rows_total,
            "valid_rows": valid_rows,
            "failed_rows": failed_rows,
            "warnings_rows": warning_rows,
        }
        return 1 if failed_rows > 0 else 0
