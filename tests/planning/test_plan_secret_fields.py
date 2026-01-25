from __future__ import annotations

import json
from pathlib import Path

from connector.domain.planning.plan_builder import PlanBuilder
from connector.domain.planning.plan_models import PlanItem
from connector.infra.artifacts.plan_reader import readPlanFile


def test_plan_builder_serializes_secret_fields():
    builder = PlanBuilder(
        include_skipped_in_report=False,
        report_items_limit=10,
        identity_label="match_key",
        conflict_code="conflict",
        conflict_field="match_key",
    )
    builder.add_plan_item(
        PlanItem(
            row_id="r1",
            line_no=1,
            op="create",
            resource_id="id-1",
            desired_state={"email": "a@b.c"},
            changes={},
            secret_fields=["password"],
        )
    )
    result = builder.build()
    assert result.items[0]["secret_fields"] == ["password"]


def test_plan_reader_reads_secret_fields(tmp_path: Path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "meta": {"run_id": "r1", "generated_at": "now", "csv_path": "a.csv", "dataset": "employees"},
                "summary": {
                    "rows_total": 1,
                    "valid_rows": 1,
                    "failed_rows": 0,
                    "planned_create": 1,
                    "planned_update": 0,
                    "skipped": 0,
                },
                "items": [
                    {
                        "row_id": "line:1",
                        "line_no": 1,
                        "op": "create",
                        "resource_id": "id-1",
                        "desired_state": {"email": "a@b.c"},
                        "changes": {"mail": "a@b.c"},
                        "secret_fields": ["password"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    plan = readPlanFile(str(plan_path))
    assert plan.items[0].secret_fields == ["password"]
