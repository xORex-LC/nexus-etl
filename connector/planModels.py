from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PlanMeta:
    run_id: str | None
    generated_at: str | None
    csv_path: str | None
    plan_path: str | None
    include_deleted_users: bool | None
    on_missing_org: str | None


@dataclass
class PlanSummary:
    rows_total: int
    planned_create: int
    planned_update: int
    skipped: int
    failed: int


@dataclass
class PlanItem:
    row_id: str
    line_no: int | None
    action: str
    match_key: str | None
    existing_id: str | None
    new_id: str | None
    desired: dict[str, Any]
    diff: dict[str, Any]
    errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]]


@dataclass
class Plan:
    meta: PlanMeta
    summary: PlanSummary
    items: list[PlanItem]
