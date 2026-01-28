from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from connector.common.sanitize import maskSecretsInObject
from connector.domain.models import MatchStatus
from connector.domain.planning.match_models import MatchedRow
from connector.domain.planning.resolver import Resolver
from connector.domain.transform.result import TransformResult


class ResolveUseCase:
    """
    Назначение/ответственность:
        Use-case разрешения операций (match -> resolve).
    """

    def __init__(
        self,
        report_items_limit: int,
        include_resolved_items: bool,
    ) -> None:
        self.report_items_limit = report_items_limit
        self.include_resolved_items = include_resolved_items

    def iter_resolved_ok(
        self,
        matched_source: Iterable[TransformResult],
        resolver: Resolver,
    ):
        """
        Назначение:
            Итератор разрешённых строк без ошибок (для plan).
        """
        for resolved in self._iter_resolved(matched_source, resolver):
            if resolved.errors:
                continue
            yield resolved

    def run(
        self,
        matched_source: Iterable[TransformResult],
        resolver: Resolver,
        dataset: str,
        report,
    ) -> int:
        report.set_meta(dataset=dataset, items_limit=self.report_items_limit)
        for resolved in self._iter_resolved(matched_source, resolver):
            row = resolved.row
            if row is None:
                continue
            status = "FAILED" if resolved.errors else "OK"
            payload = asdict(row) if self.include_resolved_items and row is not None else None
            report.add_item(
                status=status,
                row_ref=row.row_ref if row else None,
                payload=maskSecretsInObject(payload) if payload else None,
                errors=resolved.errors,
                warnings=resolved.warnings,
                meta={"op": row.op if row else None},
                store=status == "FAILED" or self.include_resolved_items,
            )
        return 1 if report.summary.errors_total > 0 else 0

    def _iter_resolved(
        self,
        matched_source: Iterable[TransformResult],
        resolver: Resolver,
    ):
        matched_rows: list[TransformResult[MatchedRow]] = []
        for matched in matched_source:
            matched_rows.append(matched)

        resource_id_map = _build_resource_id_map(matched_rows)

        for matched in matched_rows:
            if matched.row is None:
                yield matched  # type: ignore[return-value]
                continue
            resolved_row, errors, warnings = resolver.resolve(
                matched.row,
                resource_id_map=resource_id_map,
            )
            yield TransformResult(
                record=matched.record,
                row=resolved_row,
                row_ref=matched.row_ref,
                match_key=matched.match_key,
                secret_candidates=matched.secret_candidates,
                errors=errors,
                warnings=warnings,
            )


def _build_resource_id_map(matched_rows: list[TransformResult[MatchedRow]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in matched_rows:
        row = item.row
        if row is None:
            continue
        if row.match_status == MatchStatus.MATCHED and row.existing:
            resource_id = row.existing.get("_id")
        else:
            resource_id = row.resource_id
        if resource_id:
            mapping[row.identity.primary_value] = str(resource_id)
    return mapping
