"""
Назначение:
    Загрузчик dataset-level DSL конфигурации из registry.yml.

Граница ответственности:
    - Owns: чтение и валидация секций report/apply/diagnostics из registry.yml.
    - Does NOT: компиляция в runtime-объекты (payload builder, catalog).
"""

from __future__ import annotations

from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.loader import load_registry, validate_spec
from connector.domain.dataset_dsl.specs import DatasetDslSpec


def load_dataset_dsl_spec(dataset: str) -> DatasetDslSpec:
    """
    Назначение:
        Загрузить dataset-level DSL (report, apply, diagnostics) из registry.yml.

    Raises:
        DslLoadError: если датасет не найден или конфигурация невалидна.
    """
    registry = load_registry()
    datasets = registry.get("datasets") or {}
    if dataset not in datasets:
        raise DslLoadError(
            code="DSL_DATASET_NOT_FOUND",
            message=f"Dataset '{dataset}' not found in registry.yml",
            details={"dataset": dataset},
        )
    entry = datasets[dataset]
    raw = {
        "report": entry.get("report"),
        "apply": entry.get("apply"),
        "diagnostics": entry.get("diagnostics", []),
    }
    if raw["report"] is None:
        raise DslLoadError(
            code="DSL_DATASET_MISSING_REPORT",
            message=f"Dataset '{dataset}' is missing 'report:' section in registry.yml",
            details={"dataset": dataset},
        )
    if raw["apply"] is None:
        raise DslLoadError(
            code="DSL_DATASET_MISSING_APPLY",
            message=f"Dataset '{dataset}' is missing 'apply:' section in registry.yml",
            details={"dataset": dataset},
        )
    return validate_spec(
        raw,
        DatasetDslSpec,
        code="DSL_DATASET_SPEC_INVALID",
        details={"dataset": dataset},
    )
