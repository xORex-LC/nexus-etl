from __future__ import annotations

from typing import Iterable

from connector.domain.ports.sources import RecordAdapterProtocol, RowSource
from connector.domain.transform.collect_result import CollectResult


class CollectingRecordSource:
    """
    Назначение/ответственность:
        Оборачивает RowSource и возвращает CollectResult через RecordAdapter.
    """

    def __init__(self, row_source: RowSource, adapter: RecordAdapterProtocol):
        self.row_source = row_source
        self.adapter = adapter

    def __iter__(self) -> Iterable[CollectResult]:
        for row in self.row_source:
            yield self.adapter.collect(row)
