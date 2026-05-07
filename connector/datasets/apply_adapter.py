"""
Назначение:
    Универсальная реализация `ApplyAdapterProtocol` для operation-alias режима.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from connector.domain.diagnostics.exceptions import MissingRequiredSecretError
from connector.domain.planning.plan_models import PlanItem
from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.domain.ports.target.apply import ApplyAdapterProtocol
from connector.domain.ports.target.execution import RequestSpec
from connector.domain.secrets.errors import (
    SecretDecryptionError,
    SecretIntegrityError,
    SecretNotFoundError,
    SecretReadError,
)

PayloadBuilder = Callable[[dict[str, Any]], dict[str, Any]]
ParamsBuilder = Callable[[PlanItem], dict[str, Any] | None]


@dataclass
class OperationApplyAdapter(ApplyAdapterProtocol):
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
        """Purpose:
            Дополнить payload обязательными секретами только для `item.secret_fields`.

        Contract:
            - если поле уже заполнено в `desired_state`, повторный read не выполняется;
            - lookup miss или `SecretNotFoundError` маппится в `SECRET_REQUIRED`;
            - read/decrypt/integrity сбои маппятся в соответствующие `SECRET_*` коды.
        """
        payload_source = dict(item.desired_state)
        for secret_field in item.secret_fields:
            if payload_source.get(secret_field):
                continue
            try:
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
            except SecretNotFoundError as exc:
                raise MissingRequiredSecretError(
                    dataset=self.dataset,
                    field=secret_field,
                    row_id=item.row_id,
                    line_no=item.line_no,
                    target_id=item.target_id,
                    diag_code="SECRET_REQUIRED",
                ) from exc
            except SecretReadError as exc:
                raise MissingRequiredSecretError(
                    dataset=self.dataset,
                    field=secret_field,
                    row_id=item.row_id,
                    line_no=item.line_no,
                    target_id=item.target_id,
                    diag_code="SECRET_READ_ERROR",
                ) from exc
            except SecretDecryptionError as exc:
                raise MissingRequiredSecretError(
                    dataset=self.dataset,
                    field=secret_field,
                    row_id=item.row_id,
                    line_no=item.line_no,
                    target_id=item.target_id,
                    diag_code="SECRET_DECRYPTION_ERROR",
                ) from exc
            except SecretIntegrityError as exc:
                raise MissingRequiredSecretError(
                    dataset=self.dataset,
                    field=secret_field,
                    row_id=item.row_id,
                    line_no=item.line_no,
                    target_id=item.target_id,
                    diag_code="SECRET_INTEGRITY_ERROR",
                ) from exc
            if not secret:
                raise MissingRequiredSecretError(
                    dataset=self.dataset,
                    field=secret_field,
                    row_id=item.row_id,
                    line_no=item.line_no,
                    target_id=item.target_id,
                    diag_code="SECRET_REQUIRED",
                )
            payload_source[secret_field] = secret
        return payload_source


__all__ = ["OperationApplyAdapter"]
