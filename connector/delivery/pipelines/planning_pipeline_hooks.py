"""
Назначение:
    Delivery-level wiring lifecycle hooks для planning/resolve pipeline.

Граница ответственности:
    - Owns: сборку PipelineHooks с callback-ами housekeeping/observability.
    - Does NOT: выполнять resolve/match логику или репортинг use-case.
"""

from __future__ import annotations

from connector.domain.transform.matcher.ports import IMatchScopeService
from connector.domain.transform.resolver.ports import IPendingExpiryService
from connector.domain.transform.stages.stages import PipelineHooks


class PlanningPipelineHooks:
    """
    Назначение:
        Фабрика hook-наборов для planning/resolve pipeline.

    Граница ответственности:
        - plan_hooks(): возвращает PipelineHooks для match+resolve прохода;
          на on_stage_complete("match") вызывает match_scope.clear_scope(),
          на on_stage_complete("resolve") вызывает pending_expiry.sweep().
        - Не занимается drain/report expired pending — это зона ResolveUseCase.
    """

    def __init__(
        self,
        pending_expiry: IPendingExpiryService,
        match_scope: IMatchScopeService,
    ) -> None:
        self._pending_expiry = pending_expiry
        self._match_scope = match_scope

    def plan_hooks(self) -> PipelineHooks:
        def _on_stage_complete(stage_name: str, _duration_ms: float, _stats: dict | None) -> None:
            if stage_name == "match":
                self._match_scope.clear_scope()
            elif stage_name == "resolve":
                self._pending_expiry.sweep()

        return PipelineHooks(on_stage_complete=_on_stage_complete)


__all__ = ["PlanningPipelineHooks"]
