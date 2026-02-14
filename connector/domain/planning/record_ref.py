from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecordRef:
    """Opaque correlation reference (no payload, no source schema)."""

    row_id: str
    line_no: int | None = None
