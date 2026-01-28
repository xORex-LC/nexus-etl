from __future__ import annotations

import json
from pathlib import Path

from connector.domain.planning.plan_builder import PlanBuilder
from connector.domain.planning.match_models import ResolvedRow, ResolveOp
from connector.domain.models import Identity, RowRef
from connector.infra.artifacts.plan_reader import readPlanFile


def test_plan_builder_serializes_secret_fields():
    builder = PlanBuilder()
    resolved = ResolvedRow(
        row_ref=RowRef(line_no=1, row_id="r1", identity_primary="match_key", identity_value="A|B|C|1"),
        identity=Identity(primary="match_key", values={"match_key": "A|B|C|1"}),
        op=ResolveOp.CREATE,
        desired_state={"email": "a@b.c"},
        changes={},
        resource_id="id-1",
        secret_fields=["password"],
    )
    builder.add_resolved(resolved)
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
