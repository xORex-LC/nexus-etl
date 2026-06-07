"""Порт topology-provider-а — stage-facing доступ к topology snapshot-ам

Определяет runtime capability boundary для стадий и use case-ов, которым нужен
read-only доступ к заранее построенным topology snapshots.

Зона ответственности:
    - Отдавать required/optional access к source и target snapshots

Вне области ответственности:
    - Snapshot construction или readiness evaluation
    - Metadata/provenance access
"""

from __future__ import annotations

from typing import Protocol

from connector.domain.dependency_tree.snapshot import TopologySnapshot


class TopologyNotAvailableError(Exception):
    """Поднимается, когда required topology snapshot недоступен"""


class TopologyProviderPort(Protocol):
    """Read-only runtime access к заранее собранным topology snapshot-ам"""

    def require_source(self) -> TopologySnapshot: ...
    def require_target(self) -> TopologySnapshot: ...
    def get_source(self) -> TopologySnapshot | None: ...
    def get_target(self) -> TopologySnapshot | None: ...
