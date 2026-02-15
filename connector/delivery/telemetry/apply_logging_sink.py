from __future__ import annotations

import logging

from connector.domain.models import DiagnosticItem
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.planning.record_ref import RecordRef
from connector.usecases.apply.models import ApplySummary


class LoggingApplyTelemetrySink:
    """Структурированное per-item логирование apply на уровне delivery/infra."""

    def __init__(self, logger: logging.Logger, run_id: str, dataset: str) -> None:
        self._logger = logger
        self._run_id = run_id
        self._dataset = dataset

    def _extra(self, record_ref: RecordRef, op: str) -> dict:
        return {
            "runId": self._run_id,
            "component": "import-apply",
            "dataset": self._dataset,
            "op": op,
            "row_id": record_ref.row_id,
            "line_no": record_ref.line_no,
        }

    def on_item_ok(self, *, record_ref: RecordRef, op: str, target_id: str | None) -> None:
        self._logger.log(
            logging.DEBUG,
            f"Apply OK: {op} target_id={target_id}",
            extra=self._extra(record_ref, op),
        )

    def on_item_warn(self, *, record_ref: RecordRef, op: str, diag: DiagnosticItem) -> None:
        self._logger.log(
            logging.WARNING,
            f"Apply WARN: {op} code={diag.code} message={diag.message}",
            extra=self._extra(record_ref, op),
        )

    def on_item_error(self, *, record_ref: RecordRef, op: str, diag: DiagnosticItem) -> None:
        self._logger.log(
            logging.ERROR,
            f"Apply ERROR: {op} code={diag.code} message={diag.message}",
            extra=self._extra(record_ref, op),
        )

    def on_summary(
        self,
        *,
        primary_code: SystemErrorCode,
        all_codes: tuple[SystemErrorCode, ...],
        fatal_error: bool,
        counters: ApplySummary,
    ) -> None:
        self._logger.log(
            logging.INFO,
            f"Apply summary: created={counters.created} updated={counters.updated} "
            f"failed={counters.failed} skipped={counters.skipped} "
            f"primary_code={primary_code.value} fatal={fatal_error}",
            extra={"runId": self._run_id, "component": "import-apply"},
        )
