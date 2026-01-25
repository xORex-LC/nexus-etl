from __future__ import annotations

from typing import Iterable, Protocol, TypeVar, Generic

from connector.domain.models import CsvRow
from connector.domain.transform.map_result import MapResult
from connector.domain.transform.source_record import SourceRecord

T = TypeVar("T")

class RowSource(Protocol):
    """
    Назначение/ответственность:
        Источник нормализованных строк для валидатора/планировщика (абстракция над CSV/маппером).
    Взаимодействия:
        Потребляется пайплайнами validate/plan/apply.
    """

    def __iter__(self) -> Iterable[CsvRow]:
        """
        Контракт:
            Возвращает итерируемые CsvRow (с заполненными file_line_no/values).
        """
        ...

class RowMapper(Protocol):
    """
    Назначение/ответственность:
        Нормализует сырые данные (dict/CSV row) в унифицированный CsvRow.
    Взаимодействия:
        Может использоваться нормализатором/планировщиком для разных схем.
    """

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
