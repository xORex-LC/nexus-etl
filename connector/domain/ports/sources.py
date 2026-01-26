from __future__ import annotations

from typing import Iterable, Protocol, TypeVar, Generic
from connector.domain.transform.source_record import SourceRecord
from connector.domain.transform.result import TransformResult

T = TypeVar("T")
N = TypeVar("N")

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

class SourceMapper(Protocol, Generic[N, T]):
    """
    Назначение/ответственность:
        Маппер источника в каноническую форму для датасета.
    """

    def map(self, record: SourceRecord, normalized: N) -> TransformResult[T]:
        """
        Контракт:
            Вход: SourceRecord + нормализованная строка.
            Выход: TransformResult с row_ref/row/match_key.
        """
        ...
