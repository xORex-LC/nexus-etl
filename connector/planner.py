from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from .cacheRepo import getOrgByOuid
from .csvReader import CsvFormatError, readEmployeeRows
from .diff import build_user_diff
from .loggingSetup import logEvent
from .matcher import MatchResult, matchEmployeeByMatchKey
from .models import ValidationErrorItem
from .sanitize import maskSecret
from .timeUtils import getNowIso
from .validator import logValidationFailure
from .validation.pipeline import ValidatorFactory
from .validation.deps import ValidationDependencies

def _mask_sensitive_item(item: dict[str, Any]) -> dict[str, Any]:
    """Возвращает копию item с маскированием чувствительных данных."""

    masked = item.copy()
    desired = masked.get("desired")
    if isinstance(desired, dict) and "password" in desired:
        desired_copy = desired.copy()
        desired_copy["password"] = maskSecret(desired_copy.get("password"))
        masked["desired"] = desired_copy
    return masked

def _validation_error(code: str, field: str | None, message: str) -> ValidationErrorItem:
    return ValidationErrorItem(code=code, field=field, message=message)

def build_import_plan(
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
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Строит план импорта на основе CSV и кэша.
    Возвращает (items, summary).
    """
    plan_items: list[dict[str, Any]] = []
    rows_processed = 0
    failed_rows = 0
    planned_create = planned_update = skipped_rows = 0
    class _OrgLookupAdapter:
        """Адаптер для получения организаций из кэша по протоколу валидатора."""

        def __init__(self, conn):
            self.conn = conn

        def get_org_by_id(self, ouid: int):
            return getOrgByOuid(self.conn, ouid)

    factory = ValidatorFactory(
        ValidationDependencies(org_lookup=_OrgLookupAdapter(conn)),
        on_missing_org="error",
    )
    row_validator = factory.create_row_validator()
    state = factory.create_validation_context()
    dataset_validator = factory.create_dataset_validator(state)

    def append_report_item(item: dict[str, Any], status: str) -> int | None:
        if status not in ("failed", "skipped") and not report_items_success:
            return None
        if len(report.items) >= report_items_limit:
            try:
                report.meta.items_truncated = True
            except Exception:
                pass
            return None
        sanitized = _mask_sensitive_item(item)
        report.items.append(
            {
                "row_id": sanitized.get("row_id"),
                "action": sanitized.get("action"),
                "match_key": sanitized.get("match_key"),
                "existing_id": sanitized.get("existing_id"),
                "new_id": sanitized.get("new_id"),
                "desired": sanitized.get("desired"),
                "errors": sanitized.get("errors", []),
                "warnings": sanitized.get("warnings", []),
                "diff": sanitized.get("diff", {}),
                "status": status,
            }
        )
        return len(report.items) - 1

    try:
        for csvRow in readEmployeeRows(csv_path, hasHeader=csv_has_header):
            rows_processed += 1
            employee, validation = row_validator.validate(csvRow)
            dataset_validator.validate(employee, validation)
            errors = list(validation.errors)
            warnings = list(validation.warnings)
            desired = employee.__dict__.copy()
            match_key = validation.match_key

            if errors:
                failed_rows += 1
                item = {
                    "row_id": f"line:{validation.line_no}",
                    "line_no": validation.line_no,
                    "action": "error",
                    "match_key": match_key,
                    "desired": desired,
                    "errors": [e.__dict__ for e in errors],
                    "warnings": [w.__dict__ for w in warnings],
                }
                plan_items.append(item)
                idx = append_report_item(item, "failed")
                logValidationFailure(
                    logger,
                    run_id,
                    "import-plan",
                    validation,
                    idx,
                    errors=errors,
                    warnings=warnings,
                )
                continue

            match_result: MatchResult = matchEmployeeByMatchKey(conn, match_key, include_deleted_users)
            if match_result.status == "not_found":
                new_id = str(uuid.uuid4())
                diff = build_user_diff(None, employee.__dict__)
                planned_create += 1
                item = {
                    "row_id": f"line:{validation.line_no}",
                    "line_no": validation.line_no,
                    "action": "create",
                    "match_key": match_key,
                    "new_id": new_id,
                    "desired": desired,
                    "diff": diff,
                    "errors": [],
                    "warnings": [w.__dict__ for w in warnings],
                }
                plan_items.append(item)
                append_report_item(item, "planned_create")
                continue

            if match_result.status == "conflict":
                failed_rows += 1
                item = {
                    "row_id": f"line:{validation.line_no}",
                    "line_no": validation.line_no,
                    "action": "error",
                    "match_key": match_key,
                    "desired": desired,
                    "errors": [
                        {"code": "MATCH_CONFLICT", "field": "matchKey", "message": "multiple users with same match_key"}
                    ],
                    "warnings": [w.__dict__ for w in warnings],
                }
                plan_items.append(item)
                append_report_item(item, "failed")
                continue

            existing = match_result.candidate
            diff = build_user_diff(existing, employee.__dict__)
            if not diff:
                skipped_rows += 1
                item = {
                    "row_id": f"line:{validation.line_no}",
                    "line_no": validation.line_no,
                    "action": "skip",
                    "match_key": match_key,
                    "existing_id": existing.get("_id") if existing else None,
                    "desired": desired,
                    "errors": [],
                    "warnings": [w.__dict__ for w in warnings],
                }
                plan_items.append(item)
                append_report_item(item, "skipped")
                continue

            planned_update += 1
            item = {
                "row_id": f"line:{validation.line_no}",
                "line_no": validation.line_no,
                "action": "update",
                "match_key": match_key,
                "existing_id": existing.get("_id") if existing else None,
                "desired": desired,
                "diff": diff,
                "errors": [],
                "warnings": [w.__dict__ for w in warnings],
            }
            plan_items.append(item)
            append_report_item(item, "planned_update")
    except CsvFormatError as exc:
        logEvent(logger, logging.ERROR, run_id, "csv", f"CSV format error: {exc}")
        raise
    except OSError as exc:
        logEvent(logger, logging.ERROR, run_id, "csv", f"CSV read error: {exc}")
        raise

    summary = {
        "rows_total": rows_processed,
        "planned_create": planned_create,
        "planned_update": planned_update,
        "skipped": skipped_rows,
        "failed": failed_rows,
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