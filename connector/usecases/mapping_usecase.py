from __future__ import annotations

import logging
from dataclasses import asdict

from connector.common.sanitize import maskSecretsInObject
from connector.domain.transform.extractor import Extractor
from connector.domain.transform.pipeline import TransformPipeline
from connector.domain.models import RowRef, DiagnosticStage
from connector.domain.diagnostics.boundary import diagnostic_boundary
from connector.domain.diagnostics.context import get_catalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode


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
        transformer: TransformPipeline,
        dataset: str,
        logger: logging.Logger,
        run_id: str,
        report,
    ) -> CommandResult:
        rows_total = 0
        mapped_ok = 0
        mapping_failed = 0
        warnings_rows = 0
        vault_candidates_rows = 0
        vault_candidates_fields_total = 0

        report.set_meta(dataset=dataset, items_limit=self.report_items_limit)

        extractor = Extractor(row_source)
        for collected in extractor.run():
            rows_total += 1
            boundary_errors: list = []
            map_result = None
            row_ref = collected.row_ref or RowRef(
                line_no=collected.record.line_no,
                row_id=collected.record.record_id,
                identity_primary=None,
                identity_value=None,
            )
            with diagnostic_boundary(
                stage=DiagnosticStage.MAP,
                catalog=get_catalog(),
                sink=boundary_errors,
                record_ref=row_ref,
            ):
                map_result = transformer.map_source(collected)
            if boundary_errors:
                mapping_failed += 1
                report.add_item(
                    status="FAILED",
                    row_ref=row_ref,
                    payload=None,
                    errors=boundary_errors,
                    warnings=[],
                    meta={"match_key": None, "secret_candidate_fields": []},
                    store=True,
                )
                continue
            if map_result is None:
                mapping_failed += 1
                report.add_item(
                    status="FAILED",
                    row_ref=row_ref,
                    payload=None,
                    errors=[],
                    warnings=[],
                    meta={"match_key": None, "secret_candidate_fields": []},
                    store=True,
                )
                continue

            has_errors = len(map_result.errors) > 0
            status = "FAILED" if has_errors else "OK"
            if has_errors:
                mapping_failed += 1
            else:
                mapped_ok += 1

            if map_result.warnings:
                warnings_rows += 1

            secret_fields = list(map_result.secret_candidates.keys())
            if secret_fields:
                vault_candidates_rows += 1
                vault_candidates_fields_total += len(secret_fields)

            should_store = status == "FAILED" or self.include_mapped_items
            row_ref = map_result.row_ref or row_ref
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
            "mapping",
            {
                "rows_total": rows_total,
                "mapped_ok": mapped_ok,
                "mapping_failed": mapping_failed,
                "warnings_rows": warnings_rows,
                "vault_candidates_rows": vault_candidates_rows,
                "vault_candidates_fields_total": vault_candidates_fields_total,
            },
        )
        result = CommandResult()
        if mapping_failed > 0:
            result.add_code(SystemErrorCode.DATA_INVALID)
        else:
            result.add_code(SystemErrorCode.OK)
        return result
