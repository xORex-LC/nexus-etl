"""Snapshot dependency_tree — read-only query-слой над topology-индексами

Содержит immutable topology snapshot и его stage-facing query semantics.
Snapshot владеет graph indices и deterministic query methods, а builders
остаются ответственными только за ingestion и validation.

Зона ответственности:
    - Хранить topology indices в read-only runtime-safe форме
    - Отдавать graph queries, нужные topology-aware consumer-ам

Вне области ответственности:
    - Source/target data ingestion
    - Diagnostics emission и validation policy
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol

from connector.domain.dependency_tree.fingerprints import build_structural_signature
from connector.domain.dependency_tree.models import TopologyNode


class TopologyQueryPort(Protocol):
    """Контракт topology-запросов для runtime consumer-ов"""

    def get_node(self, node_id: str) -> TopologyNode | None: ...
    def require_node(self, node_id: str) -> TopologyNode: ...
    def parent_id(self, node_id: str) -> str | None: ...
    def children_ids(self, node_id: str) -> tuple[str, ...]: ...
    def ancestors(self, node_id: str) -> tuple[str, ...]: ...
    def descendants(self, node_id: str) -> tuple[str, ...]: ...
    def path_to_root(self, node_id: str) -> tuple[str, ...]: ...
    def depth(self, node_id: str) -> int: ...
    def root_id(self, node_id: str) -> str: ...
    def canonical_path(self, node_id: str) -> tuple[str, ...]: ...
    def structural_signature(self, node_id: str) -> str: ...


@dataclass(frozen=True)
class TopologySnapshot:
    """Неизменяемые topology-индексы с детерминированными query-хелперами

    Инварианты:
        - ``nodes_by_id``, ``parent_by_id`` and ``children_by_id`` are read-only
        - Child collections are stored as tuples to prevent in-place mutation
        - Query methods never mutate internal state
    """

    nodes_by_id: Mapping[str, TopologyNode]
    parent_by_id: Mapping[str, str | None]
    children_by_id: Mapping[str, tuple[str, ...]]
    roots: tuple[str, ...]

    def __post_init__(self) -> None:
        nodes = MappingProxyType(dict(self.nodes_by_id))
        parent = MappingProxyType(dict(self.parent_by_id))
        children = MappingProxyType(
            {key: tuple(value) for key, value in self.children_by_id.items()}
        )
        object.__setattr__(self, "nodes_by_id", nodes)
        object.__setattr__(self, "parent_by_id", parent)
        object.__setattr__(self, "children_by_id", children)
        object.__setattr__(self, "roots", tuple(self.roots))

    @classmethod
    def empty(cls) -> "TopologySnapshot":
        """Вернуть пустой immutable snapshot"""

        return cls(nodes_by_id={}, parent_by_id={}, children_by_id={}, roots=())

    def get_node(self, node_id: str) -> TopologyNode | None:
        return self.nodes_by_id.get(node_id)

    def require_node(self, node_id: str) -> TopologyNode:
        node = self.get_node(node_id)
        if node is None:
            raise KeyError(f"Unknown topology node: {node_id}")
        return node

    def parent_id(self, node_id: str) -> str | None:
        self.require_node(node_id)
        return self.parent_by_id.get(node_id)

    def children_ids(self, node_id: str) -> tuple[str, ...]:
        self.require_node(node_id)
        return self.children_by_id.get(node_id, ())

    def ancestors(self, node_id: str) -> tuple[str, ...]:
        result: list[str] = []
        current = self.parent_id(node_id)
        while current is not None:
            result.append(current)
            current = self.parent_id(current)
        return tuple(result)

    def descendants(self, node_id: str) -> tuple[str, ...]:
        self.require_node(node_id)
        result: list[str] = []
        stack = list(reversed(sorted(self.children_ids(node_id))))
        while stack:
            current = stack.pop()
            result.append(current)
            children = sorted(self.children_ids(current))
            stack.extend(reversed(children))
        return tuple(result)

    def path_to_root(self, node_id: str) -> tuple[str, ...]:
        self.require_node(node_id)
        path = [node_id]
        current = self.parent_id(node_id)
        while current is not None:
            path.append(current)
            current = self.parent_id(current)
        return tuple(path)

    def depth(self, node_id: str) -> int:
        return len(self.ancestors(node_id))

    def root_id(self, node_id: str) -> str:
        return self.path_to_root(node_id)[-1]

    def canonical_path(self, node_id: str) -> tuple[str, ...]:
        path_ids = reversed(self.path_to_root(node_id))
        return tuple(
            self.require_node(current_id).canonical_name for current_id in path_ids
        )

    def structural_signature(self, node_id: str) -> str:
        return build_structural_signature(
            canonical_path=self.canonical_path(node_id),
            root_id=self.root_id(node_id),
            depth=self.depth(node_id),
        )
