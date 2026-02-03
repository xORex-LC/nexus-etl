from __future__ import annotations

from typing import Generic, TypeVar

from connector.domain.transform.result import TransformResult
from connector.domain.models import DiagnosticStage
from connector.domain.diagnostics.boundary import diagnostic_boundary
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.sources import SourceMapper
from connector.domain.transform.normalizer import Normalizer
from connector.domain.transform.enricher import Enricher

T = TypeVar("T")
N = TypeVar("N")
D = TypeVar("D")


class TransformPipeline(Generic[T, N, D]):
    """
    Назначение/ответственность:
        Последовательный запуск map -> normalize -> enrich без валидации.
    """

    def __init__(
        self,
        mapper: SourceMapper[T],
        normalizer: Normalizer[N],
        enricher: Enricher[N, D],
        catalog: ErrorCatalog,
    ) -> None:
        self.mapper = mapper
        self.normalizer = normalizer
        self.enricher = enricher
        self.catalog = catalog

    def map_source(self, collected: TransformResult[None]) -> TransformResult[T]:
        if collected.errors:
            return TransformResult(
                record=collected.record,
                row=None,
                row_ref=collected.row_ref,
                match_key=collected.match_key,
                meta=collected.meta,
                secret_candidates=collected.secret_candidates,
                errors=[*collected.errors],
                warnings=[*collected.warnings],
            )
        errors = [*collected.errors]
        warnings = [*collected.warnings]
        mapped: TransformResult[T] | None = None
        with diagnostic_boundary(
            stage=DiagnosticStage.MAP,
            catalog=self.catalog,
            sink=errors,
            record_ref=collected.row_ref,
        ):
            mapped = self.mapper.map(collected.record)
        if mapped is None:
            return TransformResult(
                record=collected.record,
                row=None,
                row_ref=collected.row_ref,
                match_key=collected.match_key,
                meta=dict(collected.meta) if collected.meta else None,
                secret_candidates=dict(collected.secret_candidates),
                errors=errors,
                warnings=warnings,
            )
        if collected.meta:
            if mapped.meta:
                mapped.meta = {**collected.meta, **mapped.meta}
            else:
                mapped.meta = dict(collected.meta)
        mapped.errors = [*errors, *mapped.errors]
        mapped.warnings = [*warnings, *mapped.warnings]
        return mapped

    def normalize_only(self, collected: TransformResult[None]) -> TransformResult[N]:
        mapped = self.map_source(collected)
        if mapped.errors:
            return mapped  # type: ignore[return-value]
        errors = [*mapped.errors]
        warnings = [*mapped.warnings]
        normalized: TransformResult[N] | None = None
        with diagnostic_boundary(
            stage=DiagnosticStage.NORMALIZE,
            catalog=self.catalog,
            sink=errors,
            record_ref=mapped.row_ref,
        ):
            normalized = self.normalizer.normalize(mapped)
        if normalized is None:
            return TransformResult(
                record=mapped.record,
                row=None,
                row_ref=mapped.row_ref,
                match_key=mapped.match_key,
                meta=dict(mapped.meta) if mapped.meta else None,
                secret_candidates=dict(mapped.secret_candidates),
                errors=errors,
                warnings=warnings,
            )
        # Normalizer already propagates upstream diagnostics into the result.
        # Re-adding them here would duplicate errors/warnings.
        return normalized

    def enrich(self, collected: TransformResult[None]) -> TransformResult[N]:
        normalized = self.normalize_only(collected)
        errors = [*normalized.errors]
        warnings = [*normalized.warnings]
        enriched: TransformResult[N] | None = None
        with diagnostic_boundary(
            stage=DiagnosticStage.ENRICH,
            catalog=self.catalog,
            sink=errors,
            record_ref=normalized.row_ref,
        ):
            enriched = self.enricher.enrich(normalized)
        if enriched is None:
            return TransformResult(
                record=normalized.record,
                row=None,
                row_ref=normalized.row_ref,
                match_key=normalized.match_key,
                meta=dict(normalized.meta) if normalized.meta else None,
                secret_candidates=dict(normalized.secret_candidates),
                errors=errors,
                warnings=warnings,
            )
        # Enricher already carries upstream diagnostics in the result.
        # Re-adding them here would duplicate errors/warnings.
        return enriched
