from __future__ import annotations

import pytest

from connector.domain.cache_dsl.specs import CacheDatasetSpec
from connector.infra.cache.sync.dsl_adapter import build_dsl_cache_sync_adapter


def _build_dataset_spec(*, on_error: str, required: bool = False) -> CacheDatasetSpec:
    return CacheDatasetSpec.model_validate(
        {
            "dataset": "employees",
            "table": "users",
            "schema": {
                "primary_key": "id",
                "columns": [
                    {"name": "id", "type": "string", "required": True},
                    {"name": "email", "type": "string"},
                ],
            },
            "sync": {
                "list_operation_alias": "users.list",
                "report_entity": "users",
                "item_key": {"source": "id"},
                "projection": [
                    {
                        "target": "email",
                        "source": "email",
                        "ops": [{"op": "missing_op"}],
                        "on_error": on_error,
                        "required": required,
                    }
                ],
            },
        }
    )


def test_map_target_to_cache_skips_field_on_skip_policy() -> None:
    dataset_spec = _build_dataset_spec(on_error="skip")
    assert dataset_spec.sync is not None
    adapter = build_dsl_cache_sync_adapter(dataset_spec=dataset_spec, sync_spec=dataset_spec.sync)

    mapped = adapter.map_target_to_cache({"id": "1", "email": "user@example.com"})

    assert mapped == {}


def test_map_target_to_cache_sets_null_on_set_null_policy() -> None:
    dataset_spec = _build_dataset_spec(on_error="set_null")
    assert dataset_spec.sync is not None
    adapter = build_dsl_cache_sync_adapter(dataset_spec=dataset_spec, sync_spec=dataset_spec.sync)

    mapped = adapter.map_target_to_cache({"id": "1", "email": "user@example.com"})

    assert mapped == {"email": None}


def test_map_target_to_cache_sets_null_on_warn_policy() -> None:
    dataset_spec = _build_dataset_spec(on_error="warn")
    assert dataset_spec.sync is not None
    adapter = build_dsl_cache_sync_adapter(dataset_spec=dataset_spec, sync_spec=dataset_spec.sync)

    mapped = adapter.map_target_to_cache({"id": "1", "email": "user@example.com"})

    assert mapped == {"email": None}


def test_map_target_to_cache_raises_on_error_policy() -> None:
    dataset_spec = _build_dataset_spec(on_error="error")
    assert dataset_spec.sync is not None
    adapter = build_dsl_cache_sync_adapter(dataset_spec=dataset_spec, sync_spec=dataset_spec.sync)

    with pytest.raises(ValueError):
        adapter.map_target_to_cache({"id": "1", "email": "user@example.com"})


def test_map_target_to_cache_rejects_skip_for_required_field() -> None:
    dataset_spec = _build_dataset_spec(on_error="skip", required=True)
    assert dataset_spec.sync is not None
    adapter = build_dsl_cache_sync_adapter(dataset_spec=dataset_spec, sync_spec=dataset_spec.sync)

    with pytest.raises(ValueError, match="cannot be skipped"):
        adapter.map_target_to_cache({"id": "1", "email": "user@example.com"})
