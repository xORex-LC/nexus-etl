from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from connector.datasets.spec import ApplyAdapter
from connector.domain.ports.target.execution import RequestSpec, ExecutionResult
from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.domain.diagnostics.exceptions import MissingRequiredSecretError
from connector.domain.planning.plan_models import PlanItem
from connector.infra.target.providers.ankey_rest.payloads import (
    build_user_upsert_payload,
)


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
        for secret_field in item.secret_fields:
            if payload_source.get(secret_field):
                continue
            secret = (
                self.secrets.get_secret(
                    dataset=self.dataset,
                    field=secret_field,
                    row_id=item.row_id,
                    line_no=item.line_no,
                    source_ref=item.source_ref,
                    target_id=item.target_id,
                )
                if self.secrets
                else None
            )
            if not secret:
                raise MissingRequiredSecretError(
                    dataset=self.dataset,
                    field=secret_field,
                    row_id=item.row_id,
                    line_no=item.line_no,
                    target_id=item.target_id,
                )
            payload_source[secret_field] = secret

        payload = build_user_upsert_payload(payload_source)
        return RequestSpec.operation(
            alias="users.upsert",
            params={"target_id": item.target_id},
            payload=payload,
        )

    def on_failed_request(self, item: PlanItem, result: ExecutionResult, retries_left: int) -> PlanItem | None:
        """
        Назначение:
            Обработка конфликта resourceExists для create: сгенерировать новый target_id.
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
                target_id=str(uuid.uuid4()),
                desired_state=item.desired_state,
                changes=item.changes,
                source_ref=item.source_ref,
                secret_fields=item.secret_fields,
            )
        return None
