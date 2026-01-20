from __future__ import annotations

from connector.planModels import PlanItem
from connector.domain.ports.execution import RequestSpec
from connector.domain.mappers.user_payload import buildUserUpsertPayload


class EmployeesApplyAdapter:
    """
    Назначение/ответственность:
        Преобразует PlanItem (employees) в RequestSpec для исполнения.
    Взаимодействия:
        Используется слоем apply для построения запроса к API.
    Ограничения:
        Знает конкретный endpoint/метод и payload employees.
    """

    def to_request(self, item: PlanItem) -> RequestSpec:
        """
        Контракт (вход/выход):
            Вход: PlanItem с op=create|update и desired_state.
            Выход: RequestSpec с методом PUT и payload.
        Алгоритм:
            - Формирует путь /ankey/managed/user/{resource_id}.
            - Сборку payload делегирует buildUserUpsertPayload.
        """
        path = f"/ankey/managed/user/{item.resource_id}"
        payload = buildUserUpsertPayload(item.desired_state)
        return RequestSpec.put(path=path, json=payload)
