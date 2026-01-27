from __future__ import annotations

from typing import Iterable, Protocol, TypeVar, Generic
from connector.domain.transform.result import TransformResult

T = TypeVar("T")

class RowSource(Protocol):
    """
    Назначение/ответственность:
        Источник SourceRecord для transform/validate/plan.
    """

    def __iter__(self) -> Iterable[TransformResult[None]]:
        """
        Контракт:
            Возвращает итерируемые TransformResult с SourceRecord.
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
