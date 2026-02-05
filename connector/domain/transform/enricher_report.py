"""
Назначение:
    Вспомогательные структуры для отчётов enricher.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass
class EnricherReport:
    """
    Назначение:
        Сводная статистика по операциям enrich для одной строки.

    Контракт:
        - record(report) увеличивает счётчики по outcome.
        - as_dict() возвращает сериализуемую структуру для meta.
    """

    operations_total: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    updated_fields: int = 0

    def record(self, report) -> None:
        """
        Назначение:
            Учесть результат операции enrich в сводке.
        """

        self.operations_total += 1
        key = report.outcome.value if hasattr(report.outcome, "value") else str(report.outcome)
        self.outcomes[key] = self.outcomes.get(key, 0) + 1
        if report.events:
            self.updated_fields += sum(
                1
                for event in report.events
                if getattr(event, "outcome", None) == "APPLIED"
            )

    def as_dict(self) -> dict[str, Any]:
        """
        Назначение:
            Представление в виде словаря для meta.
        """

        return {
            "operations_total": self.operations_total,
            "outcomes": dict(self.outcomes),
            "updated_fields": self.updated_fields,
        }


__all__ = ["EnricherReport"]
