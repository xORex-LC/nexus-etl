from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable, Mapping

from connector.common.time import getNowIso
from connector.domain.models import DiagnosticStage, RowRef, ValidationErrorItem
from connector.domain.reporting.models import (
    ReportDiagnostic,
    ReportEnvelope,
    ReportItem,
    ReportMeta,
    ReportSummary,
)


class ReportCollector:
    """
    Назначение/ответственность:
        Единый сборщик отчётов для всех команд.
    """

    def __init__(self, run_id: str, command: str, started_at: str | None = None) -> None:
        self.meta = ReportMeta(
            run_id=run_id,
            dataset=None,
            command=command,
            started_at=started_at or getNowIso(),
        )
        self.summary = ReportSummary()
        self.items: list[ReportItem] = []
        self.context: dict[str, Any] = {}
        self.status: str | None = None

    def set_meta(
        self,
        *,
        dataset: str | None = None,
        items_limit: int | None = None,
        app_version: str | None = None,
        git_rev: str | None = None,
    ) -> None:
        if dataset is not None:
            self.meta.dataset = dataset
        if items_limit is not None:
            self.meta.items_limit = items_limit
        if app_version is not None:
            self.meta.app_version = app_version
        if git_rev is not None:
            self.meta.git_rev = git_rev

    def set_context(self, name: str, value: dict[str, Any]) -> None:
        self.context[name] = value

    def add_op(self, name: str, *, ok: int = 0, failed: int = 0, count: int = 0) -> None:
        entry = self.summary.ops.setdefault(name, {"ok": 0, "failed": 0, "count": 0})
        entry["ok"] += ok
        entry["failed"] += failed
        entry["count"] += count

    def add_item(
        self,
        *,
        status: str,
        row_ref: RowRef | None = None,
        payload: Mapping[str, Any] | None = None,
        errors: Iterable[ValidationErrorItem] | None = None,
        warnings: Iterable[ValidationErrorItem] | None = None,
        meta: dict[str, Any] | None = None,
        store: bool = True,
    ) -> None:
        error_list = list(errors or [])
        warning_list = list(warnings or [])

        self.summary.rows_total += 1
        if status == "FAILED":
            self.summary.rows_blocked += 1
        elif status == "OK":
            self.summary.rows_passed += 1
        if warning_list:
            self.summary.rows_with_warnings += 1

        self._count_diagnostics(error_list, warning_list)

        if store and self._should_store_item(status):
            diagnostics = self._build_diagnostics(error_list, warning_list)
            self.items.append(
                ReportItem(
                    status=status,
                    row_ref=row_ref,
                    payload=payload,
                    diagnostics=diagnostics,
                    meta=meta or {},
                )
            )
        elif store and status in ("FAILED", "OK"):
            self.meta.items_truncated = True

    def finish(self, finished_at: str | None = None, duration_ms: int | None = None) -> None:
        self.meta.finished_at = finished_at or getNowIso()
        self.meta.duration_ms = duration_ms
        if self.status is None:
            self.status = self._derive_status()

    def build(self) -> ReportEnvelope:
        return ReportEnvelope(
            status=self.status or self._derive_status(),
            meta=self.meta,
            summary=self.summary,
            items=self.items,
            context=self.context,
        )

    def _should_store_item(self, status: str) -> bool:
        limit = self.meta.items_limit
        if limit is None:
            return True
        return len(self.items) < limit

    def _derive_status(self) -> str:
        if self.summary.errors_total == 0:
            return "SUCCESS"
        if self.summary.rows_passed > 0:
            return "PARTIAL"
        return "FAILED"

    def _count_diagnostics(
        self,
        errors: list[ValidationErrorItem],
        warnings: list[ValidationErrorItem],
    ) -> None:
        self.summary.errors_total += len(errors)
        self.summary.warnings_total += len(warnings)
        for error in errors:
            self._count_stage(error.stage, "errors_total")
        for warning in warnings:
            self._count_stage(warning.stage, "warnings_total")

    def _count_stage(self, stage: DiagnosticStage, field: str) -> None:
        key = stage.value if isinstance(stage, DiagnosticStage) else str(stage)
        entry = self.summary.by_stage.setdefault(key, {"errors_total": 0, "warnings_total": 0})
        entry[field] += 1

    def _build_diagnostics(
        self,
        errors: list[ValidationErrorItem],
        warnings: list[ValidationErrorItem],
    ) -> list[ReportDiagnostic]:
        diagnostics: list[ReportDiagnostic] = []
        for err in errors:
            diagnostics.append(self._from_error(err, severity="error"))
        for warn in warnings:
            diagnostics.append(self._from_error(warn, severity="warning"))
        return diagnostics

    @staticmethod
    def _from_error(item: ValidationErrorItem, severity: str) -> ReportDiagnostic:
        return ReportDiagnostic(
            severity=severity,
            stage=item.stage,
            code=item.code,
            field=item.field,
            message=item.message,
            rule=getattr(item, "rule", None),
        )


def asdict_report(envelope: ReportEnvelope) -> dict[str, Any]:
    """
    Назначение:
        Упрощённая сериализация без привязки к dataclasses.asdict.
    """
    return {
        "status": envelope.status,
        "meta": asdict(envelope.meta),
        "summary": asdict(envelope.summary),
        "items": [
            {
                "status": item.status,
                "row_ref": asdict(item.row_ref) if item.row_ref else None,
                "payload": item.payload,
                "diagnostics": [asdict(diag) for diag in item.diagnostics],
                "meta": item.meta,
            }
            for item in envelope.items
        ],
        "context": envelope.context,
    }
