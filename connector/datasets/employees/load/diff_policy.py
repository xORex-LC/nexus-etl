from __future__ import annotations

from typing import Any

from connector.datasets.employees.load.diff_detail import build_user_diff


class EmployeesDiffPolicy:
    """
    Назначение/ответственность:
        Вычисляет изменения между желаемым и текущим состоянием пользователя.
    Ограничения:
        Игнорирует чувствительные поля (password) в diff для update.
    """

    def calculate_changes(self, existing: dict[str, Any] | None, desired: dict[str, Any]) -> dict[str, Any]:
        if not existing:
            return {}
        diff = build_user_diff(existing, desired)
        changes: dict[str, Any] = {}
        for field, change in diff.items():
            if field == "password":
                continue
            if isinstance(change, dict) and "to" in change:
                changes[field] = change.get("to")
        return changes
