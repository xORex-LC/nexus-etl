from __future__ import annotations

import pytest

from connector.domain.dsl.build_options import CacheDslBuildOptions
from connector.domain.dsl.cache_compiler import compile_cache_runtime
from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.specs import CacheDatasetSpec, CacheRegistrySpec


def _registry_with_employees(*, depends_on: list[str] | None = None) -> CacheRegistrySpec:
    return CacheRegistrySpec.model_validate(
        {
            "version": 1,
            "datasets": {
                "employees": {
                    "cache_spec": "employees.cache.yaml",
                    "depends_on": depends_on or [],
                    "enabled": True,
                }
            },
        }
    )


def _employees_spec(*, with_unknown_projection_target: bool = False) -> CacheDatasetSpec:
    projection_target = "unknown_target" if with_unknown_projection_target else "id"
    return CacheDatasetSpec.model_validate(
        {
            "dataset": "employees",
            "table": "users",
            "schema": {
                "primary_key": "id",
                "columns": [
                    {"name": "id", "type": "string", "required": True},
                    {"name": "name", "type": "string", "required": False},
                ],
            },
            "sync": {
                "list_path": "items",
                "report_entity": "users",
                "item_key": {"source": "id"},
                "projection": [{"target": projection_target, "source": "id"}],
            },
        }
    )


def test_compile_cache_runtime_fails_on_unknown_dependencies_by_default() -> None:
    registry = _registry_with_employees(depends_on=["organizations"])
    dataset_specs = {"employees": _employees_spec()}

    with pytest.raises(DslLoadError, match="unknown dependencies"):
        compile_cache_runtime(registry_spec=registry, dataset_specs=dataset_specs)


def test_compile_cache_runtime_allows_unknown_dependencies_when_option_disabled() -> None:
    registry = _registry_with_employees(depends_on=["organizations"])
    dataset_specs = {"employees": _employees_spec()}

    runtime = compile_cache_runtime(
        registry_spec=registry,
        dataset_specs=dataset_specs,
        options=CacheDslBuildOptions(fail_on_unknown_dependencies=False),
    )

    assert runtime.dependency_graph.refresh_order() == ["employees"]


def test_compile_cache_runtime_fails_on_unknown_projection_target_by_default() -> None:
    registry = _registry_with_employees()
    dataset_specs = {"employees": _employees_spec(with_unknown_projection_target=True)}

    with pytest.raises(DslLoadError, match="unknown target columns"):
        compile_cache_runtime(registry_spec=registry, dataset_specs=dataset_specs)


def test_compile_cache_runtime_allows_unknown_projection_target_when_option_disabled() -> None:
    registry = _registry_with_employees()
    dataset_specs = {"employees": _employees_spec(with_unknown_projection_target=True)}

    runtime = compile_cache_runtime(
        registry_spec=registry,
        dataset_specs=dataset_specs,
        options=CacheDslBuildOptions(fail_on_unknown_projection_targets=False),
    )

    assert runtime.sync_specs["employees"].projection[0].target == "unknown_target"
