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
from .validator import buildMatchKey, logValidationFailure, validateEmployeeRow


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
    matchkey_seen: dict[str, int] = {}
    usr_org_tab_seen: dict[str, int] = {}

    def append_report_item(item: dict[str, Any], status: str) -> int | None:
        if status not in ("failed", "skipped") and not report_items_success:
            return None
        if len(report.items) >= report_items_limit:
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
            employee, validation = validateEmployeeRow(csvRow)
            errors = list(validation.errors)
            warnings = list(validation.warnings)
            desired = employee.__dict__.copy()

            if validation.match_key_complete:
                prev_line = matchkey_seen.get(validation.match_key)
                if prev_line is not None:
                    errors.append(
                        _validation_error("DUPLICATE_MATCHKEY", "matchKey", f"duplicate of line {prev_line}")
                    )
                else:
                    matchkey_seen[validation.match_key] = validation.line_no
            else:
                errors.append(_validation_error("MATCH_KEY_MISSING", "matchKey", "match_key cannot be built"))

            if validation.usr_org_tab_num:
                prev_line = usr_org_tab_seen.get(validation.usr_org_tab_num)
                if prev_line is not None:
                    errors.append(
                        _validation_error("DUPLICATE_USR_ORG_TAB_NUM", "usrOrgTabNum", f"duplicate of line {prev_line}")
                    )
                else:
                    usr_org_tab_seen[validation.usr_org_tab_num] = validation.line_no

            match_key = buildMatchKey(employee)
            org_exists = None
            if employee.organization_id is not None:
                org_exists = getOrgByOuid(conn, employee.organization_id)
            if org_exists is None:
                if on_missing_org == "error":
                    errors.append(
                        _validation_error("ORG_NOT_FOUND", "organization_id", "organization_id not found in cache")
                    )
                elif on_missing_org == "warn-and-skip":
                    warnings.append(
                        _validation_error("ORG_NOT_FOUND", "organization_id", "organization_id not found in cache")
                    )

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

            if on_missing_org == "warn-and-skip" and org_exists is None:
                skipped_rows += 1
                item = {
                    "row_id": f"line:{validation.line_no}",
                    "line_no": validation.line_no,
                    "action": "skip",
                    "match_key": match_key,
                    "desired": desired,
                    "errors": [],
                    "warnings": [w.__dict__ for w in warnings]
                    + [
                        {"code": "ORG_NOT_FOUND", "field": "organization_id", "message": "organization_id not found in cache"}
                    ],
                }
                plan_items.append(item)
                append_report_item(item, "skipped")
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
