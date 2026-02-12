from __future__ import annotations

from connector.domain.cache_core import CacheDatasetSnapshot, CacheStatusEvaluator


def test_status_evaluator_builds_global_status_payload() -> None:
    evaluator = CacheStatusEvaluator()
    payload = evaluator.evaluate(
        schema_version="6",
        global_meta={"schema_version": "6"},
        snapshots=[
            CacheDatasetSnapshot(dataset="organizations", counts={"organizations": 2}, meta={"rows": "2"}),
            CacheDatasetSnapshot(dataset="employees", counts={"users": 3}, meta={"rows": "3"}),
        ],
        dataset=None,
    )
    assert payload["schema_version"] == "6"
    assert payload["total"] == 5
    assert payload["by_dataset"]["organizations"]["count"] == 2
    assert payload["by_dataset"]["employees"]["count"] == 3


def test_status_evaluator_builds_dataset_payload() -> None:
    evaluator = CacheStatusEvaluator()
    payload = evaluator.evaluate(
        schema_version="6",
        global_meta={"schema_version": "6"},
        snapshots=[CacheDatasetSnapshot(dataset="employees", counts={"users": 4}, meta={"rows": "4"})],
        dataset="employees",
    )
    assert payload == {
        "dataset": "employees",
        "schema_version": "6",
        "counts": {"users": 4},
        "meta": {"rows": "4"},
    }
