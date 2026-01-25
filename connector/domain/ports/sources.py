from __future__ import annotations

from typing import Iterable, Protocol, TypeVar, Generic

from connector.domain.models import CsvRow
from connector.domain.transform.map_result import MapResult
from connector.domain.transform.source_record import SourceRecord
from connector.domain.transform.collect_result import CollectResult

T = TypeVar("T")

class LegacyRowSource(Protocol):
    """
    Назначение/ответственность:
        Legacy источник CsvRow (используется в CSV-адаптерах).

    TODO: TECHDEBT - удалить после полного перехода на SourceRecord.
    """

    def __iter__(self) -> Iterable[CsvRow]:
        """
        Контракт:
            Возвращает итерируемые CsvRow (с заполненными file_line_no/values).
        """
        ...


class RowSource(Protocol):
    """
    Назначение/ответственность:
        Источник SourceRecord для transform/validate/plan.
    """

    def __iter__(self) -> Iterable[SourceRecord]:
        """
        Контракт:
            Возвращает итерируемые SourceRecord.
        """
        ...

class RowMapper(Protocol):
    """
    Назначение/ответственность:
        Нормализует сырые данные (dict/CSV row) в унифицированный CsvRow.
    Взаимодействия:
        Может использоваться нормализатором/планировщиком для разных схем.
    """

    # TODO: TECHDEBT - legacy mapper for CsvRow; remove after SourceRecord migration.
    def map(self, raw: dict) -> CsvRow:
        """
        Контракт:
            Вход: сырой dict/строка.
            Выход: CsvRow с values и file_line_no.
        """
        ...


class SourceMapper(Protocol, Generic[T]):
    """
    Назначение/ответственность:
        Маппер источника в каноническую форму для датасета.
    """

    def map(self, raw: SourceRecord) -> MapResult[T]:
        """
        Контракт:
            Вход: SourceRecord (универсальная запись источника).
            Выход: MapResult с row_ref/row/match_key.
        """
        ...


class RecordAdapterProtocol(Protocol):
    """
    Назначение/ответственность:
        Адаптер исходной строки в SourceRecord с диагностикой.
    """

    def collect(self, raw: CsvRow) -> CollectResult:
        """
        Контракт:
            Вход: CsvRow (legacy CSV запись).
            Выход: CollectResult (SourceRecord + ошибки/варнинги).
        """
        ...
