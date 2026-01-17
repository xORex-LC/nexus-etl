from __future__ import annotations

import logging

from .cacheDb import ensureSchema
from .protocols_services import ImportPlanServiceProtocol
from .loggingSetup import logEvent
from .planModels import Plan, PlanItem, PlanMeta, PlanSummary
from .planner import build_import_plan, write_plan_file
from .timeUtils import getNowIso

class ImportPlanService(ImportPlanServiceProtocol):
    """
    Оркестратор построения плана импорта.
    """

    def __init__(self) -> None:
        # Храним последний построенный план в памяти (без маскирования пароля),
        # чтобы apply мог использовать его напрямую без чтения файла.
        self.last_plan: Plan | None = None

    def run(
        self,
        conn,
        csv_path: str,
        csv_has_header: bool,
        include_deleted_users: bool,
        logger,
        run_id: str,
        report,
        report_items_limit: int,
        report_items_success: bool,
        report_dir: str,
    ) -> int:
        ensureSchema(conn)

        plan_items, summary = build_import_plan(
            conn=conn,
            csv_path=csv_path,
            csv_has_header=csv_has_header,
            include_deleted_users=include_deleted_users,
            logger=logger,
            run_id=run_id,
            report=report,
            report_items_limit=report_items_limit,
            report_items_success=report_items_success,
        )
        generated_at = getNowIso()
        plan_meta = {
            "csv_path": csv_path,
            "include_deleted_users": include_deleted_users,
        }
        plan_path = write_plan_file(plan_items, summary, plan_meta, report_dir, run_id)
        logEvent(logger, logging.INFO, run_id, "plan", f"Plan written: {plan_path}")

        # Сохраняем немаскированный план для дальнейшего использования.
        self.last_plan = Plan(
            meta=PlanMeta(
                run_id=run_id,
                generated_at=generated_at,
                csv_path=csv_path,
                plan_path=plan_path,
                include_deleted_users=include_deleted_users,
            ),
            summary=PlanSummary(
                rows_total=summary["rows_total"],
                planned_create=summary["planned_create"],
                planned_update=summary["planned_update"],
                skipped=summary["skipped"],
                failed=summary["failed"],
            ),
            items=[
                PlanItem(
                    row_id=item.get("row_id") or "",
                    line_no=item.get("line_no"),
                    action=item.get("action") or "",
                    match_key=item.get("match_key"),
                    existing_id=item.get("existing_id"),
                    new_id=item.get("new_id"),
                    desired=item.get("desired") or {},
                    diff=item.get("diff") or {},
                    errors=item.get("errors") or [],
                    warnings=item.get("warnings") or [],
                )
                for item in plan_items
            ],
        )

        report.meta.plan_file = plan_path
        report.meta.include_deleted_users = include_deleted_users
        report.meta.csv_rows_total = summary["rows_total"]
        report.meta.csv_rows_processed = summary["rows_total"]
        report.summary.planned_create = summary["planned_create"]
        report.summary.planned_update = summary["planned_update"]
        report.summary.skipped = summary["skipped"]
        report.summary.failed = summary["failed"]

        return 1 if summary["failed"] > 0 else 0
