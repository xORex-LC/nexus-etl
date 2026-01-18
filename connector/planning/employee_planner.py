from __future__ import annotations

from typing import Any

from connector.planModels import EntityType, Operation, PlanItem
from connector.matcher import MatchResult
from .decision import EmployeeDecisionPolicy
from .differ import EmployeeDiffer
from .matcher import EmployeeMatcher

class EmployeePlanner:
    """
    Назначение/ответственность:
        Собирает решение по одному сотруднику: create/update/skip.
    Взаимодействия:
        Делегирует сопоставление matcher, diff — differ, решение — decision policy.
    Ограничения:
        Работает с уже валидированными данными.
    """

    def __init__(
        self,
        matcher: EmployeeMatcher,
        differ: EmployeeDiffer,
        decision: EmployeeDecisionPolicy,
    ):
        self.matcher = matcher
        self.differ = differ
        self.decision = decision

    def plan_row(
        self,
        desired_state: dict[str, Any],
        line_no: int,
        match_key: str,
    ) -> tuple[str, PlanItem | None, MatchResult | None]:
        """
        Назначение:
            Решить, какую операцию сформировать по строке CSV.
        Контракт (вход/выход):
            - Вход: desired_state, line_no, match_key.
            - Выход: (status, plan_item|None, match_result|None), где status = create/update/skip/conflict.
        Ошибки/исключения:
            Пробрасывает исключения matcher/differ/decision.
        Алгоритм:
            matcher.match -> diff -> decision -> PlanItem (кроме skip/conflict).
        """
        match_result = self.matcher.match(match_key)
        if match_result.status == "conflict":
            return "conflict", None, match_result

        changes = self.differ.calculate_changes(match_result.candidate, desired_state)
        op, resource_id = self.decision.decide(match_result, changes, desired_state)

        if op == "skip":
            return "skip", None, match_result

        plan_item = PlanItem(
            row_id=f"line:{line_no}",
            line_no=line_no,
            entity_type=EntityType.EMPLOYEE,
            op=op,
            resource_id=resource_id or "",
            desired_state=desired_state,
            changes=changes,
            source_ref={"match_key": match_key},
        )
        return op, plan_item, match_result
