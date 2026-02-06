"""
Назначение:
    Единая обработка TransformResult для отчётов и статистики.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from connector.common.sanitize import maskSecretsInObject
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.models import RowRef, DiagnosticItem
from connector.domain.reporting.diagnostics import split_report_diagnostics
from connector.domain.transform.core.result import TransformResult


class TransformResultProcessor:
    """
    Назначение/ответственность:
        Унифицированная обработка TransformResult для стадий map/normalize/enrich/validate.

    Контракт:
        - Отсекает записи с ошибками (FAILED) и считает статистику.
        - Формирует report items по единому правилу.
        - Возвращает CommandResult на основе количества ошибок.
    """

    def __init__(
        self,
        *,
        report,
        include_items: bool,
        context_key: str,
        ok_label: str,
        failed_label: str,
        payload_builder: Callable[[TransformResult], Any] | None = None,
    ) -> None:
        self.report = report
        self.include_items = include_items
        self.context_key = context_key
        self.ok_label = ok_label
        self.failed_label = failed_label
        self.payload_builder = payload_builder

        self.rows_total = 0
        self.ok_rows = 0
        self.failed_rows = 0
        self.warnings_rows = 0
        self.vault_candidates_rows = 0
        self.vault_candidates_fields_total = 0

    def process(
        self,
        result: TransformResult | None,
        *,
        row_ref: RowRef | None = None,
        force_failed: bool = False,
        errors_override: list[DiagnosticItem] | None = None,
        warnings_override: list[DiagnosticItem] | None = None,
    ) -> None:
        """
        Назначение:
            Обрабатывает одну запись с единым правилом фильтрации/репортинга.

        Алгоритм:
            - Вычисляет итоговый статус (OK/FAILED).
            - Обновляет счётчики summary.
            - Строит payload и report-диагностику.
            - Добавляет элемент в отчёт при необходимости.
        """
        self.rows_total += 1

        eff_errors = errors_override if errors_override is not None else (result.errors if result else [])
        eff_warnings = warnings_override if warnings_override is not None else (result.warnings if result else [])

        has_errors = force_failed or bool(eff_errors)
        status = "FAILED" if has_errors else "OK"

        if has_errors:
            self.failed_rows += 1
        else:
            self.ok_rows += 1

        if eff_warnings:
            self.warnings_rows += 1

        secret_fields: list[str] = []
        if result:
            meta_secret_fields = result.meta.get("secret_fields") if result.meta else None
            if isinstance(meta_secret_fields, (list, tuple, set)):
                secret_fields = [str(item) for item in meta_secret_fields if item]
            elif result.secret_candidates:
                secret_fields = list(result.secret_candidates.keys())
            if secret_fields:
                self.vault_candidates_rows += 1
                self.vault_candidates_fields_total += len(secret_fields)

        should_store = status == "FAILED" or self.include_items

        effective_row_ref = row_ref or (result.row_ref if result else None)
        if effective_row_ref is None and result is not None:
            effective_row_ref = RowRef(
                line_no=result.record.line_no,
                row_id=result.record.record_id,
                identity_primary=None,
                identity_value=None,
            )

        row_payload = None
        if should_store and result is not None and result.row is not None:
            payload_obj = self.payload_builder(result) if self.payload_builder else result.row
            if payload_obj is not None:
                if isinstance(payload_obj, dict):
                    row_payload = maskSecretsInObject(payload_obj)
                elif hasattr(payload_obj, "__dataclass_fields__"):
                    row_payload = maskSecretsInObject(asdict(payload_obj))
                else:
                    row_payload = maskSecretsInObject(payload_obj)
            if row_payload is not None and isinstance(row_payload, dict) and secret_fields:
                for field in secret_fields:
                    row_payload[field] = "***"

        report_errors, report_warnings = split_report_diagnostics(eff_errors, eff_warnings)
        self.report.add_item(
            status=status,
            row_ref=effective_row_ref,
            payload=row_payload,
            errors=report_errors,
            warnings=report_warnings,
            meta={
                "match_key": result.match_key.value if result and result.match_key else None,
                "secret_candidate_fields": secret_fields,
            },
            store=should_store,
        )

    def finalize(self) -> CommandResult:
        """
        Назначение:
            Записывает summary и возвращает CommandResult.
        """
        self.report.set_context(
            self.context_key,
            {
                "rows_total": self.rows_total,
                self.ok_label: self.ok_rows,
                self.failed_label: self.failed_rows,
                "warnings_rows": self.warnings_rows,
                "vault_candidates_rows": self.vault_candidates_rows,
                "vault_candidates_fields_total": self.vault_candidates_fields_total,
            },
        )
        result = CommandResult()
        if self.failed_rows > 0:
            result.add_code(SystemErrorCode.DATA_INVALID)
        else:
            result.add_code(SystemErrorCode.OK)
        return result


class PlanningResultProcessor(TransformResultProcessor):
    """
    Назначение/ответственность:
        Унифицированная обработка результатов match/resolve с учетом planning-метаданных.
    """

    def __init__(
        self,
        *,
        report,
        include_items: bool,
        context_key: str,
        ok_label: str,
        failed_label: str,
        meta_builder: Callable[[TransformResult], dict[str, Any] | None],
        should_skip: Callable[[TransformResult], bool] | None = None,
        payload_builder: Callable[[TransformResult], Any] | None = None,
    ) -> None:
        super().__init__(
            report=report,
            include_items=include_items,
            context_key=context_key,
            ok_label=ok_label,
            failed_label=failed_label,
            payload_builder=payload_builder,
        )
        self.meta_builder = meta_builder
        self.should_skip = should_skip

    def process(
        self,
        result: TransformResult | None,
        *,
        row_ref: RowRef | None = None,
        force_failed: bool = False,
        errors_override: list[DiagnosticItem] | None = None,
        warnings_override: list[DiagnosticItem] | None = None,
    ) -> None:
        """
        Назначение:
            Обработать planning-результат с учётом meta/skip-логики.

        Алгоритм:
            - Опционально пропускает result по should_skip.
            - Строит payload и meta через meta_builder.
            - Добавляет item в отчёт согласно include_items.
        """
        if result is None:
            return super().process(
                result,
                row_ref=row_ref,
                force_failed=force_failed,
                errors_override=errors_override,
                warnings_override=warnings_override,
            )
        if self.should_skip and self.should_skip(result):
            return
        self.rows_total += 1

        eff_errors = errors_override if errors_override is not None else result.errors
        eff_warnings = warnings_override if warnings_override is not None else result.warnings

        has_errors = force_failed or bool(eff_errors)
        status = "FAILED" if has_errors else "OK"

        if has_errors:
            self.failed_rows += 1
        else:
            self.ok_rows += 1

        if eff_warnings:
            self.warnings_rows += 1

        should_store = status == "FAILED" or self.include_items

        effective_row_ref = row_ref or result.row_ref
        if effective_row_ref is None:
            effective_row_ref = RowRef(
                line_no=result.record.line_no,
                row_id=result.record.record_id,
                identity_primary=None,
                identity_value=None,
            )

        row_payload = None
        if should_store and result.row is not None:
            payload_obj = self.payload_builder(result) if self.payload_builder else result.row
            if payload_obj is not None:
                if isinstance(payload_obj, dict):
                    row_payload = maskSecretsInObject(payload_obj)
                elif hasattr(payload_obj, "__dataclass_fields__"):
                    row_payload = maskSecretsInObject(asdict(payload_obj))
                else:
                    row_payload = maskSecretsInObject(payload_obj)
            if row_payload is not None and isinstance(row_payload, dict) and result.meta:
                secret_fields = result.meta.get("secret_fields")
                if isinstance(secret_fields, (list, tuple, set)):
                    for field in secret_fields:
                        row_payload[field] = "***"

        meta = self.meta_builder(result) or {}

        report_errors, report_warnings = split_report_diagnostics(eff_errors, eff_warnings)
        self.report.add_item(
            status=status,
            row_ref=effective_row_ref,
            payload=row_payload,
            errors=report_errors,
            warnings=report_warnings,
            meta=meta,
            store=should_store,
        )
