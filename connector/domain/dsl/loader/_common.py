"""
Назначение:
    Общие утилиты для загрузки DSL-спецификаций.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar

import yaml

from connector.domain.dsl.issues import DslLoadError

TSpec = TypeVar("TSpec")
_registry_path_override: Path | None = None


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


@lru_cache(maxsize=1)
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


def _configure_registry_path(path: str | Path | None) -> None:
    """
    Назначение:
        Настроить runtime registry-файл для всех DSL loaders.

    Контракт:
        - None сбрасывает настройку к историческому datasets/registry.yml;
        - относительный путь интерпретируется относительно текущего working directory;
        - смена пути сбрасывает кеш загруженного registry.
    """
    global _registry_path_override
    _registry_path_override = None if path is None else Path(path).expanduser().resolve()
    _load_registry_or_raise.cache_clear()


def _registry_path() -> Path:
    """
    Назначение:
        Вернуть активный registry-файл.
    """
    if _registry_path_override is not None:
        return _registry_path_override
    return _repo_root() / "datasets" / "registry.yml"


def _datasets_root() -> Path:
    """
    Назначение:
        Вернуть директорию, относительно которой registry ссылается на YAML-спеки.
    """
    return _registry_path().parent


@lru_cache(maxsize=1)
def _load_registry_or_raise() -> dict[str, Any]:
    """
    Назначение:
        Загрузить активный registry YAML с error handling.
    """
    registry_path = _registry_path()
    try:
        return _read_yaml(registry_path)
    except Exception as exc:
        raise DslLoadError(
            code="DSL_REGISTRY_INVALID",
            message=f"Failed to read registry file: {exc}",
            details={"path": str(registry_path)},
        ) from exc


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

