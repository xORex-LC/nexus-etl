"""
Назначение:
    Доменные порты для transform-источников и справочников.
"""

from __future__ import annotations

from typing import Iterable, Protocol, TypeVar, Generic
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.core.result import TransformResult

T = TypeVar("T")

class RowSource(Protocol):
    """
    Назначение/ответственность:
        Источник SourceRecord для data transform и plan/apply конвейера.
    """

    def __iter__(self) -> Iterable[SourceRecord]:
        """
        Контракт:
            Возвращает итерируемые SourceRecord.
        """
        ...

class SourceMapper(Generic[T]):
    """
    Назначение/ответственность:
        Маппер источника в каноническую форму для датасета.
    """

    def map(self, record) -> TransformResult[T]:
        """
        Контракт:
            Вход: SourceRecord.
            Выход: TransformResult с row_ref/row/match_key.
        """
        raise NotImplementedError
