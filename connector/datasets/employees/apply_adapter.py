from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from connector.datasets.spec import ApplyAdapter
from connector.domain.ports.execution import RequestSpec, ExecutionResult
from connector.domain.mappers.user_payload import buildUserUpsertPayload
from connector.domain.ports.secrets import SecretProviderProtocol
from connector.domain.exceptions import MissingRequiredSecretError
from connector.planModels import PlanItem


@dataclass
class EmployeesApplyAdapter(ApplyAdapter):
    """
    Назначение:
        Преобразует плановые элементы сотрудников в HTTP-запросы Ankey API.
    """

    secrets: SecretProviderProtocol | None = field(default=None)
    dataset: str = "employees"

    def to_request(self, item: PlanItem) -> RequestSpec:
        payload_source = dict(item.desired_state)
        if item.op == "create":
            password = payload_source.get("password")
            if not password:
                password = self.secrets.get_secret(
                    dataset=self.dataset,
                    field="password",
                    row_id=item.row_id,
                    line_no=item.line_no,
                    source_ref=item.source_ref,
                    resource_id=item.resource_id,
                ) if self.secrets else None
            if not password:
                raise MissingRequiredSecretError(
                    dataset=self.dataset,
                    field="password",
                    row_id=item.row_id,
                    line_no=item.line_no,
                    resource_id=item.resource_id,
                )
            payload_source["password"] = password

        payload = buildUserUpsertPayload(payload_source)
        return RequestSpec.put(
            path=f"/ankey/managed/user/{item.resource_id}",
            query={"_prettyPrint": "true", "decrypt": "false"},
            payload=payload,
        )

    def on_failed_request(self, item: PlanItem, result: ExecutionResult, retries_left: int) -> PlanItem | None:
        """
        Назначение:
            Обработка конфликта resourceExists для create: сгенерировать новый resource_id.
        """
        if retries_left <= 0:
            return None
        if item.op != "create":
            return None
        if result.error_reason == "resourceexists":
            return PlanItem(
                row_id=item.row_id,
                line_no=item.line_no,
                op=item.op,
                resource_id=str(uuid.uuid4()),
                desired_state=item.desired_state,
                changes=item.changes,
                source_ref=item.source_ref,
            )
        return None
