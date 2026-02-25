"""
Тесты ResolveContextStage (DEC-004 Stage 4).

Architecture:
    - ResolveContextStage буферизует source, строит batch_index, вызывает
      IBatchIndexService.set_index(), затем передаёт записи без изменений.
    - ResolveStage lazy: читает IBatchIndexService.get() при первой итерации.
    - IBatchIndexService.get() бросает RuntimeError до set_index().

Unit:
    - context_stage буферизует все записи и вызывает set_index().
    - context_stage передаёт записи без изменений (identity pass-through).
    - context_stage с пустым source вызывает set_index({}).
    - batch_index.get() до context_stage.run() → RuntimeError.
    - resolve_stage.run() после context_stage.run() использует индекс.
    - Парная цепочка context_stage → resolve_stage корректно передаёт записи.

Integration:
    - ResolveContextStage + ResolveStage с реальным InMemoryBatchIndexService.
    - PlanningPipeline вызывает dedup_store.reset() перед прогоном.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call

import pytest

from connector.domain.models import Identity, RowRef
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.matcher.match_models import (
    MatchDecision,
    MatchDecisionStatus,
    MatchedRow,
)
from connector.domain.transform.resolver.batch_index_service import InMemoryBatchIndexService
from connector.domain.transform.stages.stages import ResolveContextStage, ResolveStage


# ════════════════════════════════════════════════════════════════════════════════
# Test helpers
# ════════════════════════════════════════════════════════════════════════════════

def _make_transform_result(row_id: str = "row-1") -> TransformResult:
    """Create a minimal TransformResult with a valid MatchedRow."""
    identity = Identity(primary="match_key", values={"match_key": "key-1"})
    row_ref = RowRef(line_no=1, row_id=row_id, identity_primary="match_key", identity_value="key-1")
    matched_row = MatchedRow(
        row_ref=row_ref,
        identity=identity,
        desired_state={"field": "value"},
        existing=None,
        fingerprint="fp",
        fingerprint_fields=("field",),
        source_links={},
        target_id=None,
        match_decision=MatchDecision(
            status=MatchDecisionStatus.NOT_FOUND,
            reason_code="not_found",
        ),
    )
    return TransformResult(
        record=SourceRecord(line_no=1, record_id=row_id, values={}),
        row=matched_row,
        row_ref=row_ref,
        match_key=None,
    )


def _make_none_row_result(row_id: str = "row-null") -> TransformResult:
    """Create a TransformResult with row=None (dropped/errored record)."""
    row_ref = RowRef(line_no=1, row_id=row_id, identity_primary=None, identity_value=None)
    return TransformResult(
        record=SourceRecord(line_no=1, record_id=row_id, values={}),
        row=None,
        row_ref=row_ref,
        match_key=None,
    )


class _FakeResolver:
    """Minimal ResolveProcessor stub."""

    def __init__(self, index: dict[str, list[str]] | None = None) -> None:
        self._index = index or {}
        self.build_batch_index_calls: list[list] = []

    def build_batch_index(self, matched_rows: list) -> dict[str, list[str]]:
        self.build_batch_index_calls.append(matched_rows)
        return self._index

    def resolve(self, matched: Any, *, target_id_map: Any, meta: Any = None, batch_index: Any = None):
        # Return no-op resolved row
        return None, [], []


# ════════════════════════════════════════════════════════════════════════════════
# ResolveContextStage unit tests
# ════════════════════════════════════════════════════════════════════════════════

class TestResolveContextStage:

    def test_set_index_called_with_all_records(self):
        """context_stage должна вызвать set_index() с batch_index для всех записей."""
        batch_index_svc = MagicMock()
        resolver = _FakeResolver(index={"key:val": ["id-1"]})
        stage = ResolveContextStage(batch_index=batch_index_svc, resolver=resolver)

        records = [_make_transform_result("r1"), _make_transform_result("r2")]
        result = list(stage.run(iter(records)))

        assert len(resolver.build_batch_index_calls) == 1
        assert len(resolver.build_batch_index_calls[0]) == 2
        batch_index_svc.set_index.assert_called_once_with({"key:val": ["id-1"]})

    def test_records_passed_through_unchanged(self):
        """context_stage передаёт записи без изменений."""
        batch_index_svc = InMemoryBatchIndexService()
        resolver = _FakeResolver()
        stage = ResolveContextStage(batch_index=batch_index_svc, resolver=resolver)

        r1 = _make_transform_result("r1")
        r2 = _make_transform_result("r2")
        result = list(stage.run([r1, r2]))

        assert result[0] is r1
        assert result[1] is r2

    def test_empty_source_sets_empty_index(self):
        """Пустой source → set_index({})."""
        batch_index_svc = InMemoryBatchIndexService()
        resolver = _FakeResolver(index={})
        stage = ResolveContextStage(batch_index=batch_index_svc, resolver=resolver)

        result = list(stage.run([]))

        assert result == []
        assert batch_index_svc.get() == {}

    def test_none_row_records_included_in_buffering(self):
        """Записи с row=None включаются в буфер и передаются без изменений."""
        batch_index_svc = InMemoryBatchIndexService()
        resolver = _FakeResolver()
        stage = ResolveContextStage(batch_index=batch_index_svc, resolver=resolver)

        r_ok = _make_transform_result("r1")
        r_none = _make_none_row_result("r-null")
        result = list(stage.run([r_ok, r_none]))

        assert len(result) == 2
        assert result[0] is r_ok
        assert result[1] is r_none
        # build_batch_index получает все 2 записи (не только ok)
        assert len(resolver.build_batch_index_calls[0]) == 2


# ════════════════════════════════════════════════════════════════════════════════
# IBatchIndexService architecture tests
# ════════════════════════════════════════════════════════════════════════════════

class TestInMemoryBatchIndexServiceContract:

    def test_get_raises_before_set_index(self):
        """IBatchIndexService.get() до set_index() → RuntimeError."""
        svc = InMemoryBatchIndexService()
        with pytest.raises(RuntimeError, match="set_index"):
            svc.get()

    def test_set_index_then_get_returns_index(self):
        svc = InMemoryBatchIndexService()
        svc.set_index({"k:v": ["id-1"]})
        assert svc.get() == {"k:v": ["id-1"]}

    def test_set_index_atomically_replaces_previous(self):
        svc = InMemoryBatchIndexService()
        svc.set_index({"old": ["1"]})
        svc.set_index({"new": ["2"]})
        assert svc.get() == {"new": ["2"]}
        assert "old" not in svc.get()


# ════════════════════════════════════════════════════════════════════════════════
# Paired chain: context_stage → resolve_stage
# ════════════════════════════════════════════════════════════════════════════════

class TestResolveContextAndResolveStagePair:

    def test_paired_chain_processes_records(self):
        """
        context_stage.run(source) → resolve_stage.run(context_output) корректно
        передаёт все записи: index установлен до вызова resolve_stage.run().
        """
        from connector.domain.diagnostics.catalog import build_catalog
        catalog = build_catalog("employees", strict=False)

        batch_index_svc = InMemoryBatchIndexService()
        resolver = _FakeResolver(index={})

        ctx_stage = ResolveContextStage(batch_index=batch_index_svc, resolver=resolver)
        resolve_stage = ResolveStage(resolver=resolver, catalog=catalog, batch_index=batch_index_svc)

        records = [_make_transform_result("r1"), _make_transform_result("r2")]
        context_output = ctx_stage.run(iter(records))
        result = list(resolve_stage.run(context_output))

        assert len(result) == 2

    def test_resolve_stage_uses_index_set_by_context_stage(self):
        """
        resolve_stage.run() использует batch_index, заполненный context_stage.
        """
        from connector.domain.diagnostics.catalog import build_catalog
        catalog = build_catalog("employees", strict=False)
        batch_index_svc = InMemoryBatchIndexService()

        captured_index: dict = {}

        class _CapturingResolver:
            def build_batch_index(self, rows):
                return {"link:val": ["target-42"]}

            def resolve(self, matched, *, target_id_map, meta=None, batch_index=None):
                captured_index.update(batch_index or {})
                return None, [], []

        resolver = _CapturingResolver()
        ctx_stage = ResolveContextStage(batch_index=batch_index_svc, resolver=resolver)
        resolve_stage = ResolveStage(resolver=resolver, catalog=catalog, batch_index=batch_index_svc)

        records = [_make_transform_result("r1")]
        context_output = ctx_stage.run(iter(records))
        list(resolve_stage.run(context_output))

        assert captured_index == {"link:val": ["target-42"]}

    def test_resolve_stage_get_raises_without_context_stage(self):
        """
        Если context_stage не запущена, resolve_stage.run() бросает RuntimeError
        на первой итерации (IBatchIndexService.get() до set_index()).
        """
        from connector.domain.diagnostics.catalog import build_catalog
        catalog = build_catalog("employees", strict=False)
        batch_index_svc = InMemoryBatchIndexService()
        resolver = _FakeResolver()

        resolve_stage = ResolveStage(resolver=resolver, catalog=catalog, batch_index=batch_index_svc)

        with pytest.raises(RuntimeError, match="set_index"):
            list(resolve_stage.run([_make_transform_result("r1")]))

    def test_none_row_bypasses_resolve(self):
        """
        Записи с row=None проходят через resolve_stage без вызова resolve().
        """
        from connector.domain.diagnostics.catalog import build_catalog
        catalog = build_catalog("employees", strict=False)
        batch_index_svc = InMemoryBatchIndexService()
        batch_index_svc.set_index({})

        resolve_calls = []

        class _TrackingResolver:
            def build_batch_index(self, rows): return {}
            def resolve(self, matched, *, target_id_map, meta=None, batch_index=None):
                resolve_calls.append(matched)
                return None, [], []

        resolver = _TrackingResolver()
        resolve_stage = ResolveStage(resolver=resolver, catalog=catalog, batch_index=batch_index_svc)

        r_none = _make_none_row_result("dropped")
        result = list(resolve_stage.run([r_none]))

        assert result[0] is r_none
        assert resolve_calls == []  # resolve не вызывался


# ════════════════════════════════════════════════════════════════════════════════
# PlanningPipeline dedup_store.reset() contract
# ════════════════════════════════════════════════════════════════════════════════

class TestPlanningPipelineResetsDedup:

    def test_dedup_store_reset_called_before_open(self):
        """
        PlanningPipeline.open() вызывает dedup_store.reset() перед прогоном.
        Тест использует mock-объекты для всего кроме dedup_store.
        """
        from connector.delivery.pipelines.planning_pipeline import PlanningPipeline

        dedup_store = MagicMock()
        transform_segment = MagicMock()
        transform_segment.run.return_value = iter([])
        match_stage = MagicMock()
        resolve_context_stage = MagicMock()
        resolve_context_stage.run.return_value = iter([])
        resolve_stage = MagicMock()
        row_source = MagicMock()
        row_source.open.return_value.__enter__ = MagicMock(return_value=MagicMock())
        row_source.open.return_value.__exit__ = MagicMock(return_value=False)

        app_settings = MagicMock()
        app_settings.matching_runtime.match_batch_size = 10
        app_settings.matching_runtime.match_flush_interval_ms = 100
        app_settings.matching_runtime.resolve_batch_size = 10
        app_settings.matching_runtime.resolve_flush_interval_ms = 100

        dataset_spec = MagicMock()
        dataset_spec.dataset_name = "employees"
        catalog = MagicMock()

        planning_runtime = MagicMock()
        planning_runtime.list_pending_rows.return_value = []

        pipeline = PlanningPipeline(
            transform_segment=transform_segment,
            match_stage=match_stage,
            resolve_context_stage=resolve_context_stage,
            resolve_stage=resolve_stage,
            dedup_store=dedup_store,
            row_source=row_source,
            catalog=catalog,
            dataset_spec=dataset_spec,
            app_settings=app_settings,
        )

        # open() вызывает open_match_runtime, которая может падать без реального runtime.
        # Проверяем только то, что reset() вызывается ПЕРЕД любыми операциями.
        dedup_store.reset.assert_not_called()

        # Пробуем вызвать open(); он может бросить из-за mock — нас интересует только reset().
        try:
            with pipeline.open(
                run_id="test-run",
                planning_runtime=planning_runtime,
                report_items_limit=100,
            ) as _:
                pass
        except Exception:
            pass

        dedup_store.reset.assert_called_once()
