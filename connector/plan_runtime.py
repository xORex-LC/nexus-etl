from __future__ import annotations

from dataclasses import dataclass
from typing import List

from connector.planModels import PlanItem, PlanMeta, PlanSummary


@dataclass(frozen=True)
class ResolvedPlanItem:
    """
    Назначение:
        Плановая операция с уже определённым датасетом (runtime-представление).
    """

    dataset: str
    item: PlanItem


@dataclass
class ResolvedPlan:
    """
    Назначение:
        План с однородным dataset, пригодный для исполнения.
    """

    meta: PlanMeta
    items: List[ResolvedPlanItem]
    summary: PlanSummary | None = None
