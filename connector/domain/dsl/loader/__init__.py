"""
Назначение:
    DSL loader public API (только generic утилиты).

    Transform-специфичные загрузчики — connector.domain.transform_dsl.
    Cache-специфичные загрузчики — connector.domain.cache_dsl.
"""

from connector.domain.dsl.loader._common import (
    _configure_runtime_paths as configure_runtime_paths,
    _configure_registry_path as configure_registry_path,
    _datasets_root as datasets_root,
    _load_registry_or_raise as load_registry,
    _load_spec_from_path as load_spec_from_path,
    _read_yaml as read_yaml,
    _registry_path as registry_path,
    _repo_root as find_repo_root,
    _validate_spec_or_raise as validate_spec,
)

__all__ = [
    "read_yaml",
    "find_repo_root",
    "registry_path",
    "datasets_root",
    "configure_runtime_paths",
    "configure_registry_path",
    "load_registry",
    "validate_spec",
    "load_spec_from_path",
]
