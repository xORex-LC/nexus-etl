from __future__ import annotations

import uuid
from typing import Any

from connector.planModels import Operation
from connector.matcher import MatchResult

class EmployeeDecisionPolicy:
    """
    Назначение/ответственность:
        Принимает решение по операции (create/update/skip) на основе
        результатов сопоставления и diff.
    """

    def decide(
        self,
        match_result: MatchResult,
        changes: dict[str, Any],
        desired_state: dict[str, Any],
    ) -> tuple[str, str | None]:
        """
        Контракт:
            Вход: match_result, changes (diff), desired_state.
            Выход: (op, resource_id) где op одно из Operation.* или "skip".
        Ошибки:
            Не обрабатывает конфликт — его должен отловить вызывающий код.
        Алгоритм:
            - not_found -> create c новым UUID
            - found + пустой diff -> skip
            - found + diff -> update с existing _id
        """
        if match_result.status == "not_found":
            return Operation.CREATE, str(uuid.uuid4())
        if not changes:
            return "skip", match_result.candidate.get("_id") if match_result.candidate else None
        return Operation.UPDATE, match_result.candidate.get("_id") if match_result.candidate else None
