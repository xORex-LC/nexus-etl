"""Trace-порты dependency_tree — domain-local seam для topology-отладки

Определяет fine-grained trace abstraction, которую topology builders используют
для optional DEBUG-level observability. Domain layer зависит только от этого
seam и ничего не знает о logging backend.

Зона ответственности:
    - Предоставлять узкий trace contract для topology build internals
    - Давать default no-op implementation для hot path

Вне области ответственности:
    - Transport/backend logging integration
    - Runtime bootstrap или provider orchestration
"""

from __future__ import annotations

from typing import Protocol


class TopologyTracePort(Protocol):
    """Узкий trace seam для внутренних шагов topology build"""

    def node_ingested(
        self,
        *,
        node_id: str,
        parent_id: str | None,
        canonical_name: str,
    ) -> None: ...

    def path_ingested(
        self,
        *,
        canonical_segments: tuple[str, ...],
        synthetic_node_id: str,
    ) -> None: ...

    def cycle_checked(
        self,
        *,
        nodes: int,
        has_cycle: bool,
    ) -> None: ...


class NullTopologyTrace:
    """Пустая trace-реализация для production hot path"""

    def node_ingested(
        self,
        *,
        node_id: str,
        parent_id: str | None,
        canonical_name: str,
    ) -> None:
        return None

    def path_ingested(
        self,
        *,
        canonical_segments: tuple[str, ...],
        synthetic_node_id: str,
    ) -> None:
        return None

    def cycle_checked(
        self,
        *,
        nodes: int,
        has_cycle: bool,
    ) -> None:
        return None
