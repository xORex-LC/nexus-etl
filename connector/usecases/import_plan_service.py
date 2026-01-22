from __future__ import annotations

import logging

from connector.infra.cache.db import ensureSchema
from connector.infra.sources.csv_reader import CsvRowSource
from connector.infra.logging.setup import logEvent
from connector.infra.artifacts.plan_writer import write_plan_file
from connector.usecases.ports import ImportPlanServiceProtocol
from connector.common.time import getNowIso
from connector.usecases.plan_usecase import PlanUseCase
from connector.datasets.registry import get_spec

class ImportPlanService(ImportPlanServiceProtocol):
    """
    Оркестратор построения плана импорта.
    """

    def run(
        self,
        conn,
        csv_path: str,
        csv_has_header: bool,
        include_deleted: bool,
        dataset: str,
        logger,
        run_id: str,
        report,
        report_items_limit: int,
        include_skipped_in_report: bool,
        report_dir: str,
        settings=None,
    ) -> int:
        ensureSchema(conn)
        generated_at = getNowIso()

        dataset_spec = get_spec(dataset)
        validation_deps = dataset_spec.build_validation_deps(conn, settings)
        planning_deps = dataset_spec.build_planning_deps(conn, settings)
        row_source = CsvRowSource(csv_path, csv_has_header)
        use_case = PlanUseCase(
            report_items_limit=report_items_limit,
            include_skipped_in_report=include_skipped_in_report,
        )
        plan_result = use_case.run(
            row_source=row_source,
            dataset_spec=dataset_spec,
            include_deleted=include_deleted,
            logger=logger,
            run_id=run_id,
            validation_deps=validation_deps,
            planning_deps=planning_deps,
        )
        plan_meta = {
            "csv_path": csv_path,
            "include_deleted": include_deleted,
            "dataset": dataset,
        }
        plan_path = write_plan_file(
            plan_items=plan_result.items,
            summary=plan_result.summary_as_dict(),
            meta=plan_meta,
            report_dir=report_dir,
            run_id=run_id,
            generated_at=generated_at,
        )
        logEvent(logger, logging.INFO, run_id, "plan", f"Plan written: {plan_path}")

        report.meta.plan_file = plan_path
        report.meta.include_deleted = include_deleted
        report.meta.csv_rows_total = plan_result.summary.rows_total
        report.meta.csv_rows_processed = plan_result.summary.rows_total
        report.summary.planned_create = plan_result.summary.planned_create
        report.summary.planned_update = plan_result.summary.planned_update
        report.summary.skipped = plan_result.summary.skipped
        report.summary.failed = plan_result.summary.failed_rows
        if plan_result.items_truncated:
            report.meta.items_truncated = True
        report.items = plan_result.report_items

        return 1 if plan_result.summary.failed_rows > 0 else 0
