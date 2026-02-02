from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from connector.common.sanitize import maskSecretsInObject
from connector.domain.models import DiagnosticStage
from connector.domain.diagnostics.context import (
    error as diag_error,
    warning as diag_warning,
)
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.boundary import diagnostic_boundary
from connector.domain.planning.match_models import MatchedRow
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.planning.matcher import Matcher
from connector.domain.transform.result import TransformResult


class MatchUseCase:
    """
    Назначение/ответственность:
        Use-case для сопоставления валидированных строк (validate -> match).
    """

    def __init__(
        self,
        report_items_limit: int,
        include_matched_items: bool,
    ) -> None:
        self.report_items_limit = report_items_limit
        self.include_matched_items = include_matched_items

    def iter_matched_ok(
        self,
        validated_source: Iterable[TransformResult],
        matcher: Matcher,
        *,
        catalog: ErrorCatalog,
    ):
        """
        Назначение:
            Итератор сопоставленных строк без ошибок (для resolver).
        """
        for matched in self._iter_matched(validated_source, matcher, catalog=catalog):
            if matched.errors:
                continue
            if any(w.code == "MATCH_DUPLICATE_SOURCE" for w in matched.warnings):
                continue
            yield matched

    def run(
        self,
        validated_source: Iterable[TransformResult],
        matcher: Matcher,
        dataset: str,
        report,
        catalog: ErrorCatalog,
    ) -> CommandResult:
        report.set_meta(dataset=dataset, items_limit=self.report_items_limit)
        for matched in self._iter_matched(validated_source, matcher, catalog=catalog):
            row = matched.row
            row_ref = row.row_ref if row else None
            status = "FAILED" if matched.errors else "OK"
            payload = asdict(row) if self.include_matched_items and row is not None else None
            report.add_item(
                status=status,
                row_ref=row_ref,
                payload=maskSecretsInObject(payload) if payload else None,
                errors=matched.errors,
                warnings=matched.warnings,
                meta={"match_status": row.match_status if row else None},
                store=status == "FAILED" or self.include_matched_items,
            )
        result = CommandResult()
        if report.summary.errors_total > 0:
            result.add_code(SystemErrorCode.CONFLICT)
        else:
            result.add_code(SystemErrorCode.OK)
        return result

    def _iter_matched(
        self,
        validated_source: Iterable[TransformResult],
        matcher: Matcher,
        *,
        catalog: ErrorCatalog,
    ):
        seen: dict[str, str] = {}
        for validated in validated_source:
            boundary_errors: list = []
            matched: TransformResult[MatchedRow] | None = None
            with diagnostic_boundary(
                stage=DiagnosticStage.MATCH,
                catalog=catalog,
                sink=boundary_errors,
                record_ref=validated.row_ref,
            ):
                matched = matcher.match(validated)
            if matched is None:
                yield TransformResult(
                    record=validated.record,
                    row=None,
                    row_ref=validated.row_ref,
                    match_key=validated.match_key,
                    meta=validated.meta,
                    secret_candidates=validated.secret_candidates,
                    errors=[*validated.errors, *boundary_errors],
                    warnings=[*validated.warnings],
                )
                continue
            if boundary_errors:
                matched.errors = [*matched.errors, *boundary_errors]
            if matched.row is None:
                yield matched
                continue

            identity_value = matched.row.identity.primary_value
            fingerprint = matched.row.fingerprint
            if identity_value in seen:
                if seen[identity_value] == fingerprint:
                    warning = diag_warning(
                        catalog=catalog,
                        stage=DiagnosticStage.MATCH,
                        code="MATCH_DUPLICATE_SOURCE",
                        field=matched.row.identity.primary,
                        message="duplicate row in source batch",
                        record_ref=matched.row.row_ref,
                    )
                    matched.warnings.append(warning)
                    yield matched
                    continue
                error = diag_error(
                    catalog=catalog,
                    stage=DiagnosticStage.MATCH,
                    code="MATCH_CONFLICT_SOURCE",
                    field=matched.row.identity.primary,
                    message="conflicting rows in source batch",
                    record_ref=matched.row.row_ref,
                )
                matched.errors.append(error)
                yield matched
                continue

            seen[identity_value] = fingerprint
            yield matched
