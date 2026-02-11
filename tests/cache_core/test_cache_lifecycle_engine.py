from __future__ import annotations

from contextlib import contextmanager

from connector.domain.cache_core import CacheClearPlanner, CacheDependencyGraph, CacheLifecycleEngine
from connector.domain.ports.cache.models import CacheMeta


class _CacheAdminStub:
    def __init__(self) -> None:
        self._datasets = ["organizations", "employees"]
        self._counts = {"organizations": 2, "employees": 3}
        self._cleared: list[str] = []
        self._reset_meta: list[str] = []
        self.tx_entered = 0
        self.tx_exited = 0

    @contextmanager
    def transaction(self):
        self.tx_entered += 1
        try:
            yield
        finally:
            self.tx_exited += 1

    def list_datasets(self) -> list[str]:
        return list(self._datasets)

    def count(self, dataset: str) -> int:
        return int(self._counts.get(dataset, 0))

    def count_by_table(self, dataset: str) -> dict[str, int]:
        return {dataset: int(self._counts.get(dataset, 0))}

    def clear(self, dataset: str) -> None:
        self._cleared.append(dataset)
        self._counts[dataset] = 0

    def reset_meta(self, dataset: str) -> None:
        self._reset_meta.append(dataset)

    def get_meta(self, dataset: str | None = None) -> CacheMeta:
        if dataset is None:
            return CacheMeta(values={"schema_version": "6"})
        return CacheMeta(values={"schema_hash": f"hash:{dataset}"})

    def set_meta(self, dataset: str | None, key: str, value: str | None) -> None:
        _ = (dataset, key, value)

    def upsert(self, dataset: str, write_model: dict):
        raise NotImplementedError

    def rebuild(self, dataset: str) -> None:
        raise NotImplementedError


class _RefreshUseCaseStub:
    def __init__(self) -> None:
        self.called = False

    def refresh(self, **kwargs):
        self.called = True
        return {"total": {"inserted": 1, "updated": 0, "failed": 0, "skipped": 0}, "by_dataset": {}}


def test_cache_lifecycle_engine_status_aggregates_datasets() -> None:
    engine = CacheLifecycleEngine(cache_admin=_CacheAdminStub())
    status = engine.status()

    assert status["schema_version"] == "6"
    assert status["total"] == 5
    assert status["by_dataset"]["employees"]["count"] == 3
    assert status["by_dataset"]["organizations"]["count"] == 2


def test_cache_lifecycle_engine_clear_runs_in_single_transaction() -> None:
    admin = _CacheAdminStub()
    clear_planner = CacheClearPlanner(
        CacheDependencyGraph(
            ("organizations", "employees"),
            dependencies={"employees": ("organizations",)},
        )
    )
    engine = CacheLifecycleEngine(cache_admin=admin, clear_planner=clear_planner)
    deleted = engine.clear(dataset="organizations", cascade=True)

    assert deleted["organizations"] == 2
    assert deleted["employees"] == 3
    assert admin.tx_entered == 1
    assert admin.tx_exited == 1
    assert set(admin._cleared) == {"organizations", "employees"}
    assert set(admin._reset_meta) == {"organizations", "employees"}


def test_cache_lifecycle_engine_refresh_delegates_to_refresh_usecase() -> None:
    admin = _CacheAdminStub()
    refresh_usecase = _RefreshUseCaseStub()
    engine = CacheLifecycleEngine(cache_admin=admin, refresh_usecase=refresh_usecase)
    summary = engine.refresh(
        page_size=100,
        max_pages=1,
        logger=None,
        report=None,
        run_id="run-1",
        catalog=None,
    )

    assert refresh_usecase.called is True
    assert summary["total"]["inserted"] == 1
