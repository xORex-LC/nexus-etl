"""
Назначение:
    Delivery-level wiring lifecycle hooks для planning/resolve pipeline.

Граница ответственности:
    - Owns: сборку ``PipelineHooks`` с callback-ами housekeeping/observability.
    - Does NOT: выполнять resolve/match логику или репортинг use-case.
"""

from __future__ import annotations

from connector.domain.transform.resolver.ports import IPendingExpiryService
from connector.domain.transform.stages.stages import PipelineHooks


class PlanningPipelineHooks:
    """
    Назначение:
        Фабрика hook-наборов для resolve-прохода в planning/resolve сценариях.

    Граница ответственности:
        - resolve_stage_hooks(): возвращает PipelineHooks для micro-batch запуска
          ResolveStage; на ``on_stage_complete`` выполняет pending_expiry.sweep().
        - Не занимается drain/report expired pending — это зона ResolveUseCase.
    """

    def __init__(self, pending_expiry: IPendingExpiryService) -> None:
        self._pending_expiry = pending_expiry

    def resolve_stage_hooks(self) -> PipelineHooks:
        """Purpose:
            Собрать lifecycle hooks для resolve-стадии.

        Contract:
            on_stage_complete триггерит sweep expired pending после полного
            завершения micro-batch resolve-стадии.
        """

        def _on_stage_complete(stage_name: str, _duration_ms: float, _stats: dict | None) -> None:
            if stage_name != "resolve":
                return
            self._pending_expiry.sweep()

        return PipelineHooks(on_stage_complete=_on_stage_complete)


__all__ = ["PlanningPipelineHooks"]
