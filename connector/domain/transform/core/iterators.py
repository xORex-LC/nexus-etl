"""
Назначение:
    Итераторы для фильтрации/разделения потоков результатов.
"""

from __future__ import annotations

from time import monotonic
from typing import Callable, Iterable, Iterator, TypeVar

from connector.domain.transform.core.result import TransformResult

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


def iter_micro_batches(
    source: Iterable[T],
    *,
    batch_size: int,
    flush_interval_ms: int,
) -> Iterator[list[T]]:
    """
    Назначение/ответственность:
        Буферизует поток в микро-батчи по размеру и интервалу flush.

    Контракт:
        - batch_size <= 0 нормализуется в 1.
        - flush_interval_ms <= 0 отключает time-based flush.
        - Интервальный flush срабатывает при поступлении очередного элемента.
    """
    normalized_size = batch_size if batch_size > 0 else 1
    normalized_interval = flush_interval_ms if flush_interval_ms > 0 else 0
    batch: list[T] = []
    opened_at: float | None = None

    for item in source:
        now = monotonic()
        if batch and normalized_interval > 0 and opened_at is not None:
            elapsed_ms = int((now - opened_at) * 1000)
            if elapsed_ms >= normalized_interval:
                yield batch
                batch = []
                opened_at = None

        if not batch:
            opened_at = now
        batch.append(item)
        if len(batch) >= normalized_size:
            yield batch
            batch = []
            opened_at = None

    if batch:
        yield batch
