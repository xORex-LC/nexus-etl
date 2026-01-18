from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .cacheRepo import getOrgByOuid
from .csvReader import CsvFormatError, CsvRowSource
from .loggingSetup import logEvent
from .planModels import EntityType, Operation
from .planning.factory import PlannerFactory
from .sanitize import maskSecret
from .timeUtils import getNowIso
from .validation.deps import ValidationDependencies
from .validation.pipeline import ValidatorFactory, logValidationFailure
from .validation.registry import ValidatorRegistry

def _mask_sensitive_item(item: dict[str, Any]) -> dict[str, Any]:
    """
    Назначение:
        Маскирует чувствительные поля плана перед записью в отчёт/файл.
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
    plan_items: list[dict[str, Any]] = []
    rows_processed = 0
    valid_rows = 0
    failed_rows = 0
    planned_create = planned_update = skipped_rows = 0
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
    from .planning.registry import PlannerRegistry

    registry = PlannerRegistry(planner_factory)
    employee_planner = registry.get(dataset=dataset, include_deleted_users=include_deleted_users)

    def append_report_item(item: dict[str, Any], status: str) -> int | None:
        """
        Добавляет элемент в отчёт с учётом лимита.
        """
        if status == "skipped" and not include_skipped_in_report:
            return None
        if status not in ("failed", "skipped") and not report_items_success:
            return None
        if len(report.items) >= report_items_limit:
            try:
                report.meta.items_truncated = True
            except Exception:
                pass
            return None
        sanitized = _mask_sensitive_item(item)
        report.items.append(sanitized)
        return len(report.items) - 1

    try:
        for csvRow in row_source:
            rows_processed += 1
            employee, validation = row_validator.validate(csvRow)
            dataset_validator.validate(employee, validation)
            errors = list(validation.errors)
            warnings = list(validation.warnings)
            desired = employee.__dict__.copy()
            match_key = validation.match_key

            if errors:
                failed_rows += 1
                append_report_item(
                    {
                        "row_id": f"line:{validation.line_no}",
                        "line_no": validation.line_no,
                        "status": "invalid",
                        "match_key": match_key,
                        "errors": [e.__dict__ for e in errors],
                        "warnings": [w.__dict__ for w in warnings],
                    },
                    "failed",
                )
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

            valid_rows += 1
            op_status, plan_item, match_result = employee_planner.plan_row(
                desired_state=desired,
                line_no=validation.line_no,
                match_key=match_key,
            )
            if op_status == "conflict":
                failed_rows += 1
                append_report_item(
                    {
                        "row_id": f"line:{validation.line_no}",
                        "line_no": validation.line_no,
                        "status": "invalid",
                        "match_key": match_key,
                        "errors": [
                            {"code": "MATCH_CONFLICT", "field": "matchKey", "message": "multiple users with same match_key"}
                        ],
                        "warnings": [w.__dict__ for w in warnings],
                    },
                    "failed",
                )
                continue
            if op_status == "skip":
                skipped_rows += 1
                append_report_item(
                    {
                        "row_id": f"line:{validation.line_no}",
                        "line_no": validation.line_no,
                        "status": "skipped",
                        "match_key": match_key,
                        "warnings": [w.__dict__ for w in warnings],
                    },
                    "skipped",
                )
                continue
            if plan_item:
                if plan_item.op == Operation.CREATE:
                    planned_create += 1
                elif plan_item.op == Operation.UPDATE:
                    planned_update += 1
                plan_items.append(plan_item.__dict__)
    except CsvFormatError as exc:
        logEvent(logger, logging.ERROR, run_id, "csv", f"CSV format error: {exc}")
        raise
    except OSError as exc:
        logEvent(logger, logging.ERROR, run_id, "csv", f"CSV read error: {exc}")
        raise

    summary = {
        "rows_total": rows_processed,
        "valid_rows": valid_rows,
        "failed_rows": failed_rows,
        "planned_create": planned_create,
        "planned_update": planned_update,
        "skipped": skipped_rows,
    }
    return plan_items, summary

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
