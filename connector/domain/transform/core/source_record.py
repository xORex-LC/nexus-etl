from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SourceRecord:
    """
    Назначение:
        Универсальная запись источника с каноническими ключами.
    """

    line_no: int
    record_id: str
    values: Mapping[str, Any]
