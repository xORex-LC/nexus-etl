"""
Назначение:
    Загрузка TargetSpec из YAML-файла через datasets/registry.yml.

Алгоритм:
    1. Читает registry.yml, находит путь к YAML по targets.{target_type}.
    2. Читает YAML-файл.
    3. Инжектирует alias в каждую операцию из ключа словаря (чтобы не дублировать в YAML).
    4. Валидирует через TargetSpec.model_validate() — Pydantic коэрцирует list→tuple/frozenset.
    5. Оборачивает ошибки в DslLoadError для согласованной диагностики.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.loader import find_repo_root, load_registry, read_yaml
from connector.infra.target.core.spec_models import TargetSpec


def load_target_spec(target_type: str) -> TargetSpec:
    """
    Назначение:
        Загрузить TargetSpec для указанного провайдера из YAML через registry.

    Аргументы:
        target_type: идентификатор провайдера (ключ в ``registry.yml → targets``).

    Возвращает:
        Валидированный и неизменяемый TargetSpec.

    Raises:
        DslLoadError: если target_type не найден в registry, файл недоступен
                      или YAML не проходит валидацию TargetSpec.
    """
    registry = load_registry()
    spec_path = _resolve_target_path(registry, target_type)
    raw = _read_target_yaml(spec_path, target_type)
    _inject_aliases(raw)
    return _validate_target_spec(raw, target_type, spec_path)


# ---------------------------------------------------------------------------
# Внутренние утилиты
# ---------------------------------------------------------------------------


def _resolve_target_path(registry: dict[str, Any], target_type: str) -> Path:
    """Разрешить путь к YAML-файлу провайдера из registry.yml."""
    targets = registry.get("targets") or {}
    if target_type not in targets:
        raise DslLoadError(
            code="TARGET_DSL_REGISTRY_MISSING",
            message=f"Target provider '{target_type}' not found in registry.yml under 'targets:'",
            details={"target_type": target_type, "available": sorted(targets.keys())},
        )
    relative = targets[target_type]
    if not relative:
        raise DslLoadError(
            code="TARGET_DSL_REGISTRY_INVALID",
            message=f"Target provider '{target_type}' has empty path in registry.yml",
            details={"target_type": target_type},
        )
    return find_repo_root() / "datasets" / relative


def _read_target_yaml(path: Path, target_type: str) -> dict[str, Any]:
    """Прочитать YAML-файл провайдера."""
    try:
        return read_yaml(path)
    except Exception as exc:
        raise DslLoadError(
            code="TARGET_DSL_FILE_ERROR",
            message=f"Failed to read target spec for '{target_type}': {exc}",
            details={"target_type": target_type, "path": str(path)},
        ) from exc


def _inject_aliases(data: dict[str, Any]) -> None:
    """
    Назначение:
        Инжектировать поле ``alias`` в каждую операцию из ключа словаря.

    Пояснение:
        В YAML операции описаны как ``operations: {users.upsert: {...}}``.
        OperationSpec требует поле ``alias``, совпадающее с ключом.
        Чтобы не дублировать alias в YAML, инжектируем его программно.
    """
    operations = data.get("operations")
    if not isinstance(operations, dict):
        return
    for key, op_data in operations.items():
        if isinstance(op_data, dict):
            op_data["alias"] = key


def _validate_target_spec(
    raw: dict[str, Any],
    target_type: str,
    path: Path,
) -> TargetSpec:
    """Валидировать dict как TargetSpec через Pydantic model_validate."""
    try:
        return TargetSpec.model_validate(raw)
    except Exception as exc:
        raise DslLoadError(
            code="TARGET_DSL_SPEC_INVALID",
            message=f"Invalid target spec for '{target_type}': {exc}",
            details={"target_type": target_type, "path": str(path)},
        ) from exc
