from __future__ import annotations

import logging
from dataclasses import asdict

from connector.common.sanitize import maskSecretsInObject
from connector.domain.validation.pipeline import RowValidator


class MappingUseCase:
    """
    Назначение/ответственность:
        Use-case для отчета по маппингу (без записи в vault).
    """

    def __init__(
        self,
        report_items_limit: int,
        include_mapped_items: bool,
    ) -> None:
        self.report_items_limit = report_items_limit
        self.include_mapped_items = include_mapped_items

    def run(
        self,
        row_source,
        row_validator: RowValidator,
        dataset: str,
        logger: logging.Logger,
        run_id: str,
        report,
    ) -> int:
        rows_total = 0
        mapped_ok = 0
        mapping_failed = 0
        warnings_rows = 0
        vault_candidates_rows = 0
        vault_candidates_fields_total = 0

        report.meta.dataset = dataset
        report.meta.report_items_limit = self.report_items_limit

        for csv_row in row_source:
            rows_total += 1
            map_result = row_validator.map_only(csv_row)

            has_errors = len(map_result.errors) > 0
            is_mapped = not has_errors and map_result.match_key is not None
            status = "mapped" if is_mapped else "mapping_failed"
            if not is_mapped:
                mapping_failed += 1
            else:
                mapped_ok += 1

            if map_result.warnings:
                warnings_rows += 1

            secret_fields = list(map_result.secret_candidates.keys())
            if secret_fields:
                vault_candidates_rows += 1
                vault_candidates_fields_total += len(secret_fields)

            should_store = status == "mapping_failed" or self.include_mapped_items
            if should_store and len(report.items) < self.report_items_limit:
                row_ref = map_result.row_ref
                item = {
                    "row_id": row_ref.row_id if row_ref else f"line:{csv_row.file_line_no}",
                    "line_no": row_ref.line_no if row_ref else csv_row.file_line_no,
                    "match_key": map_result.match_key.value if map_result.match_key else None,
                    "status": status,
                    "row": asdict(map_result.row),
                    "errors": [e.__dict__ for e in map_result.errors],
                    "warnings": [w.__dict__ for w in map_result.warnings],
                    "secret_candidate_fields": secret_fields,
                }
                report.items.append(maskSecretsInObject(item))
            elif should_store:
                report.meta.items_truncated = True

        report.summary.failed = mapping_failed
        report.summary.warnings = warnings_rows
        report.summary.by_dataset = report.summary.by_dataset or {}
        report.summary.by_dataset[dataset] = {
            "rows_total": rows_total,
            "mapped_ok": mapped_ok,
            "mapping_failed": mapping_failed,
            "warnings_rows": warnings_rows,
            "vault_candidates_rows": vault_candidates_rows,
            "vault_candidates_fields_total": vault_candidates_fields_total,
        }
        report.meta.csv_rows_total = rows_total
        report.meta.csv_rows_processed = rows_total
        return 1 if mapping_failed > 0 else 0
