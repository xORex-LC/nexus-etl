from __future__ import annotations

import logging
from dataclasses import asdict

from connector.common.sanitize import maskSecretsInObject
from connector.domain.transform.extractor import Extractor
from connector.domain.transform.pipeline import TransformPipeline
from connector.domain.models import RowRef


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
        row_source,
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

        report.set_meta(dataset=dataset, items_limit=self.report_items_limit)

        extractor = Extractor(row_source)
        for collected in extractor.run():
            rows_total += 1
            map_result = transformer.enrich(collected)

            has_errors = len(map_result.errors) > 0
            status = "FAILED" if has_errors else "OK"
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

            should_store = status == "FAILED" or self.include_enriched_items
            row_ref = map_result.row_ref or RowRef(
                line_no=collected.record.line_no,
                row_id=collected.record.record_id,
                identity_primary=None,
                identity_value=None,
            )
            row_payload = asdict(map_result.row) if should_store and map_result.row is not None else None
            report.add_item(
                status=status,
                row_ref=row_ref,
                payload=maskSecretsInObject(row_payload) if row_payload else None,
                errors=map_result.errors,
                warnings=map_result.warnings,
                meta={
                    "match_key": map_result.match_key.value if map_result.match_key else None,
                    "secret_candidate_fields": secret_fields,
                },
                store=should_store,
            )

        report.set_context(
            "enrich",
            {
                "rows_total": rows_total,
                "enriched_ok": enriched_ok,
                "enrich_failed": enrich_failed,
                "warnings_rows": warnings_rows,
                "vault_candidates_rows": vault_candidates_rows,
                "vault_candidates_fields_total": vault_candidates_fields_total,
            },
        )
        return 1 if enrich_failed > 0 else 0

    def iter_enriched_ok(
        self,
        row_source,
        transformer: TransformPipeline,
    ):
        """
        Назначение:
            Итератор обогащенных строк без ошибок.
        """
        extractor = Extractor(row_source)
        for collected in extractor.run():
            map_result = transformer.enrich(collected)
            if map_result.errors:
                continue
            yield map_result
