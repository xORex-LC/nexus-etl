from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .sanitize import maskSecret
from .timeUtils import getNowIso

def _mask_sensitive_item(item: dict[str, Any]) -> dict[str, Any]:
    """
    Назначение:
        Маскирует чувствительные поля плана перед записью в файл/отчёт.
    """
    clone = json.loads(json.dumps(item))
    desired = clone.get("desired_state")
    if isinstance(desired, dict) and "password" in desired:
        desired["password"] = maskSecret(desired["password"])
    return clone


def write_plan_file(
    plan_items: list[dict[str, Any]],
    summary: dict[str, Any],
    meta: dict[str, Any],
    report_dir: str,
    run_id: str,
) -> str:
    """
    Назначение:
        Записывает plan_import_*.json с маскированными секретами.

    Контракт:
        plan_items: операции плана.
        summary: агрегаты по плану.
        meta: метаданные (run_id, dataset, csv_path и т.д.).
        report_dir: каталог вывода.
        run_id: идентификатор запуска.
    Выход:
        Путь к записанному файлу.
    """
    plan_dir = Path(report_dir)
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plan_dir / f"plan_import_{run_id}.json"
    masked_items = [_mask_sensitive_item(item) for item in plan_items]
    data = {
        "meta": {
            "run_id": run_id,
            "generated_at": getNowIso(),
            **meta,
        },
        "summary": summary,
        "items": masked_items,
    }
    plan_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(plan_path)
