"""Source topology filter stage — row-level применение Stage G verdicts.

Стадия применяет заранее вычисленный source anchoring result к основному
pipeline stream после Map. Она не строит graph и не читает source повторно:
на вход получает только `SourceTopologyValidationState`.

Зона ответственности:
    - Найти mapped node id в текущей строке
    - Превратить graph verdict в row-level DiagnosticItem с актуальным row_ref
    - Применить policy skip/warn/hard_error к текущему TransformResult

Вне области ответственности:
    - Source adjacency projection и anchoring
    - Target membership reading
    - Pending/link resolution
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from connector.domain.diagnostics.catalog import ErrorCatalog, build_error, build_warning
from connector.domain.models import DiagnosticStage
from connector.domain.ports.topology import SourceTopologyValidationState
from connector.domain.transform.core.result import TransformResult


class SourceTopologyFilterStage:
    """Отсечь или пометить mapped source rows по precomputed anchoring verdicts."""

    stage_name = "source_topology_filter"

    def __init__(
        self,
        *,
        validation: SourceTopologyValidationState | None,
        catalog: ErrorCatalog,
    ) -> None:
        self._validation = validation
        self._catalog = catalog

    def run(
        self,
        source: Iterable[TransformResult[Mapping[str, Any]]],
    ) -> Iterable[TransformResult[Mapping[str, Any]]]:
        """Применить source anchoring verdicts к mapped stream."""

        validation = self._validation
        if validation is None or not validation.dropped:
            yield from source
            return

        for result in source:
            if result.row is None:
                yield result
                continue
            node_id = _node_id(result.row, validation.node_id_field)
            if node_id is None:
                yield result
                continue
            verdict = validation.dropped.get(node_id)
            if verdict is None:
                yield result
                continue
            diagnostic_factory = (
                build_warning if validation.on_unanchored == "warn" else build_error
            )
            diagnostic = diagnostic_factory(
                catalog=self._catalog,
                stage=DiagnosticStage.RESOLVE,
                code="TOPOLOGY_SOURCE_UNANCHORED",
                field=validation.node_id_field,
                message=f"Source topology node '{node_id}' is not anchored",
                record_ref=result.row_ref,
                details={
                    "node_id": node_id,
                    "reason": verdict.reason,
                    "broken_at_parent_id": verdict.broken_at_parent_id,
                },
            )
            builder = result.as_builder()
            if validation.on_unanchored == "warn":
                builder.add_warning_item(diagnostic)
            else:
                builder.set_row(None)
                builder.add_error_item(diagnostic)
            yield builder.build()


def _node_id(row: Mapping[str, Any], field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
