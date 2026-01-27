from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from connector.domain.planning.plan_models import Operation, PlanItem, PlanSummary
from connector.domain.models import DiagnosticStage, RowRef, ValidationErrorItem, ValidationRowResult
from connector.domain.reporting.collector import ReportCollector

@dataclass
class PlanBuildResult:
    """
    Назначение:
        Итог сборки плана и отчётных элементов.
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
        identity_label: str,
        conflict_code: str,
        conflict_field: str,
        report: ReportCollector,
    ) -> None:
        self.include_skipped_in_report = include_skipped_in_report
        self.report_items_limit = report_items_limit
        self.identity_label = identity_label
        self.conflict_code = conflict_code
        self.conflict_field = conflict_field

        self.plan_items: list[dict[str, Any]] = []
        self.report = report

        self.rows_total = 0
        self.valid_rows = 0
        self.failed_rows = 0
        self.planned_create = 0
        self.planned_update = 0
        self.skipped_rows = 0

    def _should_store(self, status: str) -> bool:
        if status == "SKIPPED" and not self.include_skipped_in_report:
            return False
        return status in ("FAILED", "SKIPPED")

    def add_invalid(self, result: ValidationRowResult, errors: list[Any], warnings: list[Any]) -> None:
        """
        Назначение:
            Учесть невалидную строку и, при необходимости, добавить её в отчёт.
        """
        self.rows_total += 1
        self.failed_rows += 1
        row_ref = result.row_ref or RowRef(
            line_no=result.line_no,
            row_id=f"line:{result.line_no}",
            identity_primary=self.identity_label,
            identity_value=None,
        )
        self.report.add_item(
            status="FAILED",
            row_ref=row_ref,
            payload=None,
            errors=errors,
            warnings=warnings,
            meta={"identity_label": self.identity_label},
            store=self._should_store("FAILED"),
        )

    def add_conflict(self, line_no: int, identity_value: str, warnings: list[Any]) -> None:
        """
        Назначение:
            Учесть конфликт сопоставления.
        """
        self.rows_total += 1
        self.failed_rows += 1
        row_ref = RowRef(
            line_no=line_no,
            row_id=f"line:{line_no}",
            identity_primary=self.identity_label,
            identity_value=identity_value,
        )
        conflict_error = ValidationErrorItem(
            stage=DiagnosticStage.PLAN,
            code=self.conflict_code,
            field=self.conflict_field,
            message="multiple candidates found",
        )
        self.report.add_item(
            status="FAILED",
            row_ref=row_ref,
            payload=None,
            errors=[conflict_error],
            warnings=warnings,
            meta={"identity_label": self.identity_label},
            store=self._should_store("FAILED"),
        )

    def add_skip(self, line_no: int, identity_value: str, warnings: list[Any]) -> None:
        """
        Назначение:
            Учесть строку без изменений (skip).
        """
        self.rows_total += 1
        self.valid_rows += 1
        self.skipped_rows += 1
        row_ref = RowRef(
            line_no=line_no,
            row_id=f"line:{line_no}",
            identity_primary=self.identity_label,
            identity_value=identity_value,
        )
        self.report.add_item(
            status="SKIPPED",
            row_ref=row_ref,
            payload=None,
            errors=[],
            warnings=warnings,
            meta={"identity_label": self.identity_label},
            store=self._should_store("SKIPPED"),
        )

    def add_plan_item(self, plan_item: PlanItem) -> None:
        """
        Назначение:
            Добавить create/update операцию в план и summary.
        """
        self.rows_total += 1
        self.valid_rows += 1
        if plan_item.op == Operation.CREATE:
            self.planned_create += 1
        elif plan_item.op == Operation.UPDATE:
            self.planned_update += 1
        self.plan_items.append(self._serialize_plan_item(plan_item))
        self.report.add_item(
            status="OK",
            row_ref=RowRef(
                line_no=plan_item.line_no,
                row_id=plan_item.row_id,
                identity_primary=self.identity_label,
                identity_value=None,
            ),
            payload=None,
            errors=[],
            warnings=[],
            meta={
                "op": plan_item.op,
                "resource_id": plan_item.resource_id,
                "changes": plan_item.changes,
                "desired_state": plan_item.desired_state,
                "source_ref": plan_item.source_ref,
            },
            store=False,
        )

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
            "resource_id": plan_item.resource_id,
            "desired_state": plan_item.desired_state,
            "changes": plan_item.changes,
            "source_ref": plan_item.source_ref,
            "secret_fields": list(plan_item.secret_fields or []),
        }
