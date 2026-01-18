from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .cacheRepo import getOrgByOuid
from .csvReader import CsvFormatError, CsvRowSource
from .loggingSetup import logEvent
from .planning.factory import PlannerFactory
from .planning.plan_builder import PlanBuilder
from .planning.registry import PlannerRegistry
from .sanitize import maskSecret
from .timeUtils import getNowIso
from .validation.deps import ValidationDependencies
from .validation.pipeline import logValidationFailure
from .validation.registry import ValidatorRegistry

def _mask_sensitive_item(item: dict[str, Any]) -> dict[str, Any]:
    """
    Назначение:
        Маскирует чувствительные поля плана перед записью в файл/отчёт.
    """
    clone = json.loads(json.dumps(item))
    desired = clone.get("desired_state")
    if isinstance(desired, dict) and "password" in desired:
        desired["password"] = maskSecret(desired["password"])
    return clone

def build_import_plan(
    conn,
    row_source,
    include_deleted_users: bool,
    dataset: str,
    logger,
    run_id: str,
    report,
    report_items_limit: int,
    report_items_success: bool,
    include_skipped_in_report: bool,
    planner_factory: PlannerFactory,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Строит план импорта на основе CSV и кэша.
    Возвращает (items, summary).
    """
    # TODO: when legacy planner path is fully removed, keep only dataset-driven registry usage
    builder = PlanBuilder(
        include_skipped_in_report=include_skipped_in_report,
        report_items_limit=report_items_limit,
        report_items_success=report_items_success,
    )
    class _OrgLookupAdapter:
        """Адаптер для получения организаций из кэша по протоколу валидатора."""

        def __init__(self, conn):
            self.conn = conn

        def get_org_by_id(self, ouid: int):
            return getOrgByOuid(self.conn, ouid)

    deps = ValidationDependencies(org_lookup=_OrgLookupAdapter(conn))
    validator_registry = ValidatorRegistry(deps)
    row_validator = validator_registry.create_row_validator(dataset)
    state = validator_registry.create_state()
    dataset_validator = validator_registry.create_dataset_validator(dataset, state)
    registry = PlannerRegistry(planner_factory)
    employee_planner = registry.get(dataset=dataset, include_deleted_users=include_deleted_users)

    try:
        for csvRow in row_source:
            builder.inc_rows_total()
            employee, validation = row_validator.validate(csvRow)
            dataset_validator.validate(employee, validation)
            errors = list(validation.errors)
            warnings = list(validation.warnings)
            desired = employee.__dict__.copy()
            match_key = validation.match_key

            if errors:
                builder.add_invalid(validation, errors, warnings)
                logValidationFailure(
                    logger,
                    run_id,
                    "import-plan",
                    validation,
                    None,
                    errors=errors,
                    warnings=warnings,
                )
                continue

            builder.inc_valid_rows()
            op_status, plan_item, match_result = employee_planner.plan_row(
                desired_state=desired,
                line_no=validation.line_no,
                match_key=match_key,
            )
            if op_status == "conflict":
                builder.add_conflict(validation.line_no, match_key, warnings)
                continue
            if op_status == "skip":
                builder.add_skip(validation.line_no, match_key, warnings)
                continue
            if plan_item:
                builder.add_plan_item(plan_item)
    except CsvFormatError as exc:
        logEvent(logger, logging.ERROR, run_id, "csv", f"CSV format error: {exc}")
        raise
    except OSError as exc:
        logEvent(logger, logging.ERROR, run_id, "csv", f"CSV read error: {exc}")
        raise

    build_result = builder.build()
    return build_result.items, {
        "rows_total": build_result.summary.rows_total,
        "valid_rows": build_result.summary.valid_rows,
        "failed_rows": build_result.summary.failed_rows,
        "planned_create": build_result.summary.planned_create,
        "planned_update": build_result.summary.planned_update,
        "skipped": build_result.summary.skipped,
    }, build_result.report_items, build_result.items_truncated

def write_plan_file(
    plan_items: list[dict[str, Any]],
    summary: dict[str, Any],
    meta: dict[str, Any],
    report_dir: str,
    run_id: str,
) -> str:
    plan_dir = Path(report_dir)
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plan_dir / f"plan_import_{run_id}.json"
    masked_items = [_mask_sensitive_item(item) for item in plan_items]
    data = {
        "meta": {
            "run_id": run_id,
            "generated_at": getNowIso(),
            **meta,
        },
        "summary": summary,
        "items": masked_items,
    }
    plan_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(plan_path)
