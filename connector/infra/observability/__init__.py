"""Observability infrastructure — retention и будущие runtime adapters

Пакет собирает infra-компоненты observability, которые работают поверх
value-object layout/policy из `common/observability.py`. На текущем этапе здесь
живёт безопасная ретенция логов; последующие этапы добавят остальные runtime
артефактные adapters.
"""

from .retention import ObservabilityRetentionSweeper, RetentionSweepResult

__all__ = ["ObservabilityRetentionSweeper", "RetentionSweepResult"]
