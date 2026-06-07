"""Plan writer — сериализация import plan в component-aware раскладку.

Модуль пишет итоговый import plan как единый JSON-файл в
`var/plans/<component>/...` по DEC-002 observability layout.

Границы ответственности:
    - Сериализовать payload плана в JSON со стабильной meta/run_id структурой.
    - Давать layout-aware путь для активной observability-модели.
    - Писать файл атомарно через temp + `os.replace`.

Вне ответственности:
    - Сборка plan items/summary из pipeline stream.
    - Выбор active call-site для plan path на текущем этапе.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from connector.common.observability import (
    ComponentIdentity,
    ObservabilityLayout,
    ServiceComponent,
)
from connector.infra.artifacts._atomic_json import atomic_write_json


def write_plan_file_with_layout(
    plan_items: list[dict[str, Any]],
    summary: dict[str, Any],
    meta: dict[str, Any],
    layout: ObservabilityLayout,
    component: ServiceComponent | ComponentIdentity,
    run_id: str,
    generated_at: str,
    *,
    now: datetime | None = None,
) -> str:
    """Записать plan-файл в новую component-aware observability раскладку."""
    plan_path = layout.plan_file(component, now=now)
    data = _build_plan_payload(
        plan_items=plan_items,
        summary=summary,
        meta=meta,
        run_id=run_id,
        generated_at=generated_at,
    )
    atomic_write_json(path=plan_path, payload=data)
    return str(plan_path)


def _build_plan_payload(
    *,
    plan_items: list[dict[str, Any]],
    summary: dict[str, Any],
    meta: dict[str, Any],
    run_id: str,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "meta": {
            "run_id": run_id,
            "generated_at": generated_at,
            **meta,
        },
        "summary": summary,
        "items": plan_items,
    }


__all__ = ["write_plan_file_with_layout"]
