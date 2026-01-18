from __future__ import annotations

import logging

from .cacheDb import ensureSchema
from .cacheRepo import getOrgByOuid
from .csvReader import CsvRowSource
from .loggingSetup import logEvent
from .planModels import Plan, PlanItem, PlanMeta, PlanSummary
from .planner import build_import_plan, write_plan_file
from .planning.adapters import CacheEmployeeLookup
from .planning.factory import PlannerFactory
from .planning.registry import PlannerRegistry
from .protocols_services import ImportPlanServiceProtocol
from .timeUtils import getNowIso
from .validation.deps import ValidationDependencies
from .validation.registry import ValidatorRegistry

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

        class _OrgLookupAdapter:
            """Адаптер org_lookup для валидатора поверх кэша."""

            def __init__(self, conn):
                self.conn = conn

            def get_org_by_id(self, ouid: int):
                return getOrgByOuid(self.conn, ouid)

        planner_factory = PlannerFactory(employee_lookup=CacheEmployeeLookup(conn))
        planner_registry = PlannerRegistry(planner_factory)
        deps = ValidationDependencies(org_lookup=_OrgLookupAdapter(conn))
        validator_registry = ValidatorRegistry(deps)
        row_source = CsvRowSource(csv_path, csv_has_header)
        plan_result = build_import_plan(
            row_source=row_source,
            include_deleted_users=include_deleted_users,
            dataset=dataset,
            logger=logger,
            run_id=run_id,
            report=report,
            report_items_limit=report_items_limit,
            report_items_success=report_items_success,
            include_skipped_in_report=include_skipped_in_report,
            validator_registry=validator_registry,
            planner_registry=planner_registry,
        )
        generated_at = getNowIso()
        plan_meta = {
            "csv_path": csv_path,
            "include_deleted_users": include_deleted_users,
            "dataset": dataset,
        }
        summary_dict = {
            "rows_total": plan_result.summary.rows_total,
            "valid_rows": plan_result.summary.valid_rows,
            "failed_rows": plan_result.summary.failed_rows,
            "planned_create": plan_result.summary.planned_create,
            "planned_update": plan_result.summary.planned_update,
            "skipped": plan_result.summary.skipped,
        }
        plan_path = write_plan_file(plan_result.items, summary_dict, plan_meta, report_dir, run_id)
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
                rows_total=plan_result.summary.rows_total,
                valid_rows=plan_result.summary.valid_rows,
                failed_rows=plan_result.summary.failed_rows,
                planned_create=plan_result.summary.planned_create,
                planned_update=plan_result.summary.planned_update,
                skipped=plan_result.summary.skipped,
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
                for item in plan_result.items
            ],
        )

        report.meta.plan_file = plan_path
        report.meta.include_deleted_users = include_deleted_users
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
