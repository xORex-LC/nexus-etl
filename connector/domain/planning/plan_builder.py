from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from connector.domain.planning.plan_models import Operation, PlanItem, PlanSummary
from connector.domain.planning.match_models import ResolvedRow, ResolveOp

@dataclass
class PlanBuildResult:
    """
    Назначение:
        Итог сборки плана и агрегированной summary.
    """

    items: list[dict[str, Any]]
    summary: PlanSummary

    def summary_as_dict(self) -> dict[str, Any]:
        """
        Возвращает summary в виде dict для записи в артефакт.
        """
        return {
            "rows_total": self.summary.rows_total,
            "valid_rows": self.summary.valid_rows,
            "failed_rows": self.summary.failed_rows,
            "planned_create": self.summary.planned_create,
            "planned_update": self.summary.planned_update,
            "skipped": self.summary.skipped,
        }

class PlanBuilder:
    """
    Назначение/ответственность:
        Инкрементально собирает план (create/update) и summary.
    Взаимодействия:
        Используется resolver‑пайплайном; не знает о файловой системе/отчётах.
    """

    def __init__(self) -> None:
        self.plan_items: list[dict[str, Any]] = []
        self.rows_total = 0
        self.valid_rows = 0
        self.failed_rows = 0
        self.planned_create = 0
        self.planned_update = 0
        self.skipped_rows = 0

    def add_resolved(self, resolved: ResolvedRow) -> None:
        """
        Назначение:
            Добавить resolved‑строку в план/summary.
        """
        self.rows_total += 1
        self.valid_rows += 1

        if resolved.op == ResolveOp.SKIP:
            self.skipped_rows += 1
            return

        if resolved.op == ResolveOp.CONFLICT:
            self.failed_rows += 1
            return

        plan_item = PlanItem(
            row_id=resolved.row_ref.row_id,
            line_no=resolved.row_ref.line_no,
            op=Operation.CREATE if resolved.op == ResolveOp.CREATE else Operation.UPDATE,
            target_id=resolved.target_id or "",
            desired_state=resolved.desired_state,
            changes=resolved.changes,
            source_ref=resolved.source_ref,
            secret_fields=resolved.secret_fields,
        )
        if plan_item.op == Operation.CREATE:
            self.planned_create += 1
        else:
            self.planned_update += 1
        self.plan_items.append(self._serialize_plan_item(plan_item))

    def build(self) -> PlanBuildResult:
        """
        Назначение:
            Вернуть итоговые данные плана и summary.
        """
        summary = PlanSummary(
            rows_total=self.rows_total,
            valid_rows=self.valid_rows,
            failed_rows=self.failed_rows,
            planned_create=self.planned_create,
            planned_update=self.planned_update,
            skipped=self.skipped_rows,
        )
        return PlanBuildResult(
            items=self.plan_items,
            summary=summary,
        )

    def _serialize_plan_item(self, plan_item: PlanItem) -> dict[str, Any]:
        """
        Назначение:
            Явная сериализация плановой операции для сохранения в артефакт.
        Контракт:
            - Только разрешённые поля; без dataset/entity_type.
        """
        return {
            "row_id": plan_item.row_id,
            "line_no": plan_item.line_no,
            "op": plan_item.op,
            "target_id": plan_item.target_id,
            "desired_state": plan_item.desired_state,
            "changes": plan_item.changes,
            "source_ref": plan_item.source_ref,
            "secret_fields": list(plan_item.secret_fields or []),
        }
