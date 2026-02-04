from __future__ import annotations

from typing import Iterable

from connector.domain.diagnostics.boundary import diagnostic_boundary
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.models import DiagnosticStage, MatchStatus
from connector.domain.planning.match_models import MatchedRow
from connector.domain.planning.matcher import Matcher
from connector.domain.planning.resolver import Resolver
from connector.domain.transform.result import TransformResult


class MatchStage:
    """
    Назначение/ответственность:
        Стадия match (validated -> matched).
    """

    def __init__(self, matcher: Matcher, catalog: ErrorCatalog) -> None:
        self.matcher = matcher
        self.catalog = catalog

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult[MatchedRow]]:
        for validated in source:
            boundary_errors: list = []
            matched: TransformResult[MatchedRow] | None = None
            with diagnostic_boundary(
                stage=DiagnosticStage.MATCH,
                catalog=self.catalog,
                sink=boundary_errors,
                record_ref=validated.row_ref,
            ):
                matched = self.matcher.match(validated)
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
            yield matched


class ResolveStage:
    """
    Назначение/ответственность:
        Стадия resolve (matched -> resolved).
    """

    def __init__(self, resolver: Resolver, catalog: ErrorCatalog) -> None:
        self.resolver = resolver
        self.catalog = catalog

    def run(
        self,
        source: Iterable[TransformResult[MatchedRow]],
        *,
        dataset: str | None = None,
    ) -> Iterable[TransformResult]:
        matched_rows: list[TransformResult[MatchedRow]] = []
        for matched in source:
            matched_rows.append(matched)

        batch_index = _build_batch_index(matched_rows, self.resolver, dataset)
        target_id_map = _build_target_id_map(matched_rows)

        for matched in matched_rows:
            if matched.row is None:
                yield matched  # type: ignore[return-value]
                continue
            boundary_errors: list = []
            resolved_row = None
            errors: list = []
            warnings: list = []
            with diagnostic_boundary(
                stage=DiagnosticStage.RESOLVE,
                catalog=self.catalog,
                sink=boundary_errors,
                record_ref=matched.row_ref,
            ):
                resolved_row, errors, warnings = self.resolver.resolve(
                    matched.row,
                    target_id_map=target_id_map,
                    meta=matched.meta,
                    batch_index=batch_index,
                )
            if boundary_errors:
                errors = [*errors, *boundary_errors]
            yield TransformResult(
                record=matched.record,
                row=resolved_row,
                row_ref=matched.row_ref,
                match_key=matched.match_key,
                meta=matched.meta,
                secret_candidates=matched.secret_candidates,
                errors=errors,
                warnings=warnings,
            )


def _build_target_id_map(matched_rows: list[TransformResult[MatchedRow]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in matched_rows:
        row = item.row
        if row is None:
            continue
        if row.match_status == MatchStatus.MATCHED and row.existing:
            target_id = row.existing.get("_id")
        else:
            target_id = row.target_id
        if target_id:
            mapping[row.identity.primary_value] = str(target_id)
    return mapping


def _build_batch_index(
    matched_rows: list[TransformResult[MatchedRow]],
    resolver: Resolver,
    dataset: str | None,
) -> dict[str, dict[str, list[str]]]:
    if dataset is None:
        return {}
    return resolver.build_batch_index(matched_rows, dataset)
