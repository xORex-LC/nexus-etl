from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_plan_file(
    plan_items: list[dict[str, Any]],
    summary: dict[str, Any],
    meta: dict[str, Any],
    report_dir: str,
    run_id: str,
    generated_at: str,
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
    data = {
        "meta": {
            "run_id": run_id,
            "generated_at": generated_at,
            **meta,
        },
        "summary": summary,
        "items": plan_items,
    }
    plan_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(plan_path)
