from __future__ import annotations

import uuid
from typing import Any

from connector.planModels import Operation
from connector.matcher import MatchResult

class EmployeeDecisionPolicy:
    """
    Назначение/ответственность:
        Решает, нужна ли операция create/update/skip на основе сопоставления и diff.
    Ограничения:
        Конфликты обрабатываются выше по стеку.
    """

    def decide(
        self,
        match_result: MatchResult,
        changes: dict[str, Any],
        desired_state: dict[str, Any],
    ) -> tuple[str, str | None]:
        """
        Назначение:
            Определить действие плана по текущему состоянию и diff.
        Контракт (вход/выход):
            - Вход: match_result, changes, desired_state.
            - Выход: (op, resource_id) где op = Operation.* или "skip".
        Ошибки/исключения:
            Конфликт не обрабатывается (решается вызывающим кодом).
        Алгоритм:
            not_found -> create (новый UUID)
            found + diff пуст -> skip
            found + diff -> update (id из кандидата)
        """
        if match_result.status == "not_found":
            return Operation.CREATE, str(uuid.uuid4())
        if not changes:
            return "skip", match_result.candidate.get("_id") if match_result.candidate else None
        return Operation.UPDATE, match_result.candidate.get("_id") if match_result.candidate else None
