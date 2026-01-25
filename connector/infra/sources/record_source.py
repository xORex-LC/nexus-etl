from __future__ import annotations

from typing import Iterable, Type

from connector.domain.ports.sources import RecordAdapterProtocol, LegacyRowSource
from connector.domain.transform.collect_result import CollectResult
from connector.infra.sources.csv_reader import CsvRowSource


class CollectingRecordSource:
    """
    Назначение/ответственность:
        Оборачивает LegacyRowSource и возвращает CollectResult через RecordAdapter.
    """

    def __init__(self, row_source: LegacyRowSource, adapter: RecordAdapterProtocol):
        self.row_source = row_source
        self.adapter = adapter

    def __iter__(self) -> Iterable[CollectResult]:
        for row in self.row_source:
            yield self.adapter.collect(row)


class CsvCollectResultSource:
    """
    Назначение/ответственность:
        Источник CollectResult для CSV (оборачивает CsvRowSource).
    """

    def __init__(
        self,
        csv_path: str,
        csv_has_header: bool,
        adapter: RecordAdapterProtocol,
        row_source_cls: Type[LegacyRowSource] = CsvRowSource,
    ):
        self.csv_path = csv_path
        self.csv_has_header = csv_has_header
        self.adapter = adapter
        self.row_source_cls = row_source_cls

    def __iter__(self) -> Iterable[CollectResult]:
        row_source = self.row_source_cls(self.csv_path, self.csv_has_header)
        for row in row_source:
            yield self.adapter.collect(row)
