"""
Назначение:
    PipelineComposer — собирает PipelineOrchestrator из реестра чекпоинтов
    и фабрик стадий (TRANSFORM-DEC-007).

    Не знает о бизнес-сценариях — только о том, как создать стадию по имени.
    Единственное место, где checkpoint → stage names → PipelineOrchestrator.

Граница ответственности:
    - Owns: сборка PipelineOrchestrator из stage_registry и checkpoints.
    - Does NOT: знать о DatasetSpec, командах, lifecycle sidecars.
    - Does NOT: материализовать стадии до вызова compose() — provider-ссылки
      разрешаются лениво внутри compose(), уже под активными override()-контекстами.

Использование:
    composer = AppContainer.pipeline_composer()
    pipeline = composer.compose(CheckpointName.ENRICH)
    pipeline = composer.compose(CheckpointName.MATCH, hooks=plan_hooks)

Почему plain dict для stage_registry, не providers.Dict:
    providers.Dict разрешает все значения eager при материализации Singleton-а.
    В stage_registry передаются provider-объекты как callable (не их результаты).
    compose() вызывает self._stages[name]() уже внутри override()-контекста команды,
    получая инстансы стадий с корректно переопределёнными зависимостями.
"""
from __future__ import annotations

from typing import Callable

from connector.domain.transform.stages.stages import (
    AnyStageContract,
    PipelineHooks,
    PipelineOrchestrator,
)


class PipelineComposer:
    """
    Назначение:
        Собирает PipelineOrchestrator из реестра чекпоинтов и фабрик стадий.

    Граница ответственности:
        - stage_registry: plain dict {stage_name: provider_callable}.
          Provider-ссылки передаются как callable, не разрешаются eager.
        - checkpoints: маппинг checkpoint → список stage names (из PIPELINE_CHECKPOINTS).
        - compose() вызывается внутри override()-контекста команды — стадии
          материализуются с актуальными dataset_spec, run_id, catalog и пр.

    Инварианты:
        - compose() при несуществующем checkpoint → KeyError.
        - compose() при несуществующем stage_name в stage_registry → KeyError.
        - Возвращаемый PipelineOrchestrator stateless — можно вызывать run() многократно.
        - hooks=None → PipelineOrchestrator без lifecycle callbacks.
    """

    def __init__(
        self,
        stage_registry: dict[str, Callable[[], AnyStageContract]],
        checkpoints: dict[str, list[str]],
    ) -> None:
        self._stages = stage_registry
        self._checkpoints = checkpoints

    def compose(
        self,
        checkpoint: str,
        *,
        hooks: PipelineHooks | None = None,
    ) -> PipelineOrchestrator:
        """
        Назначение:
            Собрать конвейер для указанного чекпоинта включительно.

        Контракт:
            - Вызывается внутри override()-контекста команды: provider-ссылки
              в stage_registry разрешаются с актуальными dataset_spec, run_id и пр.
            - hooks=None → PipelineOrchestrator без lifecycle callbacks.
            - Порядок стадий строго соответствует PIPELINE_CHECKPOINTS[checkpoint].
        """
        stage_names = self._checkpoints[checkpoint]
        stages = [self._stages[name]() for name in stage_names]
        return PipelineOrchestrator(stages, hooks=hooks)


__all__ = ["PipelineComposer"]
