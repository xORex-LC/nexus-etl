"""
Назначение:
    Typed factory functions для сборки PipelineOrchestrator из стадий.

    В delivery layer (не domain) сосредоточена типобезопасность сборки pipeline:
    mypy проверяет совместимость I/O типов стадий через параметры функций.
    PipelineOrchestrator получает type-erased список (AnyStageContract).

Граница ответственности:
    - Owns: typed factory functions для фиксированных pipeline-комбинаций.
    - Does NOT: создавать StageExecutionContext, загружать DSL, управлять lifecycle.
    - Does NOT: содержать бизнес-логику — только wiring stage → orchestrator.

Использование:
    Вызывается из command handlers (Этап 4 DEC-004) и тестов delivery layer.
    До Этапа 4 factory functions используются непосредственно в command handlers.
"""

from __future__ import annotations

from connector.domain.transform.stages.stages import (
    AnyStageContract,
    PipelineHooks,
    PipelineOrchestrator,
)


def build_transform_pipeline(
    map_stage: AnyStageContract,
    normalize_stage: AnyStageContract,
    enrich_stage: AnyStageContract,
    *,
    hooks: PipelineHooks | None = None,
) -> PipelineOrchestrator:
    """
    Назначение:
        Собрать pipeline [map → normalize → enrich].

    Используется командами normalize, enrich, mapping (не требуют planning stages).
    """
    return PipelineOrchestrator(
        [map_stage, normalize_stage, enrich_stage],
        hooks=hooks,
    )


def build_full_pipeline(
    map_stage: AnyStageContract,
    normalize_stage: AnyStageContract,
    enrich_stage: AnyStageContract,
    match_stage: AnyStageContract,
    resolve_stage: AnyStageContract,
    *,
    hooks: PipelineHooks | None = None,
) -> PipelineOrchestrator:
    """
    Назначение:
        Собрать полный pipeline [map → normalize → enrich → match → resolve].

    Используется командами import_plan и resolve.
    """
    return PipelineOrchestrator(
        [map_stage, normalize_stage, enrich_stage, match_stage, resolve_stage],
        hooks=hooks,
    )
