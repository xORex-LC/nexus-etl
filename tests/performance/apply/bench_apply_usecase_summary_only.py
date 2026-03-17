"""
Бенчмарк: apply_plan на N=50k элементов, все операции успешны.
Проверяет O(1) память для outcomes (для OK-элементов outcomes не хранятся).

Запуск:
    .venv/bin/python tests/performance/apply/bench_apply_usecase_summary_only.py --fast
"""

from __future__ import annotations

import pyperf

from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.planning.plan_models import Plan, PlanItem, PlanMeta, PlanSummary
from connector.domain.ports.target.execution import ExecutionResult, RequestSpec
from connector.usecases.import_apply_service import ImportApplyService

CATALOG = build_catalog("employees", strict=True)
N = 50_000


class OkExecutor:
    def execute(self, spec: RequestSpec) -> ExecutionResult:
        return ExecutionResult(ok=True, answer_code=200, response_payload={"_id": "id-ok"})


def _build_plan(n: int) -> Plan:
    items = [
        PlanItem(
            row_id=f"line:{i}",
            line_no=i,
            op="create",
            target_id=f"id-{i}",
            desired_state={
                "email": f"u{i}@example.com",
                "last_name": "L",
                "first_name": "F",
                "middle_name": "M",
                "is_logon_disable": False,
                "user_name": f"u{i}",
                "phone": "+1",
                "password": "secret",
                "personnel_number": str(i),
                "manager_id": None,
                "organization_id": 5,
                "position": "P",
                "usr_org_tab_num": "TAB",
            },
            changes={},
            source_ref={"match_key": f"mk-{i}"},
        )
        for i in range(n)
    ]
    return Plan(
        meta=PlanMeta(
            run_id="bench",
            generated_at=None,
            csv_path=None,
            plan_path=None,
            include_deleted=False,
            dataset="employees",
        ),
        summary=PlanSummary(
            rows_total=n,
            valid_rows=n,
            failed_rows=0,
            planned_create=n,
            planned_update=0,
            skipped=0,
        ),
        items=items,
    )


def bench_apply_all_ok(loops: int) -> float:
    plan = _build_plan(N)
    from connector.datasets.registry import get_spec

    adapter = get_spec("employees").get_apply_adapter()
    executor = OkExecutor()
    service = ImportApplyService(executor)

    total = 0.0
    timer = pyperf.perf_counter
    for _ in range(loops):
        t0 = timer()
        result = service.apply_plan(
            plan=plan,
            catalog=CATALOG,
            apply_adapter=adapter,
            stop_on_first_error=False,
            max_actions=None,
            max_item_outcomes=100,
        )
        total += timer() - t0

        assert result.primary_code == SystemErrorCode.OK
        assert result.summary.created == N
        assert len(result.item_outcomes) == 0

    return total


if __name__ == "__main__":
    runner = pyperf.Runner()
    runner.bench_time_func(f"apply_plan_{N}_items_all_ok", bench_apply_all_ok)
