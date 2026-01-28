from __future__ import annotations

from typing import Generic, TypeVar

from connector.domain.transform.result import TransformResult
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
    ) -> None:
        self.mapper = mapper
        self.normalizer = normalizer
        self.enricher = enricher

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
        mapped = self.mapper.map(collected.record)
        if collected.meta:
            if mapped.meta:
                mapped.meta = {**collected.meta, **mapped.meta}
            else:
                mapped.meta = dict(collected.meta)
        mapped.errors = [*collected.errors, *mapped.errors]
        mapped.warnings = [*collected.warnings, *mapped.warnings]
        return mapped

    def normalize_only(self, collected: TransformResult[None]) -> TransformResult[N]:
        mapped = self.map_source(collected)
        if mapped.errors:
            return mapped  # type: ignore[return-value]
        return self.normalizer.normalize(mapped)

    def enrich(self, collected: TransformResult[None]) -> TransformResult[N]:
        normalized = self.normalize_only(collected)
        if normalized.errors:
            return normalized
        return self.enricher.enrich(normalized)
