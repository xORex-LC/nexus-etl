"""
Тесты PipelineRunContext — per-run dataclass с dedup_store и batch_index.
"""

from __future__ import annotations

from unittest.mock import Mock

from connector.domain.transform.matcher.dedup_store import LocalSourceDedupStore
from connector.domain.transform.matcher.ports import ISourceDedupStore
from connector.domain.transform.resolver.batch_index_service import InMemoryBatchIndexService
from connector.domain.transform.resolver.ports import IBatchIndexService
from connector.domain.transform.pipeline_run_context import PipelineRunContext


def test_pipeline_run_context_holds_dedup_store_and_batch_index():
    dedup_store = LocalSourceDedupStore()
    batch_index = InMemoryBatchIndexService()
    ctx = PipelineRunContext(dedup_store=dedup_store, batch_index=batch_index)
    assert ctx.dedup_store is dedup_store
    assert ctx.batch_index is batch_index


def test_pipeline_run_context_accepts_protocol_implementations():
    """PipelineRunContext принимает любые реализации протоколов."""
    dedup_store = Mock(spec=ISourceDedupStore)
    batch_index = Mock(spec=IBatchIndexService)
    ctx = PipelineRunContext(dedup_store=dedup_store, batch_index=batch_index)
    assert ctx.dedup_store is dedup_store
    assert ctx.batch_index is batch_index


def test_dedup_store_is_accessible_and_functional():
    ctx = PipelineRunContext(
        dedup_store=LocalSourceDedupStore(),
        batch_index=InMemoryBatchIndexService(),
    )
    result = ctx.dedup_store.check_and_register("key:1", "fp-aaa")
    assert result.is_first is True


def test_batch_index_is_accessible_and_functional():
    ctx = PipelineRunContext(
        dedup_store=LocalSourceDedupStore(),
        batch_index=InMemoryBatchIndexService(),
    )
    index = {"key:1": ["id-1"]}
    ctx.batch_index.set_index(index)
    assert ctx.batch_index.get() == index
