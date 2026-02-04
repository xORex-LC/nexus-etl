from __future__ import annotations

from typing import Iterable

from connector.domain.models import DiagnosticStage
from connector.domain.diagnostics.context import (
    error as diag_error,
    warning as diag_warning,
)
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.planning.match_models import MatchedRow
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.planning.matcher import Matcher
from connector.domain.transform.result_processor import PlanningResultProcessor
from connector.domain.transform.result import TransformResult
from connector.domain.planning.stages import MatchStage


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

    def iter_matched(
        self,
        validated_source: Iterable[TransformResult],
        matcher: Matcher,
        *,
        catalog: ErrorCatalog,
    ):
        """
        Назначение:
            Итератор сопоставленных строк (для resolver/plan).
        """
        return self._iter_matched(validated_source, matcher, catalog=catalog)

    def run(
        self,
        validated_source: Iterable[TransformResult],
        matcher: Matcher,
        dataset: str,
        report,
        catalog: ErrorCatalog,
    ) -> CommandResult:
        report.set_meta(dataset=dataset, items_limit=self.report_items_limit)
        processor = PlanningResultProcessor(
            report=report,
            include_items=self.include_matched_items,
            context_key="match",
            ok_label="matched_ok",
            failed_label="match_failed",
            meta_builder=lambda r: {"match_status": r.row.match_status if r.row else None},
            should_skip=lambda r: any(w.code == "MATCH_DUPLICATE_SOURCE" for w in r.warnings),
        )

        for matched in self._iter_matched(validated_source, matcher, catalog=catalog):
            processor.process(matched)

        result = processor.finalize()
        if report.summary.errors_total > 0:
            result.add_code(SystemErrorCode.CONFLICT)
        return result

    def _iter_matched(
        self,
        validated_source: Iterable[TransformResult],
        matcher: Matcher,
        *,
        catalog: ErrorCatalog,
    ):
        seen: dict[str, str] = {}
        stage = MatchStage(matcher, catalog)
        for matched in stage.run(validated_source):
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
