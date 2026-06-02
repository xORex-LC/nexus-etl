"""
Назначение:
    Декларативный реестр чекпоинтов пайплайна (TRANSFORM-DEC-007).

    Единственное место истины о составе pipeline для каждого сценария.
    Чекпоинт — кумулятивный: включает все стадии от MAP до указанной включительно.

Граница ответственности:
    - StageName: строковые ключи стадий для stage_registry в PipelineComposer.
    - CheckpointName: строковые ключи чекпоинтов для compose() и PIPELINE_CHECKPOINTS.
    - PIPELINE_CHECKPOINTS: маппинг checkpoint → упорядоченный список stage names.
    - Не содержит логики — только константы и данные.

Добавить стадию = одна строка в нужных чекпоинтах + новый провайдер в PipelineContainer.
"""
from __future__ import annotations


class StageName:
    """
    Строковые ключи стадий — единственное место определения stage_registry ключей.

    Опечатка в stage_registry или compose() ловится при KeyError в runtime,
    а не при импорте. Используй эти константы везде.
    """

    MAP = "map_stage"
    SOURCE_TOPOLOGY_FILTER = "source_topology_filter_stage"
    NORMALIZE = "normalize_stage"
    ENRICH = "enrich_stage"
    MATCH = "match_stage"
    RESOLVE_CONTEXT = "resolve_context_stage"
    RESOLVE = "resolve_stage"


class CheckpointName:
    """
    Строковые ключи чекпоинтов — аргументы PipelineComposer.compose() и ключи PIPELINE_CHECKPOINTS.

    Чекпоинты двух типов:
    - stage-terminal (map / normalize / enrich / match / resolve_context / resolve):
      именованы по последней включаемой стадии.
    - scenario alias (plan): может совпадать по stage-chain с terminal checkpoint,
      но семантически обозначает отдельный сценарий (import_plan).
    """

    MAP = "map"
    NORMALIZE = "normalize"
    ENRICH = "enrich"
    MATCH = "match"
    RESOLVE_CONTEXT = "resolve_context"   # MAP→RESOLVE_CONTEXT без RESOLVE
    RESOLVE = "resolve"
    PLAN = "plan"


# Единственное место истины о составе пайплайнов.
# Каждый чекпоинт — кумулятивный: включает все предыдущие стадии.
#
# CheckpointName.RESOLVE_CONTEXT — промежуточный checkpoint (MAP→RESOLVE_CONTEXT без RESOLVE).
# Используется в resolve.py handler и PlanningPipeline.open() для получения contextualized rows
# перед добавлением pending rows и вызовом ResolveUseCase.
#
# CheckpointName.RESOLVE и CheckpointName.PLAN имеют одинаковый stage-chain.
# Различие семантическое: RESOLVE — stage-terminal, PLAN — scenario alias для import_plan.
PIPELINE_CHECKPOINTS: dict[str, list[str]] = {
    CheckpointName.MAP: [
        StageName.MAP,
    ],
    CheckpointName.NORMALIZE: [
        StageName.MAP,
        StageName.SOURCE_TOPOLOGY_FILTER,
        StageName.NORMALIZE,
    ],
    CheckpointName.ENRICH: [
        StageName.MAP,
        StageName.SOURCE_TOPOLOGY_FILTER,
        StageName.NORMALIZE,
        StageName.ENRICH,
    ],
    CheckpointName.MATCH: [
        StageName.MAP,
        StageName.SOURCE_TOPOLOGY_FILTER,
        StageName.NORMALIZE,
        StageName.ENRICH,
        StageName.MATCH,
    ],
    CheckpointName.RESOLVE_CONTEXT: [
        StageName.MAP,
        StageName.SOURCE_TOPOLOGY_FILTER,
        StageName.NORMALIZE,
        StageName.ENRICH,
        StageName.MATCH,
        StageName.RESOLVE_CONTEXT,
    ],
    CheckpointName.RESOLVE: [
        StageName.MAP,
        StageName.SOURCE_TOPOLOGY_FILTER,
        StageName.NORMALIZE,
        StageName.ENRICH,
        StageName.MATCH,
        StageName.RESOLVE_CONTEXT,
        StageName.RESOLVE,
    ],
    CheckpointName.PLAN: [
        StageName.MAP,
        StageName.SOURCE_TOPOLOGY_FILTER,
        StageName.NORMALIZE,
        StageName.ENRICH,
        StageName.MATCH,
        StageName.RESOLVE_CONTEXT,
        StageName.RESOLVE,
    ],
}


__all__ = [
    "StageName",
    "CheckpointName",
    "PIPELINE_CHECKPOINTS",
]
