from __future__ import annotations

import logging

from .cacheDb import ensureSchema
from .loggingSetup import logEvent
from .planner import build_import_plan, write_plan_file


class ImportPlanService:
    """
    Оркестратор построения плана импорта.
    """

    def run(
        self,
        conn,
        csv_path: str,
        csv_has_header: bool,
        include_deleted_users: bool,
        on_missing_org: str,
        logger,
        run_id: str,
        report,
        report_items_limit: int,
        report_items_success: bool,
        report_dir: str,
    ) -> int:
        if on_missing_org not in ("error", "warn-and-skip"):
            raise ValueError("on_missing_org must be 'error' or 'warn-and-skip'")

        ensureSchema(conn)

        plan_items, summary = build_import_plan(
            conn=conn,
            csv_path=csv_path,
            csv_has_header=csv_has_header,
            include_deleted_users=include_deleted_users,
            on_missing_org=on_missing_org,
            logger=logger,
            run_id=run_id,
            report=report,
            report_items_limit=report_items_limit,
            report_items_success=report_items_success,
        )
        plan_meta = {
            "csv_path": csv_path,
            "include_deleted_users": include_deleted_users,
            "on_missing_org": on_missing_org,
        }
        plan_path = write_plan_file(plan_items, summary, plan_meta, report_dir, run_id)
        logEvent(logger, logging.INFO, run_id, "plan", f"Plan written: {plan_path}")

        report.meta.plan_file = plan_path
        report.meta.include_deleted_users = include_deleted_users
        report.meta.on_missing_org = on_missing_org
        report.meta.mode = "plan"
        report.meta.csv_rows_total = summary["rows_total"]
        report.meta.csv_rows_processed = summary["rows_total"]
        report.summary.planned_create = summary["planned_create"]
        report.summary.planned_update = summary["planned_update"]
        report.summary.skipped = summary["skipped"]
        report.summary.failed = summary["failed"]

        return 1 if summary["failed"] > 0 else 0
