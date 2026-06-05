"""Plan writer — сериализация import plan в legacy и layout-aware раскладки

Модуль пишет итоговый import plan как единый JSON-файл. Он сохраняет старый
`write_plan_file(...)` для текущих call-sites и добавляет новый layout-aware
writer под `var/plans/<component>/...` без переключения оркестратора на этом этапе.

Границы ответственности:
    - Сериализовать payload плана в JSON со стабильной meta/run_id структурой.
    - Давать legacy и layout-aware пути как отдельные additive symbols.
    - Писать файл атомарно через temp + `os.replace`.

Вне ответственности:
    - Сборка plan items/summary из pipeline stream.
    - Выбор active call-site для plan path на текущем этапе.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from connector.common.observability import (
    ComponentIdentity,
    ObservabilityLayout,
    ServiceComponent,
)
from connector.infra.artifacts._atomic_json import atomic_write_json


def write_plan_file(
    plan_items: list[dict[str, Any]],
    summary: dict[str, Any],
    meta: dict[str, Any],
    report_dir: str,
    run_id: str,
    generated_at: str,
) -> str:
    """Записать legacy plan-файл в старую раскладку рядом с report_dir."""
    plan_dir = Path(report_dir)
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plan_dir / f"plan_import_{run_id}.json"
    data = _build_plan_payload(
        plan_items=plan_items,
        summary=summary,
        meta=meta,
        run_id=run_id,
        generated_at=generated_at,
    )
    atomic_write_json(path=plan_path, payload=data)
    return str(plan_path)


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


__all__ = ["write_plan_file", "write_plan_file_with_layout"]
