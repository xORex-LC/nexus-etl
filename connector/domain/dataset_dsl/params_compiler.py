"""
Назначение:
    Generic operation params builders для apply adapter.

Граница ответственности:
    - Owns: извлечение и валидация параметров операции из PlanItem.
    - Does NOT: секреты, payload, transport.
"""

from __future__ import annotations

from typing import Any, Callable

from connector.domain.dataset_dsl.specs import ParamsSpec
from connector.domain.planning.plan_models import PlanItem

ParamsBuilder = Callable[[PlanItem], dict[str, Any] | None]


def build_target_id_params(item: PlanItem) -> dict[str, Any]:
    """
    Назначение:
        Извлечь и валидировать target_id из PlanItem.
    """
    target_id = item.target_id
    if target_id is None:
        raise ValueError("target_id is required for operation params")
    normalized = str(target_id).strip()
    if normalized == "":
        raise ValueError("target_id is required for operation params")
    return {"target_id": normalized}


def resolve_params_builder(spec: ParamsSpec) -> ParamsBuilder | None:
    """
    Назначение:
        Dispatch params builder по режиму из конфигурации.
    """
    if spec.mode == "target_id":
        return build_target_id_params
    if spec.mode == "none":
        return None
    raise ValueError(f"Unknown params mode: {spec.mode!r}")
