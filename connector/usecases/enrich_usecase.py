from __future__ import annotations

import logging
from dataclasses import asdict

from connector.common.sanitize import maskSecretsInObject
from connector.domain.transform.pipeline import TransformPipeline


class EnrichUseCase:
    """
    Назначение/ответственность:
        Use-case для отчета по обогащению (normalize + map + enrich) с записью секретов через enricher.
    """

    def __init__(
        self,
        report_items_limit: int,
        include_enriched_items: bool,
    ) -> None:
        self.report_items_limit = report_items_limit
        self.include_enriched_items = include_enriched_items

    def run(
        self,
        record_source,
        transformer: TransformPipeline,
        dataset: str,
        logger: logging.Logger,
        run_id: str,
        report,
    ) -> int:
        rows_total = 0
        enriched_ok = 0
        enrich_failed = 0
        warnings_rows = 0
        vault_candidates_rows = 0
        vault_candidates_fields_total = 0

        report.meta.dataset = dataset
        report.meta.report_items_limit = self.report_items_limit

        for collected in record_source:
            rows_total += 1
            map_result = transformer.enrich(collected)

            has_errors = len(map_result.errors) > 0
            status = "enriched" if not has_errors else "enrich_failed"
            if has_errors:
                enrich_failed += 1
            else:
                enriched_ok += 1

            if map_result.warnings:
                warnings_rows += 1

            secret_fields = list(map_result.secret_candidates.keys())
            if secret_fields:
                vault_candidates_rows += 1
                vault_candidates_fields_total += len(secret_fields)

            should_store = status == "enrich_failed" or self.include_enriched_items
            if should_store and len(report.items) < self.report_items_limit:
                row_ref = map_result.row_ref
                fallback_line_no = collected.record.line_no
                row_payload = asdict(map_result.row) if map_result.row is not None else None
                item = {
                    "row_id": row_ref.row_id if row_ref else f"line:{fallback_line_no}",
                    "line_no": row_ref.line_no if row_ref else fallback_line_no,
                    "match_key": map_result.match_key.value if map_result.match_key else None,
                    "status": status,
                    "row": row_payload,
                    "errors": [e.__dict__ for e in map_result.errors],
                    "warnings": [w.__dict__ for w in map_result.warnings],
                    "secret_candidate_fields": secret_fields,
                }
                report.items.append(maskSecretsInObject(item))
            elif should_store:
                report.meta.items_truncated = True

        report.summary.failed = enrich_failed
        report.summary.warnings = warnings_rows
        report.summary.by_dataset = report.summary.by_dataset or {}
        report.summary.by_dataset[dataset] = {
            "rows_total": rows_total,
            "enriched_ok": enriched_ok,
            "enrich_failed": enrich_failed,
            "warnings_rows": warnings_rows,
            "vault_candidates_rows": vault_candidates_rows,
            "vault_candidates_fields_total": vault_candidates_fields_total,
        }
        report.meta.csv_rows_total = rows_total
        report.meta.csv_rows_processed = rows_total
        return 1 if enrich_failed > 0 else 0

    def iter_enriched_ok(
        self,
        record_source,
        transformer: TransformPipeline,
    ):
        """
        Назначение:
            Итератор обогащенных строк без ошибок.
        """
        for collected in record_source:
            map_result = transformer.enrich(collected)
            if map_result.errors:
                continue
            yield map_result
