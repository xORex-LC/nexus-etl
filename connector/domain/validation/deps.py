from __future__ import annotations

from dataclasses import dataclass

from connector.domain.ports.lookups import LookupProtocol

@dataclass
class ValidationDependencies:
    """
    Назначение:
        Универсальные зависимости валидатора.
    """
    org_lookup: LookupProtocol | None = None
