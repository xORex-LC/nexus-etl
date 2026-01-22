from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from connector.domain.planning.plan_models import Plan, PlanItem, PlanMeta, PlanSummary
from connector.common.sanitize import isMaskedSecret


def _get_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _load_plan_raw(path: str) -> tuple[dict, dict, list]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid plan format: root must be object")
    meta_raw = data.get("meta", {}) if isinstance(data.get("meta"), dict) else {}
    summary_raw = data.get("summary", {}) if isinstance(data.get("summary"), dict) else {}
    items_raw = data.get("items", [])
    if not isinstance(items_raw, list):
        raise ValueError("Invalid plan format: items must be list")
    return meta_raw, summary_raw, items_raw


def _resolve_dataset(meta_raw: dict, items_raw: list) -> str:
    dataset = _get_str(meta_raw.get("dataset") or meta_raw.get("dataset_name"))
    if dataset:
        return dataset
    raise ValueError("Invalid plan format: dataset is missing in meta")


def _build_plan(meta_raw: dict, summary_raw: dict, items_raw: list, path: str) -> Plan:
    dataset = _resolve_dataset(meta_raw, items_raw)

    meta = PlanMeta(
        run_id=_get_str(meta_raw.get("run_id")),
        generated_at=_get_str(meta_raw.get("generated_at")),
        dataset=dataset,
        csv_path=_get_str(meta_raw.get("csv_path")),
        plan_path=path,
        include_deleted_users=meta_raw.get("include_deleted_users"),
    )
    summary = PlanSummary(
        rows_total=int(summary_raw.get("rows_total") or 0),
        valid_rows=int(summary_raw.get("valid_rows") or 0),
        failed_rows=int(summary_raw.get("failed_rows") or 0),
        planned_create=int(summary_raw.get("planned_create") or 0),
        planned_update=int(summary_raw.get("planned_update") or 0),
        skipped=int(summary_raw.get("skipped") or 0),
    )

    items: list[PlanItem] = []
    for raw in items_raw:
        if not isinstance(raw, dict):
            continue
        desired_raw = raw.get("desired_state") if isinstance(raw.get("desired_state"), dict) else {}
        legacy_dataset = _get_str(raw.get("dataset"))
        legacy_entity = _get_str(raw.get("entity_type"))
        if legacy_dataset and legacy_dataset != dataset:
            raise ValueError(f"Plan item dataset mismatch: meta={dataset}, item={legacy_dataset}")
        if legacy_entity and legacy_entity != dataset:
            raise ValueError(f"Plan item entity_type mismatch: meta={dataset}, item={legacy_entity}")
        if isMaskedSecret(desired_raw.get("password")):
            desired_raw = {k: v for k, v in desired_raw.items() if k != "password"}
        items.append(
            PlanItem(
                row_id=_get_str(raw.get("row_id")) or "",
                line_no=raw.get("line_no"),
                op=_get_str(raw.get("op")) or "",
                resource_id=_get_str(raw.get("resource_id")) or "",
                desired_state=desired_raw if isinstance(desired_raw, dict) else {},
                changes=raw.get("changes") if isinstance(raw.get("changes"), dict) else {},
                source_ref=raw.get("source_ref") if isinstance(raw.get("source_ref"), dict) else None,
            )
        )

    return Plan(meta=meta, summary=summary, items=items)


def readPlanFile(path: str) -> Plan:
    meta_raw, summary_raw, items_raw = _load_plan_raw(path)
    return _build_plan(meta_raw, summary_raw, items_raw, path)
