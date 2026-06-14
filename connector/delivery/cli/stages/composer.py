"""Pipeline composer — сборка цепочек стадий из checkpoints и providers.

Модуль является delivery-layer assembly point: он маппит checkpoint name на stage
provider callables и возвращает `PipelineOrchestrator`. Он умеет комбинировать
lifecycle hook sets, но не владеет бизнес-оркестрацией.

Границы ответственности:
    - Собирать `PipelineOrchestrator` instances из stage provider callables.
    - Сохранять lazy provider resolution внутри active command overrides.
    - Подставлять lifecycle hooks по умолчанию, когда команда не передала свои hooks.

Вне ответственности:
    - Загрузка dataset specs или сборка stage execution contexts.
    - Исполнение бизнес-сценариев или reporting stage results.
"""

from __future__ import annotations

from typing import Callable

from connector.domain.transform.stages.stages import (
    AnyStageContract,
    PipelineHooks,
    PipelineOrchestrator,
)


class PipelineComposer:
    """Собирать pipeline orchestrators из checkpoint и stage-provider registries."""

    def __init__(
        self,
        stage_registry: dict[str, Callable[[], AnyStageContract]],
        checkpoints: dict[str, list[str]],
        default_hooks: Callable[[], PipelineHooks | None] | None = None,
    ) -> None:
        self._stages = stage_registry
        self._checkpoints = checkpoints
        self._default_hooks = default_hooks

    def compose(
        self,
        checkpoint: str,
        *,
        hooks: PipelineHooks | None = None,
    ) -> PipelineOrchestrator:
        stage_names = self._checkpoints[checkpoint]
        stages = [self._stages[name]() for name in stage_names]
        return PipelineOrchestrator(stages, hooks=self._combine_hooks(hooks))

    def _combine_hooks(self, hooks: PipelineHooks | None) -> PipelineHooks | None:
        if hooks is not None:
            return hooks
        if self._default_hooks is None:
            return None
        return self._default_hooks()


__all__ = ["PipelineComposer"]
