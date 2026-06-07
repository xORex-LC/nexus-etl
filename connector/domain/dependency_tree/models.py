"""Модели dependency_tree — неизменяемые объекты topology-узлов

Содержит минимальные доменные сущности topology-подсистемы. Эти модели описывают
только node-level relation и labels; производные query-факты вроде depth, root
или descendant sets живут в snapshot/query слое.

Зона ответственности:
    - Представлять topology node в immutable runtime-safe форме
    - Держать node-level identifiers и labels отдельно от query helper-логики

Вне области ответственности:
    - Graph traversal и lookup API
    - Builder validation, diagnostics и infra-specific payload
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TopologyNode:
    """Неизменяемый topology-узел для runtime snapshot-ов

    Узел хранит только local relation и label information. Query-derived факты
    вроде canonical path или structural signature вычисляются snapshot-слоем,
    чтобы node contract оставался маленьким и стабильным.
    """

    node_id: str
    parent_id: str | None
    display_name: str
    canonical_name: str
