from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from connector.domain.models import DiagnosticItem


CommandStatus = Literal["ok", "warn", "error"]


@dataclass
class CommandResult:
    """
    Назначение:
        Результат выполнения CLI-команды (без I/O и без форматирования отчёта).
    """

    status: CommandStatus = "ok"
    stats: dict[str, int] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)
    errors: list[DiagnosticItem] = field(default_factory=list)
    warnings: list[DiagnosticItem] = field(default_factory=list)
