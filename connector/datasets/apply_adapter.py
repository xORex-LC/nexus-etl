from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from connector.datasets.spec import ApplyAdapter
from connector.domain.diagnostics.exceptions import MissingRequiredSecretError
from connector.domain.planning.plan_models import PlanItem
from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.domain.ports.target.execution import RequestSpec

PayloadBuilder = Callable[[dict[str, Any]], dict[str, Any]]
ParamsBuilder = Callable[[PlanItem], dict[str, Any] | None]


@dataclass
class OperationApplyAdapter(ApplyAdapter):
    """
    Универсальный адаптер apply для operation-alias режима.

    Назначение:
        - гидрировать секреты из SecretProvider по `item.secret_fields`;
        - собрать payload через переданный payload_builder;
        - собрать параметры операции через params_builder;
        - отдать готовый alias-intent `RequestSpec`.
    """

    operation_alias: str
    payload_builder: PayloadBuilder
    dataset: str
    params_builder: ParamsBuilder | None = None
    secrets: SecretProviderProtocol | None = field(default=None)

    def to_request(self, item: PlanItem) -> RequestSpec:
        payload_source = self._hydrate_payload_source(item)
        payload = self.payload_builder(payload_source)
        params = self.params_builder(item) if self.params_builder else None
        return RequestSpec.operation(
            alias=self.operation_alias,
            params=params,
            payload=payload,
        )

    def _hydrate_payload_source(self, item: PlanItem) -> dict[str, Any]:
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
        return payload_source


__all__ = ["OperationApplyAdapter"]
