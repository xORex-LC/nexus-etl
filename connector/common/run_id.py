"""Run identifiers — генерация и нормализация correlation ids для runtime-команд.

Модуль централизует генерацию per-service `run_id` и сквозного `pipeline_run_id`. Он не хранит
состояние, не знает о CLI или отчётности и не управляет жизненным циклом команд.

Границы ответственности:
    - Генерировать новые идентификаторы запуска.
    - Нормализовать `pipeline_run_id` для монолитного и будущего multi-service режима.

Вне ответственности:
    - Проброс идентификаторов по слоям приложения.
    - Форматирование логов, отчётов и артефактов.
"""

from __future__ import annotations

import uuid


def generate_run_id() -> str:
    """
    Назначение:
        Сгенерировать run_id для запуска пайплайна.
    """
    return str(uuid.uuid4())


def generate_pipeline_run_id() -> str:
    """Сгенерировать pipeline_run_id для сквозной корреляции прогона."""
    return generate_run_id()


def resolve_pipeline_run_id(run_id: str, pipeline_run_id: str | None = None) -> str:
    """Вернуть pipeline_run_id; в монолитном режиме по умолчанию равен run_id."""
    return pipeline_run_id or run_id
