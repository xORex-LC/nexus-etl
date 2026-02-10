"""
Назначение:
    Формирование status-модели cache из уже собранных runtime фактов.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CacheDatasetSnapshot:
    dataset: str
    counts: Mapping[str, int]
    meta: Mapping[str, str | None]


class CacheStatusEvaluator:
    """
    Чистый evaluator, не зависящий от конкретного хранилища.
    """

    def evaluate(
        self,
        *,
        schema_version: str | None,
        global_meta: Mapping[str, str | None],
        snapshots: Sequence[CacheDatasetSnapshot],
        dataset: str | None = None,
    ) -> dict:
        if dataset is not None:
            snapshot = _find_snapshot(snapshots, dataset)
            return {
                "dataset": dataset,
                "schema_version": schema_version,
                "counts": dict(snapshot.counts),
                "meta": dict(snapshot.meta),
            }

        by_dataset: dict[str, dict] = {}
        total = 0
        for snapshot in snapshots:
            dataset_total = sum(int(value) for value in snapshot.counts.values())
            total += dataset_total
            by_dataset[snapshot.dataset] = {
                "count": dataset_total,
                "counts": dict(snapshot.counts),
                "meta": dict(snapshot.meta),
            }
        return {
            "schema_version": schema_version,
            "meta": dict(global_meta),
            "by_dataset": by_dataset,
            "total": total,
        }


def _find_snapshot(
    snapshots: Sequence[CacheDatasetSnapshot],
    dataset: str,
) -> CacheDatasetSnapshot:
    for snapshot in snapshots:
        if snapshot.dataset == dataset:
            return snapshot
    raise ValueError(f"Unsupported cache dataset: {dataset}")
