"""
Назначение:
    Сборочная инфраструктура transform-стадий для CLI delivery layer.

Граница ответственности:
    - Конфигурация стадий и чекпоинтов (StageName, CheckpointName, PIPELINE_CHECKPOINTS).
    - Сборка PipelineOrchestrator из DI-провайдеров (PipelineComposer).
    - Регистрация и фабрики stage descriptors (build_stage_factory).

Отличие от delivery/pipelines/:
    delivery/pipelines/ содержит конкретные сценарные pipeline-объекты (PlanningPipeline).
    delivery/cli/stages/ содержит generic machinery для сборки любого пайплайна из стадий.
"""

from connector.delivery.cli.stages.config import (
    CheckpointName,
    PIPELINE_CHECKPOINTS,
    StageName,
)
from connector.delivery.cli.stages.composer import PipelineComposer
from connector.delivery.cli.stages.registry import build_stage_factory

__all__ = [
    "CheckpointName",
    "PIPELINE_CHECKPOINTS",
    "PipelineComposer",
    "StageName",
    "build_stage_factory",
]
