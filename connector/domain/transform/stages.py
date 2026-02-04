from __future__ import annotations

from typing import Iterable, Protocol, Sequence, TypeVar

from connector.domain.diagnostics.boundary import diagnostic_boundary
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.models import DiagnosticStage
from connector.domain.ports.sources import SourceMapper
from connector.domain.transform.enricher import Enricher
from connector.domain.transform.normalizer import Normalizer
from connector.domain.transform.result import TransformResult
from connector.domain.validation.validator import Validator

T = TypeVar("T")


class TransformStageProcessor(Protocol):
    """
    Назначение/ответственность:
        Контракт процессора одной стадии трансформации.
    """

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        ...


class StagePipeline:
    """
    Назначение/ответственность:
        Последовательный запуск набора стадий (map/normalize/enrich/validate).
    """

    def __init__(self, stages: Sequence[TransformStageProcessor]) -> None:
        self.stages = stages

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        current = source
        for stage in self.stages:
            current = stage.run(current)
        return current


class MapStage:
    """
    Назначение/ответственность:
        Стадия map (source -> mapped).
    """

    def __init__(self, mapper: SourceMapper, catalog: ErrorCatalog) -> None:
        self.mapper = mapper
        self.catalog = catalog

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        for collected in source:
            if collected.errors:
                yield TransformResult(
                    record=collected.record,
                    row=None,
                    row_ref=collected.row_ref,
                    match_key=collected.match_key,
                    meta=collected.meta,
                    secret_candidates=collected.secret_candidates,
                    errors=[*collected.errors],
                    warnings=[*collected.warnings],
                )
                continue

            errors = [*collected.errors]
            warnings = [*collected.warnings]
            mapped: TransformResult | None = None
            with diagnostic_boundary(
                stage=DiagnosticStage.MAP,
                catalog=self.catalog,
                sink=errors,
                record_ref=collected.row_ref,
            ):
                mapped = self.mapper.map(collected.record)
            if mapped is None:
                yield TransformResult(
                    record=collected.record,
                    row=None,
                    row_ref=collected.row_ref,
                    match_key=collected.match_key,
                    meta=dict(collected.meta) if collected.meta else None,
                    secret_candidates=dict(collected.secret_candidates),
                    errors=errors,
                    warnings=warnings,
                )
                continue
            if collected.meta:
                if mapped.meta:
                    mapped.meta = {**collected.meta, **mapped.meta}
                else:
                    mapped.meta = dict(collected.meta)
            mapped.errors = [*errors, *mapped.errors]
            mapped.warnings = [*warnings, *mapped.warnings]
            yield mapped


class NormalizeStage:
    """
    Назначение/ответственность:
        Стадия normalize (mapped -> normalized).
    """

    def __init__(self, normalizer: Normalizer, catalog: ErrorCatalog) -> None:
        self.normalizer = normalizer
        self.catalog = catalog

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        for collected in source:
            if collected.errors:
                yield collected
                continue
            errors = [*collected.errors]
            warnings = [*collected.warnings]
            normalized: TransformResult | None = None
            with diagnostic_boundary(
                stage=DiagnosticStage.NORMALIZE,
                catalog=self.catalog,
                sink=errors,
                record_ref=collected.row_ref,
            ):
                normalized = self.normalizer.normalize(collected)
            if normalized is None:
                yield TransformResult(
                    record=collected.record,
                    row=None,
                    row_ref=collected.row_ref,
                    match_key=collected.match_key,
                    meta=dict(collected.meta) if collected.meta else None,
                    secret_candidates=dict(collected.secret_candidates),
                    errors=errors,
                    warnings=warnings,
                )
                continue
            yield normalized


class EnrichStage:
    """
    Назначение/ответственность:
        Стадия enrich (normalized -> enriched).
    """

    def __init__(self, enricher: Enricher, catalog: ErrorCatalog) -> None:
        self.enricher = enricher
        self.catalog = catalog

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        for collected in source:
            errors = [*collected.errors]
            warnings = [*collected.warnings]
            enriched: TransformResult | None = None
            with diagnostic_boundary(
                stage=DiagnosticStage.ENRICH,
                catalog=self.catalog,
                sink=errors,
                record_ref=collected.row_ref,
            ):
                enriched = self.enricher.enrich(collected)
            if enriched is None:
                yield TransformResult(
                    record=collected.record,
                    row=None,
                    row_ref=collected.row_ref,
                    match_key=collected.match_key,
                    meta=dict(collected.meta) if collected.meta else None,
                    secret_candidates=dict(collected.secret_candidates),
                    errors=errors,
                    warnings=warnings,
                )
                continue
            yield enriched


class ValidateStage:
    """
    Назначение/ответственность:
        Стадия validate (enriched -> validated).
    """

    def __init__(self, validator: Validator, catalog: ErrorCatalog) -> None:
        self.validator = validator
        self.catalog = catalog

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        for enriched in source:
            boundary_errors: list = []
            validated = None
            with diagnostic_boundary(
                stage=DiagnosticStage.VALIDATE,
                catalog=self.catalog,
                sink=boundary_errors,
                record_ref=enriched.row_ref,
            ):
                validated = self.validator.validate(enriched)
            if boundary_errors:
                yield TransformResult(
                    record=enriched.record,
                    row=None,
                    row_ref=enriched.row_ref,
                    match_key=enriched.match_key,
                    meta=enriched.meta,
                    secret_candidates=enriched.secret_candidates,
                    errors=[*enriched.errors, *boundary_errors],
                    warnings=[*enriched.warnings],
                )
                continue
            if validated is None:
                yield TransformResult(
                    record=enriched.record,
                    row=None,
                    row_ref=enriched.row_ref,
                    match_key=enriched.match_key,
                    meta=enriched.meta,
                    secret_candidates=enriched.secret_candidates,
                    errors=[*enriched.errors],
                    warnings=[*enriched.warnings],
                )
                continue
            validation_row = validated.row
            if validation_row is None:
                yield validated
                continue
            validation = validation_row.validation
            if not validation.errors:
                validated.errors = validation.errors
                validated.warnings = validation.warnings
            yield validated
