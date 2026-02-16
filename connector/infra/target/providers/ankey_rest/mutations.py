"""Мутации запросов для Ankey REST provider."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from connector.domain.ports.target.execution import RequestSpec
from connector.infra.target.core.mutations import TargetMutation


def regenerate_target_id(request_spec: RequestSpec) -> RequestSpec:
    """
    Сгенерировать новый `target_id` для operation-alias запроса.

    Используется в сценарии `resourceexists` при create/upsert.
    """
    if request_spec.operation_alias is None:
        raise ValueError("mutation 'regenerate_target_id' supports only operation_alias requests")

    params = dict(request_spec.operation_params or {})
    params["target_id"] = str(uuid.uuid4())
    return RequestSpec.operation(
        alias=request_spec.operation_alias,
        payload=request_spec.payload,
        headers=request_spec.headers,
        query=request_spec.query,
        params=params,
    )


def build_ankey_mutations() -> Mapping[str, TargetMutation]:
    return {
        "regenerate_target_id": regenerate_target_id,
    }


__all__ = ["build_ankey_mutations", "regenerate_target_id"]
