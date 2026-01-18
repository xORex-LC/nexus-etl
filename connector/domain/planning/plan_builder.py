from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from connector.planModels import Operation, PlanItem, PlanSummary
from connector.domain.validation.dataset_rules import ValidationRowResult

@dataclass
class PlanBuildResult:
    """
    Назначение:
        Итог сборки плана и отчётных элементов.
    """

    items: list[dict[str, Any]]
    summary: PlanSummary
    report_items: list[dict[str, Any]]
    items_truncated: bool

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
        Инкрементально собирает план (create/update) и отчётные элементы, считая summary.
    Взаимодействия:
        Используется оркестратором планирования; не знает о файловой системе.
    Ограничения:
        Лимиты отчёта (report_items_limit/include_skipped) применяются здесь.
    """

    def __init__(
        self,
        include_skipped_in_report: bool,
        report_items_limit: int,
    ) -> None:
        self.include_skipped_in_report = include_skipped_in_report
        self.report_items_limit = report_items_limit

        self.plan_items: list[dict[str, Any]] = []
        self.report_items: list[dict[str, Any]] = []
        self.items_truncated: bool = False

        self.rows_total = 0
        self.valid_rows = 0
        self.failed_rows = 0
        self.planned_create = 0
        self.planned_update = 0
        self.skipped_rows = 0

    def _can_store_report(self, status: str) -> bool:
        if status == "skipped" and not self.include_skipped_in_report:
            return False
        if len(self.report_items) >= self.report_items_limit:
            self.items_truncated = True
            return False
        return True

    def add_invalid(self, result: ValidationRowResult, errors: list[Any], warnings: list[Any]) -> None:
        """
        Назначение:
            Учесть невалидную строку и, при необходимости, добавить её в отчёт.
        """
        self.failed_rows += 1
        if self._can_store_report("failed"):
            self.report_items.append(
                {
                    "row_id": f"line:{result.line_no}",
                    "line_no": result.line_no,
                    "status": "invalid",
                    "match_key": result.match_key,
                    "errors": [e.__dict__ for e in errors],
                    "warnings": [w.__dict__ for w in warnings],
                }
            )

    def add_conflict(self, line_no: int, match_key: str, warnings: list[Any]) -> None:
        """
        Назначение:
            Учесть конфликт сопоставления.
        """
        self.failed_rows += 1
        if self._can_store_report("failed"):
            self.report_items.append(
                {
                    "row_id": f"line:{line_no}",
                    "line_no": line_no,
                    "status": "invalid",
                    "match_key": match_key,
                    "errors": [
                        {"code": "MATCH_CONFLICT", "field": "matchKey", "message": "multiple users with same match_key"}
                    ],
                    "warnings": [w.__dict__ for w in warnings],
                }
            )

    def add_skip(self, line_no: int, match_key: str, warnings: list[Any]) -> None:
        """
        Назначение:
            Учесть строку без изменений (skip).
        """
        self.skipped_rows += 1
        if self._can_store_report("skipped"):
            self.report_items.append(
                {
                    "row_id": f"line:{line_no}",
                    "line_no": line_no,
                    "status": "skipped",
                    "match_key": match_key,
                    "warnings": [w.__dict__ for w in warnings],
                }
            )

    def add_plan_item(self, plan_item: PlanItem) -> None:
        """
        Назначение:
            Добавить create/update операцию в план и summary.
        """
        if plan_item.op == Operation.CREATE:
            self.planned_create += 1
        elif plan_item.op == Operation.UPDATE:
            self.planned_update += 1
        self.plan_items.append(plan_item.__dict__)

    def inc_rows_total(self) -> None:
        self.rows_total += 1

    def inc_valid_rows(self) -> None:
        self.valid_rows += 1

    def build(self) -> PlanBuildResult:
        """
        Назначение:
            Вернуть итоговые данные плана/summary/отчёта.
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
            report_items=self.report_items,
            items_truncated=self.items_truncated,
        )
