from __future__ import annotations

import json
from contextlib import contextmanager

import structlog.testing

from connector.domain.ports.cache.models import PendingRow
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.infra.sqlite.engine import open_sqlite
from connector.infra.sqlite.config import SqliteDbConfig
from connector.infra.cache.cache_gateway import SqliteCacheGateway
from connector.infra.cache.roles import build_sqlite_cache_role_ports
from connector.infra.identity.sqlite.schema import ensure_identity_schema
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
    db_path = str(tmp_path / "cache.sqlite3")
    config = SqliteDbConfig(transaction_mode="deferred")
    engine = open_sqlite(config, db_path)
    ensure_identity_schema(engine)
    gateway = SqliteCacheGateway.from_engine(
        cache_engine=engine,
        identity_engine=engine,
        cache_specs=[],
    )
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
    engine.close()

    engine_check = open_sqlite(config, db_path)
    count = engine_check.fetchone(
        "SELECT COUNT(*) FROM pending_links WHERE dataset = 'employees'"
    )[0]
    engine_check.close()

    assert count == 3


# ─── Helpers for pending_replay tests ────────────────────────────────────────


def _valid_pending_payload(row_id: str = "pending-1", match_key: str = "mk-1") -> str:
    """Build a minimal valid serialized MatchedRow payload."""
    return json.dumps(
        {
            "identity": {"primary": "match_key", "values": {"match_key": match_key}},
            "row_ref": {
                "line_no": 99,
                "row_id": row_id,
                "identity_primary": "match_key",
                "identity_value": match_key,
            },
            "desired_state": {"match_key": match_key},
            "existing": None,
            "fingerprint": "fp-pending",
            "fingerprint_fields": ["match_key"],
            "match_decision": {
                "status": "not_found",
                "reason_code": "identity_not_found",
                "message": None,
                "selected": None,
                "candidates": [],
                "score": None,
                "meta": {},
            },
            "source_links": {},
            "target_id": None,
            "meta": {},
        }
    )


class _PendingReplayRuntime:
    """Stub runtime that returns pre-configured pending rows from list_pending_rows()."""

    def __init__(self, rows: list[PendingRow]) -> None:
        self._rows = rows
        self.list_pending_rows_called = False

    def list_pending_rows(self, dataset: str) -> list[PendingRow]:
        self.list_pending_rows_called = True
        return list(self._rows)

    # ResolveRuntimePort stubs (not exercised in these tests)
    def transaction(self):
        from contextlib import nullcontext
        return nullcontext()

    def find_candidates(self, dataset, identity_key):
        return []

    def add_pending(self, **kwargs):
        return 0

    def mark_resolved_for_source(self, source_row_id):
        pass

    def mark_conflict(self, pending_id, reason=None):
        pass

    def touch_attempt(self, pending_id):
        return 0

    def sweep_expired(self, now, *, reason=None):
        return []

    def purge_stale(self, cutoff, statuses=None):
        return 0


# ─── Zone 2 tests ─────────────────────────────────────────────────────────────


def test_iter_resolved_skips_pending_when_replay_is_none():
    """Backward compat: pending_replay=None (default) → only matched_source items."""
    usecase = ResolveUseCase(
        report_items_limit=100,
        include_resolved_items=False,
        batch_size=10,
        flush_interval_ms=0,
    )
    stage = _ResolveStage(cache_gateway=None)
    source = [_result(1), _result(2)]

    resolved = list(usecase.iter_resolved(source, stage, dataset="employees"))

    assert resolved == source
    assert stage.batch_sizes == [2]


def test_iter_resolved_chains_pending_when_replay_provided():
    """pending_replay with valid pending rows → items appended after matched_source."""
    pending_rows = [
        PendingRow(
            dataset="employees",
            source_row_id="pending-1",
            payload=_valid_pending_payload("pending-1", "mk-p1"),
        ),
        PendingRow(
            dataset="employees",
            source_row_id="pending-2",
            payload=_valid_pending_payload("pending-2", "mk-p2"),
        ),
    ]
    replay = _PendingReplayRuntime(pending_rows)

    usecase = ResolveUseCase(
        report_items_limit=100,
        include_resolved_items=False,
        batch_size=100,
        flush_interval_ms=0,
    )
    stage = _ResolveStage(cache_gateway=None)
    source = [_result(1)]

    resolved = list(
        usecase.iter_resolved(source, stage, dataset="employees", pending_replay=replay)
    )

    # 1 from source + 2 from pending
    assert len(resolved) == 3
    assert replay.list_pending_rows_called is True


def test_iter_resolved_skips_pending_when_dataset_is_none():
    """pending_replay provided but dataset=None → list_pending_rows() NOT called."""
    replay = _PendingReplayRuntime(
        [PendingRow(dataset="e", source_row_id="p-1", payload=_valid_pending_payload())]
    )
    usecase = ResolveUseCase(
        report_items_limit=100,
        include_resolved_items=False,
        batch_size=10,
        flush_interval_ms=0,
    )
    stage = _ResolveStage(cache_gateway=None)

    resolved = list(
        usecase.iter_resolved([], stage, dataset=None, pending_replay=replay)
    )

    assert resolved == []
    assert replay.list_pending_rows_called is False


def test_iter_resolved_warns_on_skipped_pending():
    """load_result.skipped > 0 → structlog warning 'pending_codec_skipped_invalid' emitted."""
    bad_row = PendingRow(dataset="employees", source_row_id="bad", payload="not-json{{{")
    replay = _PendingReplayRuntime([bad_row])

    usecase = ResolveUseCase(
        report_items_limit=100,
        include_resolved_items=False,
        batch_size=10,
        flush_interval_ms=0,
    )
    stage = _ResolveStage(cache_gateway=None)

    with structlog.testing.capture_logs() as cap:
        list(usecase.iter_resolved([], stage, dataset="employees", pending_replay=replay))

    warning_events = [e for e in cap if e.get("event") == "pending_codec_skipped_invalid"]
    assert len(warning_events) == 1
    assert warning_events[0]["count"] == 1
    assert warning_events[0]["dataset"] == "employees"
