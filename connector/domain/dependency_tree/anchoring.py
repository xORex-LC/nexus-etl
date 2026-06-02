"""Source anchoring — проверка source adjacency против target membership.

Модуль содержит dataset-agnostic contract Stage G: source-узлы уже
спроецированы в общий id-space, а target представлен плоским membership set.
Anchoring решает только reachability и dropped subtree.

Зона ответственности:
    - Проверять заякоренность source adjacency nodes через source/target anchors
    - Формировать node-id keyed verdicts для отсечения поддеревьев
    - Обнаруживать циклы в source adjacency graph

Вне области ответственности:
    - Читать source/cache или выполнять Polars-проекцию
    - Создавать row-level diagnostics и работать с row_ref
    - Решать pending/order semantics resolver-а
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Literal, Mapping


SourceAnchoringReason = Literal["missing_parent", "unanchored_subtree", "cycle"]


@dataclass(frozen=True)
class SourceAdjacencyNode:
    """Source-узел в абстрактном id-space Stage G."""

    node_id: str
    parent_id: str | None
    label: str


@dataclass(frozen=True)
class SourceAnchoringVerdict:
    """Решение об отсечении source-узла и причина graph-level failure."""

    node_id: str
    reason: SourceAnchoringReason
    broken_at_parent_id: str | None


@dataclass(frozen=True)
class SourceAnchoringResult:
    """Итог source anchoring без row-level привязки."""

    anchored_ids: frozenset[str]
    dropped: Mapping[str, SourceAnchoringVerdict]

    def __post_init__(self) -> None:
        object.__setattr__(self, "anchored_ids", frozenset(self.anchored_ids))
        object.__setattr__(self, "dropped", MappingProxyType(dict(self.dropped)))


def anchor_source_nodes(
    nodes: Iterable[SourceAdjacencyNode],
    *,
    target_ids: frozenset[str],
) -> SourceAnchoringResult:
    """Заякорить source adjacency nodes против target membership.

    Контракт:
        Узел считается валидным, если подъём по parent_id доходит до root,
        target id или source-родителя, который сам заякорен. Отсутствующий
        родитель отсекает узел и всё его поддерево.
    """

    nodes_by_id = _deduplicate_first(nodes)
    parent_by_id = {node_id: node.parent_id for node_id, node in nodes_by_id.items()}
    children_by_id = _build_children(parent_by_id)
    memo: dict[str, SourceAnchoringVerdict | None] = {}

    def visit(node_id: str, stack: tuple[str, ...]) -> SourceAnchoringVerdict | None:
        if node_id in memo:
            return memo[node_id]
        if node_id in stack:
            verdict = SourceAnchoringVerdict(
                node_id=node_id,
                reason="cycle",
                broken_at_parent_id=node_id,
            )
            memo[node_id] = verdict
            return verdict

        parent_id = parent_by_id[node_id]
        if parent_id is None or parent_id in target_ids:
            memo[node_id] = None
            return None
        if parent_id not in parent_by_id:
            verdict = SourceAnchoringVerdict(
                node_id=node_id,
                reason="missing_parent",
                broken_at_parent_id=parent_id,
            )
            memo[node_id] = verdict
            return verdict

        parent_verdict = visit(parent_id, (*stack, node_id))
        if parent_verdict is None:
            memo[node_id] = None
            return None
        reason: SourceAnchoringReason = (
            "cycle" if parent_verdict.reason == "cycle" else "unanchored_subtree"
        )
        verdict = SourceAnchoringVerdict(
            node_id=node_id,
            reason=reason,
            broken_at_parent_id=parent_verdict.broken_at_parent_id,
        )
        memo[node_id] = verdict
        return verdict

    for node_id in sorted(parent_by_id):
        visit(node_id, ())

    dropped: dict[str, SourceAnchoringVerdict] = {
        node_id: verdict for node_id, verdict in memo.items() if verdict is not None
    }
    for root_id, verdict in tuple(dropped.items()):
        for descendant_id in _descendants(root_id, children_by_id):
            if descendant_id in dropped:
                continue
            dropped[descendant_id] = SourceAnchoringVerdict(
                node_id=descendant_id,
                reason=(
                    "cycle" if verdict.reason == "cycle" else "unanchored_subtree"
                ),
                broken_at_parent_id=verdict.broken_at_parent_id,
            )

    anchored_ids = frozenset(node_id for node_id in parent_by_id if node_id not in dropped)
    return SourceAnchoringResult(anchored_ids=anchored_ids, dropped=dropped)


def _deduplicate_first(
    nodes: Iterable[SourceAdjacencyNode],
) -> dict[str, SourceAdjacencyNode]:
    result: dict[str, SourceAdjacencyNode] = {}
    for node in nodes:
        if node.node_id not in result:
            result[node.node_id] = node
    return result


def _build_children(parent_by_id: Mapping[str, str | None]) -> dict[str, tuple[str, ...]]:
    children: dict[str, list[str]] = {node_id: [] for node_id in parent_by_id}
    for node_id, parent_id in parent_by_id.items():
        if parent_id in children:
            children[parent_id].append(node_id)
    return {node_id: tuple(sorted(values)) for node_id, values in children.items()}


def _descendants(
    node_id: str,
    children_by_id: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    result: list[str] = []
    visited: set[str] = {node_id}
    stack = list(reversed(children_by_id.get(node_id, ())))
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        result.append(current)
        stack.extend(reversed(children_by_id.get(current, ())))
    return tuple(result)
