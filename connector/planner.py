from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .csvReader import CsvFormatError
from .loggingSetup import logEvent
from .planning.plan_builder import PlanBuilder, PlanBuildResult
from .planning.registry import PlannerRegistry
from .sanitize import maskSecret
from .timeUtils import getNowIso
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
    row_source,
    include_deleted_users: bool,
    dataset: str,
    logger,
    run_id: str,
    report,
    report_items_limit: int,
    report_items_success: bool,
    include_skipped_in_report: bool,
    validator_registry: ValidatorRegistry,
    planner_registry: PlannerRegistry,
) -> PlanBuildResult:
    """
    Строит план импорта на основе источника строк и зависимостей планировщика.
    Возвращает PlanBuildResult (items, summary, report_items, items_truncated).
    """
    builder = PlanBuilder(
        include_skipped_in_report=include_skipped_in_report,
        report_items_limit=report_items_limit,
        report_items_success=report_items_success,
    )
    row_validator = validator_registry.create_row_validator(dataset)
    state = validator_registry.create_state()
    dataset_validator = validator_registry.create_dataset_validator(dataset, state)
    employee_planner = planner_registry.get(dataset=dataset, include_deleted_users=include_deleted_users)

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

    return builder.build()

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
