"""
Назначение:
    Конкретные реализации domain-портов IMatchBatchSettings и IMatchScopeService.

    MatchBatchSettings — параметры micro-batching для MatchStage.
    MatchScopeService  — управляет lifecycle runtime-скоупа матчера:
                         вызывает clear_runtime_scope() при завершении прогона.
"""
from __future__ import annotations

from connector.domain.ports.cache.roles import MatchRuntimePort
from connector.domain.transform.matcher.ports import IMatchBatchSettings, IMatchScopeService


class MatchBatchSettings:
    """Параметры micro-batching для MatchStage."""

    def __init__(self, batch_size: int = 500, flush_interval_ms: int = 500) -> None:
        self.batch_size = batch_size
        self.flush_interval_ms = flush_interval_ms


class MatchScopeService:
    """
    Назначение/ответственность:
        Очистка runtime-скоупа матчера после завершения прогона.

    Граница ответственности:
        - Owns: вызов clear_runtime_scope() с корректным scope-ключом.
        - Does NOT: управлять lifecycle MatchRuntimePort или match-стадией.
    """

    def __init__(self, match_runtime: MatchRuntimePort, run_id: str) -> None:
        self._match_runtime = match_runtime
        self._run_id = run_id

    def clear_scope(self) -> None:
        self._match_runtime.clear_runtime_scope(f"run:{self._run_id}")


__all__ = ["MatchBatchSettings", "MatchScopeService"]
