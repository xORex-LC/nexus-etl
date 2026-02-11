from __future__ import annotations

from contextlib import contextmanager

from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.infra.cache.backends.sqlite.db import openCacheDb
from connector.infra.cache.backends.sqlite.engine import SqliteEngine
from connector.infra.cache.cache_gateway import SqliteCacheGateway
from connector.infra.cache.roles import build_sqlite_cache_role_ports
from connector.usecases.resolve_usecase import ResolveUseCase


class _TxRuntime:
    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0
        self.active = False

    @contextmanager
    def transaction(self):
        self.entered += 1
        self.active = True
        try:
            yield
        finally:
            self.active = False
            self.exited += 1


class _Resolver:
    def __init__(self, cache_gateway) -> None:
        self.cache_gateway = cache_gateway


class _ResolveStage:
    def __init__(self, cache_gateway) -> None:
        self.resolver = _Resolver(cache_gateway)
        self.batch_sizes: list[int] = []

    def run(self, source, *, dataset=None):
        _ = dataset
        batch = list(source)
        runtime = self.resolver.cache_gateway
        if runtime is not None:
            assert runtime.active is True
        self.batch_sizes.append(len(batch))
        for item in batch:
            yield item


class _PersistingResolveStage:
    def __init__(self, cache_gateway) -> None:
        self.resolver = _Resolver(cache_gateway)
        self._counter = 0

    def run(self, source, *, dataset=None):
        dataset_name = dataset or "employees"
        for item in source:
            self._counter += 1
            idx = self._counter
            self.resolver.cache_gateway.add_pending(
                dataset=dataset_name,
                source_row_id=f"line:{idx}",
                field="manager_id",
                lookup_key=f"mk:{idx}",
                expires_at=None,
                payload="{}",
            )
            yield item


def _result(idx: int) -> TransformResult:
    return TransformResult(
        record=SourceRecord(line_no=idx, record_id=f"line:{idx}", values={}),
        row={"id": idx},
        row_ref=None,
        match_key=None,
        meta={},
        secret_candidates={},
        errors=(),
        warnings=(),
    )


def test_iter_resolved_uses_transaction_per_batch():
    usecase = ResolveUseCase(
        report_items_limit=100,
        include_resolved_items=False,
        batch_size=2,
        flush_interval_ms=0,
    )
    runtime = _TxRuntime()
    stage = _ResolveStage(runtime)
    source = [_result(1), _result(2), _result(3)]

    resolved = list(usecase.iter_resolved(source, stage, dataset="employees"))

    assert resolved == source
    assert stage.batch_sizes == [2, 1]
    # One extra enter/exit is expected for terminal StopIteration check.
    assert runtime.entered == 3
    assert runtime.exited == 3


def test_iter_resolved_without_runtime_transaction():
    usecase = ResolveUseCase(
        report_items_limit=100,
        include_resolved_items=False,
        batch_size=2,
        flush_interval_ms=0,
    )
    stage = _ResolveStage(cache_gateway=None)
    source = [_result(1), _result(2), _result(3)]

    resolved = list(usecase.iter_resolved(source, stage, dataset="employees"))

    assert resolved == source
    assert stage.batch_sizes == [2, 1]


def test_iter_resolved_persists_pending_links_per_batch(tmp_path):
    db_path = tmp_path / "cache.sqlite3"
    conn = openCacheDb(str(db_path))
    engine = SqliteEngine(conn)
    gateway = SqliteCacheGateway.from_engine(engine=engine, cache_specs=[])
    cache_roles = build_sqlite_cache_role_ports(gateway)

    usecase = ResolveUseCase(
        report_items_limit=100,
        include_resolved_items=False,
        batch_size=2,
        flush_interval_ms=0,
    )
    stage = _PersistingResolveStage(cache_roles.planning_runtime)
    source = [_result(1), _result(2), _result(3)]

    _ = list(usecase.iter_resolved(source, stage, dataset="employees"))
    conn.close()

    conn_check = openCacheDb(str(db_path))
    count = conn_check.execute("SELECT COUNT(*) FROM pending_links WHERE dataset = 'employees'").fetchone()[0]
    conn_check.close()

    assert count == 3
