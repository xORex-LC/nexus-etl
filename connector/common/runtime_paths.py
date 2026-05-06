"""
Назначение:
    Определение runtime layout и стандартных путей к внешним runtime-ресурсам.

Граница ответственности:
    - Owns: обнаружение runtime root и вычисление стандартных runtime paths.
    - Does NOT: чтение YAML, DSL-валидацию, DI wiring, бизнес-логику.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping
import os
import sys

RUNTIME_ROOT_ENV_VAR = "NEXUS_RUNTIME_ROOT"
_REGISTRY_CANDIDATE_FILENAMES = ("registry.yaml", "registry.yml")


class RuntimeLayoutError(RuntimeError):
    """Runtime layout cannot be resolved."""


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    datasets_root: Path
    default_registry_path: Path
    examples_root: Path
    var_root: Path
    cache_root: Path
    logs_root: Path
    reports_root: Path


def resolve_registry_path_for_datasets_root(datasets_root: str | Path) -> Path:
    """
    Назначение:
        Разрешить канонический registry-файл внутри datasets root.

    Контракт:
        - Предпочитает `registry.yaml`.
        - Поддерживает `registry.yml` как migration fallback.
        - Если ни одного файла нет, возвращает канонический путь `registry.yaml`.
    """
    root = Path(datasets_root).expanduser().resolve()
    for filename in _REGISTRY_CANDIDATE_FILENAMES:
        candidate = root / filename
        if candidate.exists():
            return candidate
    return root / _REGISTRY_CANDIDATE_FILENAMES[0]


def detect_runtime_paths(
    *,
    argv0: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    module_file: str | Path | None = None,
) -> RuntimePaths:
    """
    Назначение:
        Вычислить runtime layout без обращения к другим слоям приложения.
    """
    runtime_env = os.environ if env is None else env
    argv0_value = sys.argv[0] if argv0 is None else argv0
    module_file_value = __file__ if module_file is None else module_file

    root = _resolve_runtime_root(
        argv0=argv0_value,
        env=runtime_env,
        module_file=module_file_value,
    )
    datasets_root = root / "datasets"
    var_root = root / "var"
    return RuntimePaths(
        root=root,
        datasets_root=datasets_root,
        default_registry_path=resolve_registry_path_for_datasets_root(datasets_root),
        examples_root=root / "examples",
        var_root=var_root,
        cache_root=var_root / "cache",
        logs_root=var_root / "logs",
        reports_root=var_root / "reports",
    )


@lru_cache(maxsize=1)
def get_runtime_paths() -> RuntimePaths:
    """Cached runtime layout for the current process."""
    return detect_runtime_paths()


def reset_runtime_paths_cache() -> None:
    """Test/helper hook to invalidate cached runtime layout."""
    get_runtime_paths.cache_clear()


def _resolve_runtime_root(
    *,
    argv0: str | Path,
    env: Mapping[str, str],
    module_file: str | Path,
) -> Path:
    env_root = env.get(RUNTIME_ROOT_ENV_VAR)
    if env_root:
        return _validate_runtime_root(Path(env_root).expanduser().resolve(), source=RUNTIME_ROOT_ENV_VAR)

    argv_candidate = _path_parent_or_cwd(argv0)
    if _has_runtime_datasets_layout(argv_candidate):
        return argv_candidate

    for parent in Path(module_file).resolve().parents:
        if _has_runtime_datasets_layout(parent):
            return parent

    raise RuntimeLayoutError(
        "Failed to resolve runtime root: no datasets layout found via "
        f"{RUNTIME_ROOT_ENV_VAR}, argv[0], or module parent search"
    )


def _path_parent_or_cwd(argv0: str | Path) -> Path:
    path = Path(argv0).expanduser()
    if path.is_absolute():
        return path.parent.resolve()
    if str(path) in {"", "."}:
        return Path.cwd().resolve()
    return (Path.cwd() / path).resolve().parent


def _validate_runtime_root(path: Path, *, source: str) -> Path:
    if not _has_runtime_datasets_layout(path):
        raise RuntimeLayoutError(
            f"Invalid runtime root from {source}: datasets registry is missing under '{path}'"
        )
    return path


def _has_runtime_datasets_layout(path: Path) -> bool:
    datasets_root = path / "datasets"
    if not datasets_root.is_dir():
        return False
    registry_path = resolve_registry_path_for_datasets_root(datasets_root)
    return registry_path.exists()


__all__ = [
    "RUNTIME_ROOT_ENV_VAR",
    "RuntimeLayoutError",
    "RuntimePaths",
    "detect_runtime_paths",
    "get_runtime_paths",
    "reset_runtime_paths_cache",
    "resolve_registry_path_for_datasets_root",
]
