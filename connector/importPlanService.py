from __future__ import annotations

import logging

from .cacheDb import ensureSchema
from .protocols_services import ImportPlanServiceProtocol
from .loggingSetup import logEvent
from .planModels import Plan, PlanItem, PlanMeta, PlanSummary
from .planner import build_import_plan, write_plan_file
from .planning.adapters import CacheEmployeeLookup
from .planning.factory import PlannerFactory
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
        dataset: str,
        logger,
        run_id: str,
        report,
        report_items_limit: int,
        report_items_success: bool,
        include_skipped_in_report: bool,
        report_dir: str,
    ) -> int:
        ensureSchema(conn)

        planner_factory = PlannerFactory(employee_lookup=CacheEmployeeLookup(conn))
        row_source = CsvRowSource(csv_path, csv_has_header)
        plan_items, summary = build_import_plan(
            conn=conn,
            row_source=row_source,
            include_deleted_users=include_deleted_users,
            dataset=dataset,
            logger=logger,
            run_id=run_id,
            report=report,
            report_items_limit=report_items_limit,
            report_items_success=report_items_success,
            include_skipped_in_report=include_skipped_in_report,
            planner_factory=planner_factory,
        )
        generated_at = getNowIso()
        plan_meta = {
            "csv_path": csv_path,
            "include_deleted_users": include_deleted_users,
            "dataset": dataset,
        }
        plan_path = write_plan_file(plan_items, summary, plan_meta, report_dir, run_id)
        logEvent(logger, logging.INFO, run_id, "plan", f"Plan written: {plan_path}")

        # Сохраняем немаскированный план для дальнейшего использования.
        self.last_plan = Plan(
            meta=PlanMeta(
                run_id=run_id,
                generated_at=generated_at,
                dataset=dataset,
                csv_path=csv_path,
                plan_path=plan_path,
                include_deleted_users=include_deleted_users,
            ),
            summary=PlanSummary(
                rows_total=summary["rows_total"],
                valid_rows=summary.get("valid_rows", 0),
                failed_rows=summary.get("failed_rows", 0),
                planned_create=summary["planned_create"],
                planned_update=summary["planned_update"],
                skipped=summary["skipped"],
            ),
            items=[
                PlanItem(
                    row_id=item.get("row_id") or "",
                    line_no=item.get("line_no"),
                    entity_type=item.get("entity_type") or "",
                    op=item.get("op") or "",
                    resource_id=item.get("resource_id") or "",
                    desired_state=item.get("desired_state") or {},
                    changes=item.get("changes") or {},
                    source_ref=item.get("source_ref") or {},
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
        report.summary.failed = summary.get("failed_rows", 0)

        return 1 if summary.get("failed_rows", 0) > 0 else 0
