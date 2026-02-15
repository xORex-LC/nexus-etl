from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecordRef:
    """Непрозрачная ссылка для корреляции записей (без payload и схемы источника)."""

    row_id: str
    line_no: int | None = None
