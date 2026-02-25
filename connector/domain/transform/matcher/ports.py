"""
Назначение:
    Domain-порты dedup-стора и runtime-зависимостей для match-стадии.

    ISourceDedupStore   — контракт хранилища, которое отслеживает,
                          встречалась ли уже данная identity-запись в текущем (или предыдущих) прогонах.
    DedupOutcome        — результат проверки, возвращаемый check_and_register().
    IMatchBatchSettings — параметры micro-batching (batch_size, flush_interval_ms).
    IMatchScopeService  — управление lifecycle runtime-скоупа матчера (clear_scope).
"""

from __future__ import annotations

from typing import Protocol


class DedupOutcome(Protocol):
    is_first: bool
    is_duplicate: bool
    is_conflict: bool


class ISourceDedupStore(Protocol):
    def check_and_register(self, key: str, fingerprint: str) -> DedupOutcome: ...

    def reset(self) -> None: ...


class IMatchBatchSettings(Protocol):
    """Параметры micro-batching для MatchStage."""

    batch_size: int
    flush_interval_ms: int


class IMatchScopeService(Protocol):
    """Управление lifecycle runtime-скоупа матчера."""

    def clear_scope(self) -> None: ...


__all__ = ["DedupOutcome", "ISourceDedupStore", "IMatchBatchSettings", "IMatchScopeService"]
