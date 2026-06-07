from __future__ import annotations

from typing import Any

from connector.domain.models import DiagnosticItem
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.planning.record_ref import RecordRef
from connector.usecases.apply.models import ApplySummary


class LoggingApplyTelemetrySink:
    """Структурированное per-item логирование apply на уровне delivery/infra."""

    def __init__(self, logger: Any, dataset: str) -> None:
        self._logger = logger
        self._dataset = dataset

    def _extra(self, record_ref: RecordRef, op: str) -> dict:
        return {
            "scope": "import-apply",
            "dataset": self._dataset,
            "op": op,
            "row_id": record_ref.row_id,
            "line_no": record_ref.line_no,
        }

    def on_item_ok(
        self, *, record_ref: RecordRef, op: str, target_id: str | None
    ) -> None:
        self._logger.debug(
            "Apply item succeeded",
            target_id=target_id,
            **self._extra(record_ref, op),
        )

    def on_item_warn(
        self, *, record_ref: RecordRef, op: str, diag: DiagnosticItem
    ) -> None:
        self._logger.warning(
            "Apply item warning",
            diag_code=diag.code,
            diagnostic_message=diag.message,
            **self._extra(record_ref, op),
        )

    def on_item_error(
        self, *, record_ref: RecordRef, op: str, diag: DiagnosticItem
    ) -> None:
        self._logger.error(
            "Apply item failed",
            diag_code=diag.code,
            diagnostic_message=diag.message,
            **self._extra(record_ref, op),
        )

    def on_summary(
        self,
        *,
        primary_code: SystemErrorCode,
        all_codes: tuple[SystemErrorCode, ...],
        fatal_error: bool,
        counters: ApplySummary,
    ) -> None:
        self._logger.info(
            "Apply summary",
            scope="import-apply",
            created=counters.created,
            updated=counters.updated,
            failed=counters.failed,
            skipped=counters.skipped,
            primary_code=primary_code.value,
            all_codes=[code.value for code in all_codes],
            fatal=fatal_error,
        )
