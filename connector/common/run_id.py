from __future__ import annotations

import uuid


def generate_run_id() -> str:
    """
    Назначение:
        Сгенерировать run_id для запуска пайплайна.
    """
    return str(uuid.uuid4())
