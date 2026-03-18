"""
Назначение:
    Контекст строки для стадий match/resolve без зависимости от ValidateStage.

Граница ответственности:
    Хранит только generic runtime metadata, общую для matcher/resolver.
    Dataset-specific поля не поднимаются в MatchContext и читаются из row
    через compiled DSL rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from connector.domain.models import DiagnosticItem, RowRef


@dataclass
class MatchContext:
    """
    Назначение:
        Единый runtime-контекст строки для matcher/resolver.

    Граница ответственности:
        - Owns: line metadata, match_key, row_ref, diagnostics, secret metadata.
        - Does NOT: хранить dataset-specific row fields.
    """

    line_no: int
    match_key: str
    match_key_complete: bool
    row_ref: RowRef | None = None
    secret_candidates: dict[str, str] = field(default_factory=dict)
    secret_fields: list[str] = field(default_factory=list)
    errors: list[DiagnosticItem] = field(default_factory=list)
    warnings: list[DiagnosticItem] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0
