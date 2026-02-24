"""
Тесты InMemoryBatchIndexService.
"""

from __future__ import annotations

import pytest

from connector.domain.transform.resolver.batch_index_service import InMemoryBatchIndexService


def test_get_before_set_index_raises_runtime_error():
    service = InMemoryBatchIndexService()
    with pytest.raises(RuntimeError, match="IBatchIndexService.get\\(\\) called before set_index\\(\\)"):
        service.get()


def test_get_after_set_index_returns_index():
    service = InMemoryBatchIndexService()
    index = {"match_key:user-1": ["id-1"]}
    service.set_index(index)
    assert service.get() is index


def test_set_index_replaces_previous_index():
    service = InMemoryBatchIndexService()
    index1 = {"key:1": ["id-1"]}
    index2 = {"key:2": ["id-2"]}
    service.set_index(index1)
    service.set_index(index2)
    assert service.get() is index2


def test_set_index_with_empty_dict():
    service = InMemoryBatchIndexService()
    service.set_index({})
    assert service.get() == {}


def test_get_returns_same_reference():
    """get() не копирует индекс, возвращает ссылку."""
    service = InMemoryBatchIndexService()
    index = {"key:1": ["id-1", "id-2"]}
    service.set_index(index)
    assert service.get() is index
