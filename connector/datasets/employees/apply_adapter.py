from __future__ import annotations

import uuid
from dataclasses import dataclass

from connector.datasets.spec import ApplyAdapter
from connector.domain.ports.execution import RequestSpec, ExecutionResult
from connector.domain.error_codes import ErrorCode
from connector.domain.mappers.user_payload import buildUserUpsertPayload
from connector.planModels import PlanItem


@dataclass
class EmployeesApplyAdapter(ApplyAdapter):
    """
    Назначение:
        Преобразует плановые элементы сотрудников в HTTP-запросы Ankey API.
    """

    def to_request(self, item: PlanItem) -> RequestSpec:
        payload = buildUserUpsertPayload(item.desired_state)
        return RequestSpec.put(
            path=f"/ankey/managed/user/{item.resource_id}",
            payload=payload,
            query={"_prettyPrint": "true", "decrypt": "false"},
        )

    def on_failed_request(self, item: PlanItem, result: ExecutionResult, retries_left: int) -> PlanItem | None:
        """
        Назначение:
            Обработка конфликта resourceExists для create: сгенерировать новый resource_id.
        """
        if retries_left <= 0:
            return None
        if result.error_code == ErrorCode.CONFLICT:
            return PlanItem(
                row_id=item.row_id,
                line_no=item.line_no,
                entity_type=item.entity_type,
                op=item.op,
                resource_id=str(uuid.uuid4()),
                desired_state=item.desired_state,
                changes=item.changes,
                source_ref=item.source_ref,
            )
        return None
