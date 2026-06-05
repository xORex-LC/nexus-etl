"""Atomic JSON writing — общий helper для runtime observability-артефактов

Модуль инкапсулирует атомарную запись JSON-файлов через временный файл в том же
каталоге и `os.replace()`. Он нужен render/write слоям observability, чтобы
не оставлять усечённые report/plan артефакты при сбоях записи.

Границы ответственности:
    - Записывать JSON payload в temp-файл рядом с целевым.
    - Атомарно подменять финальный файл через `os.replace`.
    - Чистить временный файл при ошибке до replace/после него.

Вне ответственности:
    - Формирование payload для report/plan структур.
    - Выбор final path и layout naming policy.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(
    *,
    path: str | Path,
    payload: Any,
    indent: int = 2,
) -> Path:
    """Записать JSON atomically в целевой путь.

    Args:
        path: Финальный путь артефакта.
        payload: Уже подготовленная сериализуемая структура.
        indent: Pretty-print indentation для JSON.

    Returns:
        Финальный путь после успешного `os.replace`.
    """

    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    temp_handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=target_path.parent,
        prefix=f".{target_path.stem}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(temp_handle.name)
    try:
        with temp_handle:
            json.dump(payload, temp_handle, ensure_ascii=False, indent=indent)
            temp_handle.flush()
            os.fsync(temp_handle.fileno())
        os.replace(temp_path, target_path)
        return target_path
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


__all__ = ["atomic_write_json"]
