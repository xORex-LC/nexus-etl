"""
Назначение:
    PipelineRunContext — per-run dataclass, агрегирующий синглтоны,
    которые имеют состояние в рамках одного прогона пайплайна.

    Передаётся в DI-контейнер как Singleton (один экземпляр per CLI invocation).
    MatchStage и ResolveStage получают свои зависимости напрямую из DI —
    не через PipelineRunContext.

Инварианты:
    - Не передаётся в MatchCore, ResolveCore или PlanningPipeline напрямую.
    - PlanningPipeline получает только dedup_store (нужен для reset()).
    - ResolveStage получает только batch_index (нужен для get()).
"""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.transform.matcher.ports import ISourceDedupStore
from connector.domain.transform.resolver.ports import IBatchIndexService


@dataclass
class PipelineRunContext:
    """
    Назначение:
        Контейнер per-run singleton-сервисов пайплайна.

    Атрибуты:
        dedup_store  — используется MatchCore для source-dedup;
                       reset() вызывается PlanningPipeline перед прогоном.
        batch_index  — используется ResolveStage для batch-lookup;
                       set_index() вызывается ResolveContextStage.
    """

    dedup_store: ISourceDedupStore
    batch_index: IBatchIndexService


__all__ = ["PipelineRunContext"]
