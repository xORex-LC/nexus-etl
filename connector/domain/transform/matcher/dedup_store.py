"""
Назначение:
    Реализации ISourceDedupStore.

    LocalSourceDedupStore  — in-memory хранилище для одного прогона.
    ScopedSourceDedupStore — делегирует к cache_gateway для cross-run
                             персистентного состояния (аналог bind_runtime_scope).

Жизненный цикл:
    - Создаётся как Singleton в DI-контейнере (per-PipelineRunContext).
    - Перед каждым прогоном PlanningPipeline вызывает reset().
    - ScopedSourceDedupStore сохраняет scoped-state в cache_gateway
      между прогонами; reset() очищает только локальный кэш.
"""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.ports.cache.roles import MatchRuntimePort
from connector.domain.transform.matcher.ports import DedupOutcome


@dataclass(frozen=True)
class DedupResult:
    """
    Назначение:
        Конкретная реализация DedupOutcome.

    Инварианты:
        Ровно одно из трёх полей — True.
    """

    is_first: bool
    is_duplicate: bool
    is_conflict: bool


_FIRST: DedupResult = DedupResult(is_first=True, is_duplicate=False, is_conflict=False)
_DUPLICATE: DedupResult = DedupResult(is_first=False, is_duplicate=True, is_conflict=False)
_CONFLICT: DedupResult = DedupResult(is_first=False, is_duplicate=False, is_conflict=True)


class LocalSourceDedupStore:
    """
    Назначение:
        In-memory dedup-стор: полный аналог _seen_source из MatchCore.

    Область видимости:
        Один прогон пайплайна. После reset() состояние очищается.
    """

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def check_and_register(self, key: str, fingerprint: str) -> DedupResult:
        prev = self._seen.get(key)
        if prev is None:
            self._seen[key] = fingerprint
            return _FIRST
        if prev == fingerprint:
            return _DUPLICATE
        return _CONFLICT

    def reset(self) -> None:
        self._seen.clear()


class ScopedSourceDedupStore:
    """
    Назначение:
        Dedup-стор с персистентным scoped-состоянием через cache_gateway.

    Алгоритм check_and_register:
        1. Проверяет локальный _seen (in-memory, per-run).
        2. При отсутствии — проверяет cache_gateway.get_runtime_state() (cross-run).
        3. При первом вхождении — записывает в оба хранилища.

    reset():
        Очищает только _seen (локальный per-run кэш).
        Scoped-состояние в cache_gateway сохраняется между прогонами намеренно.
    """

    def __init__(
        self,
        cache_gateway: MatchRuntimePort,
        scope: str,
        dataset: str,
    ) -> None:
        self._cache_gateway = cache_gateway
        self._scope = scope
        self._dataset = dataset
        self._seen: dict[str, str] = {}

    def check_and_register(self, key: str, fingerprint: str) -> DedupResult:
        prev = self._seen.get(key)
        if prev is None:
            prev = self._cache_gateway.get_runtime_state(self._scope, self._dataset, key)
        if prev is None:
            self._seen[key] = fingerprint
            self._cache_gateway.set_runtime_state(self._scope, self._dataset, key, fingerprint)
            return _FIRST
        if prev == fingerprint:
            return _DUPLICATE
        return _CONFLICT

    def reset(self) -> None:
        self._seen.clear()


__all__ = ["DedupResult", "LocalSourceDedupStore", "ScopedSourceDedupStore"]
