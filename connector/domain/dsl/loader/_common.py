"""
Назначение:
    Общие утилиты для загрузки DSL-спецификаций.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

import yaml

from connector.domain.dsl.issues import DslLoadError

TSpec = TypeVar("TSpec")


def _read_yaml(path: str | Path) -> dict[str, Any]:
    """
    Назначение:
        Прочитать YAML-файл и вернуть dict.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("DSL YAML must be a mapping")
    return data


def _repo_root() -> Path:
    """
    Назначение:
        Разрешить корень репозитория.

    Контракт:
        - Автоматически находит ближайший parent с datasets/registry.yml.
        - Fallback на исторический parents[4] для совместимости.
    """
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "datasets" / "registry.yml").exists():
            return parent
    return current.parents[4]


def _load_registry_or_raise() -> dict[str, Any]:
    """
    Назначение:
        Загрузить datasets/registry.yml с error handling.
    """
    registry_path = _repo_root() / "datasets" / "registry.yml"
    try:
        return _read_yaml(registry_path)
    except Exception as exc:
        raise DslLoadError(
            code="DSL_REGISTRY_INVALID",
            message=f"Failed to read registry.yml: {exc}",
            details={"path": str(registry_path)},
        ) from exc


def _resolve_dataset_path(registry: dict[str, Any], dataset: str, stage: str) -> Path:
    """
    Назначение:
        Разрешить путь к stage-файлу датасета из registry.
    """
    datasets = registry.get("datasets") or {}
    if dataset not in datasets:
        raise DslLoadError(
            code="DSL_REGISTRY_INVALID",
            message=f"Dataset '{dataset}' not found in registry.yml",
            details={"dataset": dataset, "stage": stage},
        )
    entry = datasets[dataset] or {}
    filename = entry.get(stage)
    if not filename:
        raise DslLoadError(
            code="DSL_REGISTRY_INVALID",
            message=f"Dataset '{dataset}' does not define '{stage}' in registry.yml",
            details={"dataset": dataset, "stage": stage},
        )
    return _repo_root() / "datasets" / filename


def _read_yaml_or_raise(
    path: str | Path,
    *,
    code: str,
    dataset: str | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    """
    Назначение:
        Прочитать YAML с обработкой ошибок.
    """
    try:
        return _read_yaml(path)
    except Exception as exc:
        details: dict[str, Any] = {"path": str(path)}
        if dataset is not None:
            details["dataset"] = dataset
        if stage is not None:
            details["stage"] = stage
        raise DslLoadError(
            code=code,
            message=f"Failed to read DSL file: {exc}",
            details=details,
        ) from exc


def _validate_spec_or_raise(
    raw: dict[str, Any],
    spec_cls: type[TSpec],
    *,
    code: str,
    details: dict[str, Any] | None = None,
) -> TSpec:
    """
    Назначение:
        Валидировать Pydantic-модель с обработкой ошибок.
    """
    try:
        return spec_cls.model_validate(raw)
    except Exception as exc:
        raise DslLoadError(
            code=code,
            message=f"Invalid DSL spec: {exc}",
            details=details or {},
        ) from exc


def _load_spec_from_path(path: str | Path, spec_cls: type[TSpec], *, code: str) -> TSpec:
    """
    Назначение:
        Загрузить spec из произвольного пути.
    """
    path_obj = Path(path)
    raw = _read_yaml_or_raise(path_obj, code=code)
    return _validate_spec_or_raise(raw, spec_cls, code=code, details={"path": str(path_obj)})


def _load_dataset_stage_spec(
    *,
    dataset: str,
    stage: str,
    spec_cls: type[TSpec],
    code: str,
    post_load=None,
) -> TSpec:
    """
    Назначение:
        Загрузить spec для датасета/стадии из registry.
    """
    registry = _load_registry_or_raise()
    stage_path = _resolve_dataset_path(registry, dataset, stage)
    raw = _read_yaml_or_raise(stage_path, code=code, dataset=dataset, stage=stage)
    if post_load is not None:
        try:
            raw = post_load(raw)
        except DslLoadError:
            raise
        except Exception as exc:
            raise DslLoadError(
                code=code,
                message=f"Failed to preprocess DSL stage '{stage}': {exc}",
                details={"dataset": dataset, "stage": stage, "path": str(stage_path)},
            ) from exc
    return _validate_spec_or_raise(
        raw,
        spec_cls,
        code=code,
        details={"dataset": dataset, "stage": stage, "path": str(stage_path)},
    )
