from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .planModels import Plan, PlanItem, PlanMeta, PlanSummary
from .sanitize import isMaskedSecret


def _get_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def readPlanFile(path: str) -> Plan:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid plan format: root must be object")

    meta_raw = data.get("meta", {}) if isinstance(data.get("meta"), dict) else {}
    summary_raw = data.get("summary", {}) if isinstance(data.get("summary"), dict) else {}
    items_raw = data.get("items", [])
    if not isinstance(items_raw, list):
        raise ValueError("Invalid plan format: items must be list")

    meta = PlanMeta(
        run_id=_get_str(meta_raw.get("run_id")),
        generated_at=_get_str(meta_raw.get("generated_at")),
        csv_path=_get_str(meta_raw.get("csv_path")),
        plan_path=path,
        include_deleted_users=meta_raw.get("include_deleted_users"),
    )
    summary = PlanSummary(
        rows_total=int(summary_raw.get("rows_total") or 0),
        planned_create=int(summary_raw.get("planned_create") or 0),
        planned_update=int(summary_raw.get("planned_update") or 0),
        skipped=int(summary_raw.get("skipped") or 0),
        failed=int(summary_raw.get("failed") or 0),
    )

    items: list[PlanItem] = []
    for raw in items_raw:
        if not isinstance(raw, dict):
            continue
        desired_raw = raw.get("desired") if isinstance(raw.get("desired"), dict) else {}
        if isMaskedSecret(desired_raw.get("password")):
            desired_raw = {k: v for k, v in desired_raw.items() if k != "password"}
        items.append(
            PlanItem(
                row_id=_get_str(raw.get("row_id")) or "",
                line_no=raw.get("line_no"),
                action=_get_str(raw.get("action")) or "",
                match_key=_get_str(raw.get("match_key")),
                existing_id=_get_str(raw.get("existing_id")),
                new_id=_get_str(raw.get("new_id")),
                desired=desired_raw if isinstance(desired_raw, dict) else {},
                diff=raw.get("diff") if isinstance(raw.get("diff"), dict) else {},
                errors=raw.get("errors") if isinstance(raw.get("errors"), list) else [],
                warnings=raw.get("warnings") if isinstance(raw.get("warnings"), list) else [],
            )
        )

    return Plan(meta=meta, summary=summary, items=items)
