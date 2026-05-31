"""Порты topology-builder-ов — узкие контракты для source и target ingest

Определяет domain-facing builder contracts, которые позже будут использовать
bootstrap/usecase слои. Builders намеренно разделены, потому что source
path-ingest и target adjacency-ingest имеют разную validation semantics.

Зона ответственности:
    - Определять отдельные contracts для source и target topology builders

Вне области ответственности:
    - Bootstrap orchestration и provider wiring
    - Target read или readiness evaluation
"""

from __future__ import annotations

from typing import Iterable, Protocol

from connector.domain.dependency_tree.snapshot import TopologySnapshot
from connector.domain.models import DiagnosticItem
from connector.domain.ports.topology.models import (
    SourceTopologyCanonicalPath,
    TargetHierarchyRow,
)


class SourcePathTopologyBuilderPort(Protocol):
    """Построить topology snapshot из canonical source path-ов"""

    def build(
        self,
        paths: Iterable[SourceTopologyCanonicalPath],
    ) -> tuple[
        TopologySnapshot, tuple[DiagnosticItem, ...], tuple[DiagnosticItem, ...]
    ]: ...


class TargetHierarchyTopologyBuilderPort(Protocol):
    """Построить topology snapshot из explicit target adjacency rows"""

    def build(
        self,
        rows: Iterable[TargetHierarchyRow],
    ) -> tuple[
        TopologySnapshot, tuple[DiagnosticItem, ...], tuple[DiagnosticItem, ...]
    ]: ...
