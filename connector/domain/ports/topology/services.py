"""Topology consumer service ports — узкие stage-facing контракты.

Модуль задаёт явные runtime contracts для topology-aware consumer-ов. Эти
порты держат match/resolve стадии изолированными от storage-деталей snapshot-а
и от внутренних деталей source-locator construction.

Responsibilities:
    - Описывать stage-facing topology compare contract
    - Описывать row-level source locator builder contract

Out of scope:
    - Конкретная comparison logic и source canonicalization
    - Runtime provider wiring и bootstrap orchestration
"""

from __future__ import annotations

from typing import Protocol

from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.ports.topology.models import (
    SourceTopologyCanonicalPath,
    TopologyMatchResult,
)


class SourceTopologyLocatorBuilderPort(Protocol):
    """Построить canonical source locator из текущего source record."""

    def build(self, record: SourceRecord) -> SourceTopologyCanonicalPath | None: ...


class TopologyMatchServicePort(Protocol):
    """Интерпретировать topology signal для disambiguation на match-стадии."""

    def compare(
        self,
        source_locator: SourceTopologyCanonicalPath,
        target_candidate_ids: tuple[str, ...],
    ) -> TopologyMatchResult: ...
