from __future__ import annotations

from typing import Any

from connector.diff import build_user_diff

class EmployeeDiffer:
    """
    Назначение/ответственность:
        Вычисляет изменения между желаемым и текущим состоянием пользователя.

    Ограничения:
        Игнорирует чувствительные поля (пароль) в diff для update.
    """

    def calculate_changes(self, existing: dict[str, Any] | None, desired: dict[str, Any]) -> dict[str, Any]:
        """
        Контракт:
            Вход: existing — текущая запись, desired — желаемое состояние.
            Выход: словарь изменений field -> new_value.
        Ошибки:
            Исключения работы с diff пробрасываются.
        Алгоритм:
            Использует build_user_diff, оставляя только целевые значения и
            отбрасывая password.
        """
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
