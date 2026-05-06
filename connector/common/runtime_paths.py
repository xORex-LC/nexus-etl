"""
Назначение:
    Typed runtime resolver для внешних runtime-ресурсов приложения.

Граница ответственности:
    - Owns: обнаружение runtime root и resolution policy для runtime paths.
    - Does NOT: чтение YAML, DSL-валидацию, DI wiring, бизнес-логику.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import sys

_REGISTRY_CANDIDATE_FILENAMES = ("registry.yaml", "registry.yml")


class RuntimeLayoutError(RuntimeError):
    """Runtime layout cannot be resolved."""


@dataclass(frozen=True)
class RuntimePathOverrides:
    runtime_root: str | Path | None = None
    config_root: str | Path | None = None
    datasets_root: str | Path | None = None
    dictionary_specs_root: str | Path | None = None
    dictionary_data_root: str | Path | None = None
    source_data_root: str | Path | None = None
    source_projection_root: str | Path | None = None
    target_projection_root: str | Path | None = None
    cache_root: str | Path | None = None
    logs_root: str | Path | None = None
    reports_root: str | Path | None = None


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    config_root: Path
    datasets_root: Path
    dictionary_specs_root: Path
    dictionary_data_root: Path
    source_data_root: Path
    source_projection_root: Path
    target_projection_root: Path
    cache_root: Path
    logs_root: Path
    reports_root: Path
    default_registry_path: Path

    def resolve_dataset_registry(self, ref: str | Path | None = None) -> Path:
        if ref is None:
            return self.default_registry_path
        return self._resolve_from_root(self.datasets_root, ref)

    def resolve_dataset_stage_ref(self, ref: str | Path) -> Path:
        return self._resolve_from_root(self.datasets_root, ref)

    def resolve_dictionary_spec_ref(self, ref: str | Path) -> Path:
        return self._resolve_from_root(self.dictionary_specs_root, ref)

    def resolve_dictionary_manifest_ref(self, ref: str | Path) -> Path:
        return self._resolve_from_root(self.dictionary_specs_root, ref)

    def resolve_dictionary_data_ref(self, ref: str | Path) -> Path:
        return self._resolve_from_root(self.dictionary_data_root, ref)

    def resolve_source_data_ref(self, ref: str | Path) -> Path:
        return self._resolve_from_root(self.source_data_root, ref)

    def resolve_source_projection_ref(self, ref: str | Path) -> Path:
        return self._resolve_from_root(self.source_projection_root, ref)

    def resolve_target_projection_ref(self, ref: str | Path) -> Path:
        return self._resolve_from_root(self.target_projection_root, ref)

    def resolve_cache_path(self, name: str | Path) -> Path:
        return self._resolve_from_root(self.cache_root, name)

    def resolve_log_file(self, name: str | Path) -> Path:
        return self._resolve_from_root(self.logs_root, name)

    def resolve_report_file(self, name: str | Path) -> Path:
        return self._resolve_from_root(self.reports_root, name)

    def resolve_cache_db_file(self, name: str | Path = "ankey_cache.sqlite3") -> Path:
        return self._resolve_from_root(self.cache_root, name)

    def resolve_vault_db_file(self, name: str | Path = "ankey_vault.sqlite3") -> Path:
        return self._resolve_from_root(self.cache_root, name)

    def resolve_identity_db_file(self, name: str | Path = "identity.sqlite3") -> Path:
        return self._resolve_from_root(self.cache_root, name)

    @staticmethod
    def _resolve_from_root(root: Path, ref: str | Path) -> Path:
        path = Path(ref).expanduser()
        if path.is_absolute():
            return path.resolve()
        return (root / path).resolve()


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
    overrides: RuntimePathOverrides | None = None,
    argv0: str | Path | None = None,
    module_file: str | Path | None = None,
) -> RuntimePaths:
    """
    Назначение:
        Вычислить runtime layout без обращения к config-layer и другим слоям.
    """
    applied_overrides = overrides or RuntimePathOverrides()
    argv0_value = sys.argv[0] if argv0 is None else argv0
    module_file_value = __file__ if module_file is None else module_file

    root = _resolve_runtime_root(
        argv0=argv0_value,
        module_file=module_file_value,
        override=applied_overrides.runtime_root,
    )
    config_root = _resolve_path(root, applied_overrides.config_root, "etc")
    datasets_root = _resolve_path(root, applied_overrides.datasets_root, "datasets")
    dictionary_specs_root = _resolve_path(root, applied_overrides.dictionary_specs_root, "etc/dictionaries")
    dictionary_data_root = _resolve_path(root, applied_overrides.dictionary_data_root, "dictionaries")
    source_data_root = _resolve_path(root, applied_overrides.source_data_root, "examples/sources")
    source_projection_root = _resolve_path(root, applied_overrides.source_projection_root, "etc/source-projection")
    target_projection_root = _resolve_path(root, applied_overrides.target_projection_root, "etc/target-projection")
    cache_root = _resolve_path(root, applied_overrides.cache_root, "var/cache")
    logs_root = _resolve_path(root, applied_overrides.logs_root, "var/logs")
    reports_root = _resolve_path(root, applied_overrides.reports_root, "reports")

    return RuntimePaths(
        root=root,
        config_root=config_root,
        datasets_root=datasets_root,
        dictionary_specs_root=dictionary_specs_root,
        dictionary_data_root=dictionary_data_root,
        source_data_root=source_data_root,
        source_projection_root=source_projection_root,
        target_projection_root=target_projection_root,
        cache_root=cache_root,
        logs_root=logs_root,
        reports_root=reports_root,
        default_registry_path=resolve_registry_path_for_datasets_root(datasets_root),
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
    module_file: str | Path,
    override: str | Path | None,
) -> Path:
    if override is not None:
        return _validate_runtime_root(_normalize_path(Path(override)))

    argv_candidate = _path_parent_or_cwd(argv0)
    if _has_runtime_datasets_layout(argv_candidate):
        return argv_candidate

    for parent in Path(module_file).resolve().parents:
        if _has_runtime_datasets_layout(parent):
            return parent

    raise RuntimeLayoutError(
        "Failed to resolve runtime root: no datasets layout found via argv[0] or module parent search"
    )


def _path_parent_or_cwd(argv0: str | Path) -> Path:
    path = Path(argv0).expanduser()
    if path.is_absolute():
        return path.parent.resolve()
    if str(path) in {"", "."}:
        return Path.cwd().resolve()
    return (Path.cwd() / path).resolve().parent


def _resolve_path(runtime_root: Path, override: str | Path | None, default_relative: str) -> Path:
    if override is None:
        return (runtime_root / default_relative).resolve()

    path = Path(override).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (runtime_root / path).resolve()


def _normalize_path(path: Path) -> Path:
    if path.is_absolute():
        return path.resolve()
    return (Path.cwd() / path).resolve()


def _validate_runtime_root(path: Path) -> Path:
    if not _has_runtime_datasets_layout(path):
        raise RuntimeLayoutError(
            f"Invalid runtime root override: datasets registry is missing under '{path}'"
        )
    return path


def _has_runtime_datasets_layout(path: Path) -> bool:
    datasets_root = path / "datasets"
    if not datasets_root.is_dir():
        return False
    registry_path = resolve_registry_path_for_datasets_root(datasets_root)
    return registry_path.exists()


__all__ = [
    "RuntimeLayoutError",
    "RuntimePathOverrides",
    "RuntimePaths",
    "detect_runtime_paths",
    "get_runtime_paths",
    "reset_runtime_paths_cache",
    "resolve_registry_path_for_datasets_root",
]
