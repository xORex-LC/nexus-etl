"""
Назначение:
    Стадии конвейера data transform (map/normalize/enrich/match/resolve).
"""

from __future__ import annotations

from typing import Callable, Iterable, Protocol, Sequence, TypeVar

from connector.domain.diagnostics.boundary import diagnostic_boundary
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.models import DiagnosticStage, MatchStatus
from connector.domain.ports.transform.sources import SourceMapper
from connector.domain.transform.enrich import EnricherEngine
from connector.domain.transform.normalize import NormalizerEngine
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.matching.deduplication_transform import DeduplicationTransform
from connector.domain.transform.matching.lookup_enricher import LookupEnricher
from connector.domain.transform.matching.match_models import MatchedRow

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
        Последовательный запуск набора стадий (map/normalize/enrich/match/resolve).
    """

    def __init__(self, stages: Sequence[TransformStageProcessor]) -> None:
        self.stages = stages

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        """
        Назначение:
            Прогнать поток результатов через цепочку стадий.

        Алгоритм:
            - Последовательно передаёт поток в каждую стадию.
            - Для batched-стадий буферизует вход в чанки.
        """
        current = source
        for stage in self.stages:
            if getattr(stage, "_is_batched", False):
                batches = _buffer_into_batches(
                    current,
                    batch_size=getattr(stage, "_batch_size", 1000),
                    key=getattr(stage, "_batch_key", None),
                )
                current = _run_batched(stage, batches)
                continue
            current = stage.run(current)
        return current


def batched(batch_size: int = 1000, key: Callable | None = None):
    """
    Назначение/ответственность:
        Декоратор-маркер для стадий, которым нужен батч входных данных.
    """

    def decorator(stage_cls):
        stage_cls._is_batched = True
        stage_cls._batch_size = batch_size
        stage_cls._batch_key = key
        return stage_cls

    return decorator


def _buffer_into_batches(
    stream: Iterable[TransformResult],
    *,
    batch_size: int,
    key: Callable | None = None,
) -> Iterable[list[TransformResult]]:
    """
    Назначение:
        Буферизовать поток в батчи.

    Алгоритм:
        - Без key: фиксированный размер батча.
        - С key: шардирование по ключу с ограничением размера.
    """
    if batch_size <= 0:
        batch_size = 1
    if key is None:
        batch: list[TransformResult] = []
        for item in stream:
            batch.append(item)
            if len(batch) >= batch_size:
                yield batch
                batch = []
        if batch:
            yield batch
        return
    buckets: dict[object, list[TransformResult]] = {}
    for item in stream:
        bucket_key = key(item)
        bucket = buckets.setdefault(bucket_key, [])
        bucket.append(item)
        if len(bucket) >= batch_size:
            yield bucket
            buckets[bucket_key] = []
    for bucket in buckets.values():
        if bucket:
            yield bucket


def _run_batched(stage: TransformStageProcessor, batches: Iterable[list[TransformResult]]) -> Iterable[TransformResult]:
    """
    Назначение:
        Прокрутить батчи через стадию и развернуть обратно в поток.
    """
    for batch in batches:
        for item in stage.run(batch):
            yield item


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
                builder = collected.as_builder()
                builder.set_row(None)
                yield builder.build()
                continue

            boundary_errors: list = []
            mapped: TransformResult | None = None
            with diagnostic_boundary(
                stage=DiagnosticStage.MAP,
                catalog=self.catalog,
                sink=boundary_errors,
                record_ref=collected.row_ref,
            ):
                mapped = self.mapper.map(collected.record)
            if mapped is None:
                builder = collected.as_builder()
                builder.set_row(None)
                for err in boundary_errors:
                    builder.add_error_item(err)
                yield builder.build()
                continue
            builder = mapped.as_builder()
            if collected.meta:
                builder.meta = {**collected.meta, **builder.meta}
            builder.errors = [*collected.errors, *boundary_errors, *builder.errors]
            builder.warnings = [*collected.warnings, *builder.warnings]
            yield builder.build()


class NormalizeStage:
    """
    Назначение/ответственность:
        Стадия normalize (mapped -> normalized).
    """

    def __init__(self, normalizer: NormalizerEngine, catalog: ErrorCatalog) -> None:
        self.normalizer = normalizer
        self.catalog = catalog

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        for collected in source:
            if collected.errors:
                yield collected
                continue
            boundary_errors: list = []
            normalized: TransformResult | None = None
            with diagnostic_boundary(
                stage=DiagnosticStage.NORMALIZE,
                catalog=self.catalog,
                sink=boundary_errors,
                record_ref=collected.row_ref,
            ):
                normalized = self.normalizer.normalize(collected)
            if normalized is None:
                builder = collected.as_builder()
                builder.set_row(None)
                for err in boundary_errors:
                    builder.add_error_item(err)
                yield builder.build()
                continue
            builder = normalized.as_builder()
            for err in boundary_errors:
                builder.add_error_item(err)
            yield builder.build()


class EnrichStage:
    """
    Назначение/ответственность:
        Стадия enrich (normalized -> enriched).
    """

    def __init__(self, enricher: EnricherEngine, catalog: ErrorCatalog) -> None:
        self.enricher = enricher
        self.catalog = catalog

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        for collected in source:
            boundary_errors: list = []
            enriched: TransformResult | None = None
            with diagnostic_boundary(
                stage=DiagnosticStage.ENRICH,
                catalog=self.catalog,
                sink=boundary_errors,
                record_ref=collected.row_ref,
            ):
                enriched = self.enricher.enrich(collected)
            if enriched is None:
                builder = collected.as_builder()
                builder.set_row(None)
                for err in boundary_errors:
                    builder.add_error_item(err)
                yield builder.build()
                continue
            builder = enriched.as_builder()
            for err in boundary_errors:
                builder.add_error_item(err)
            yield builder.build()


class MatchStage:
    """
    Назначение/ответственность:
        Стадия match (enriched -> matched).
    """

    def __init__(self, matcher: DeduplicationTransform, catalog: ErrorCatalog) -> None:
        self.matcher = matcher
        self.catalog = catalog

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult[MatchedRow]]:
        for enriched in source:
            boundary_errors: list = []
            matched: TransformResult[MatchedRow] | None = None
            with diagnostic_boundary(
                stage=DiagnosticStage.MATCH,
                catalog=self.catalog,
                sink=boundary_errors,
                record_ref=enriched.row_ref,
            ):
                matched = self.matcher.match(enriched)
            if matched is None:
                builder = enriched.as_builder()
                builder.set_row(None)
                for err in boundary_errors:
                    builder.add_error_item(err)
                yield builder.build()
                continue
            if boundary_errors:
                builder = matched.as_builder()
                for err in boundary_errors:
                    builder.add_error_item(err)
                yield builder.build()
                continue
            yield matched


class ResolveStage:
    """
    Назначение/ответственность:
        Стадия resolve (matched -> resolved).
    """

    def __init__(self, resolver: LookupEnricher, catalog: ErrorCatalog) -> None:
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
                errors=tuple(errors),
                warnings=tuple(warnings),
            )


def _build_target_id_map(matched_rows: list[TransformResult[MatchedRow]]) -> dict[str, str]:
    """
    Назначение:
        Построить карту identity->target_id для resolve-стадии.

    Алгоритм:
        - Для matched берём _id из existing.
        - Иначе используем target_id из matched-строки.
    """
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
    resolver: LookupEnricher,
    dataset: str | None,
) -> dict[str, dict[str, list[str]]]:
    """
    Назначение:
        Подготовить индекс батча для resolve-правил.
    """
    if dataset is None:
        return {}
    return resolver.build_batch_index(matched_rows, dataset)
