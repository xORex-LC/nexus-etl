from __future__ import annotations

from typing import Callable, Iterable, TypeVar

from connector.domain.transform.result import TransformResult

T = TypeVar("T")


def iter_ok(
    source: Iterable[TransformResult[T]],
    *,
    should_skip: Callable[[TransformResult[T]], bool] | None = None,
) -> Iterable[TransformResult[T]]:
    """
    Назначение/ответственность:
        Унифицированный фильтр по ошибкам для TransformResult-потока.

    Контракт:
        - Пропускает записи с errors.
        - Может пропускать записи по доп. условию (should_skip).
    """
    for item in source:
        if item.errors:
            continue
        if should_skip and should_skip(item):
            continue
        yield item
