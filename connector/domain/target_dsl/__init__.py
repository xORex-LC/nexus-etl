"""
Назначение:
    target-dsl — декларативное описание поведенческой спецификации target-провайдера.

    Позволяет задавать TargetSpec (capabilities, fault_rules, retry_rules, redaction,
    operations) в YAML-файле вместо Python-кода. YAML загружается через runtime registry file,
    валидируется Pydantic и возвращается как неизменяемый TargetSpec.

Использование:
    from connector.domain.target_dsl import load_target_spec

    spec = load_target_spec("ankey")

Что остаётся в Python (не идёт в YAML):
    - auth (httpx.Auth адаптеры)
    - paging strategy (алгоритм пейджинга провайдера)
    - mutations (Python-функции, ссылки на которые хранятся в YAML по имени)
    - provider wiring (сборка TargetRuntime)
"""

from connector.domain.target_dsl.loader import load_target_spec

__all__ = ["load_target_spec"]
