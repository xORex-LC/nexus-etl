"""
Назначение:
    Стадии конвейера data transform (map/normalize/enrich/match/resolve).

    Содержит:
    - Контракты стадий: StageContract (canonical, DEC-004) и TransformStageProcessor (legacy)
    - Описание engine-протоколов: MatchProcessor, ResolveProcessor
    - Оркестратор: PipelineOrchestrator с двухуровневыми lifecycle hooks и batching (DEC-004)
    - Конкретные реализации: MapStage, NormalizeStage, EnrichStage, MatchStage, ResolveStage

Граница ответственности:
    - Owns: stage contracts, stage implementations, orchestration logic, batching
    - Does NOT: load DSL config, handle I/O, build execution context (StageExecutionContext)
    - Does NOT: implement command-specific orchestration (reporting, micro-batching policies)

Миграция:
    StagePipeline и TransformStageProcessor — backward-compat; удаляются в Этапе 5 DEC-004.
    PipelineOrchestrator — целевая реализация; BatchConfig — целевой механизм батчинга.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Protocol, Sequence, TypeVar, runtime_checkable

from connector.domain.diagnostics.boundary import diagnostic_boundary
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.models import DiagnosticStage
from connector.domain.ports.transform.sources import SourceMapper
from connector.domain.transform.enrich import EnricherEngine
from connector.domain.transform.normalize import NormalizerEngine
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.matcher.match_models import (
    MatchedRow,
    MatchDecisionStatus,
    resolve_decision_status,
)

T = TypeVar("T")
T_in = TypeVar("T_in")
T_out = TypeVar("T_out")


# ════════════════════════════════════════════════════════════════════════════════
# Engine protocols — минимальные контракты для match/resolve движков.
# Не являются StageContract: это internal protocols движков, а не стадий pipeline.
# ════════════════════════════════════════════════════════════════════════════════

class MatchProcessor(Protocol):
    """
    Назначение:
        Минимальный контракт match-движка для MatchStage/MatchUseCase.
    """

    def match(self, enriched: TransformResult) -> TransformResult[MatchedRow]:
        ...

    def match_with_source_dedup(self, enriched: TransformResult) -> TransformResult[MatchedRow]:
        ...

    def reset_source_dedup(self) -> None:
        ...

    def bind_runtime_scope(self, scope: str | None) -> None:
        ...


class ResolveProcessor(Protocol):
    """
    Назначение:
        Минимальный контракт resolve-движка для ResolveStage/ResolveUseCase.
    """

    def build_batch_index(self, matched_rows: list, dataset: str) -> dict[str, dict[str, list[str]]]:
        ...

    def resolve(
        self,
        matched: MatchedRow,
        *,
        target_id_map: dict[str, str],
        meta: dict | None = None,
        batch_index: dict[str, dict[str, list[str]]] | None = None,
    ):
        ...


# ════════════════════════════════════════════════════════════════════════════════
# Stage Contract — канонический контракт стадий (TRANSFORM-DEC-004, Этап 1)
# ════════════════════════════════════════════════════════════════════════════════

@runtime_checkable
class StageContract(Protocol[T_in, T_out]):
    """
    Назначение:
        Единый контракт стадии конвейера. Покрывает все 5 стадий (map → resolve).

    Граница ответственности:
        - Предоставляет run(source) → stream: единственный публичный интерфейс стадии.
        - stage_name: строковый идентификатор стадии для hooks и диагностики.
        - НЕ включает close() или __exit__ — cleanup через python generator protocol.

    Инварианты:
        - run() принимает Iterable[T_in] и возвращает Iterable[T_out]; никаких extra kwargs.
        - stage_name — неизменяемое строковое свойство.
        - Structural subtyping (Protocol): реализация без явного наследования.
        - @runtime_checkable: isinstance(stage, StageContract) проверяет наличие
          атрибутов stage_name и run (generic params не проверяются).
    """

    @property
    def stage_name(self) -> str:
        """Имя стадии для hooks и диагностики."""
        ...

    def run(self, source: Iterable[T_in]) -> Iterable[T_out]:
        """Обработать поток записей. Генераторная реализация допускается."""
        ...


# Type alias для type-erased представления (оркестратор, реестр, DI-контейнер).
# Стадии сохраняют Generic типизацию в delivery layer; после сборки работают как AnyStageContract.
AnyStageContract = StageContract[Any, Any]


@dataclass(frozen=True)
class BatchConfig:
    """
    Назначение:
        Конфигурация батчинга для BatchableStage.

    Инварианты:
        - batch_size >= 1 (enforcement на уровне вызывающего кода).
        - key=None — fixed-size батчи без шардирования.
        - key не None — шардирование по ключу с ограничением batch_size на корзину.
    """

    batch_size: int = 1000
    key: Callable[..., Any] | None = None


class BatchableStage(StageContract[T_in, T_out], Protocol[T_in, T_out]):
    """
    Назначение:
        Расширение StageContract для стадий, требующих буферизации входного потока.

    Граница:
        - Ненулевой batch_config сигнализирует PipelineOrchestrator о необходимости
          буферизовать поток перед передачей стадии.
        - Стадия с batch_config=None считается streaming functor (не требует батчинга).
    """

    @property
    def batch_config(self) -> BatchConfig | None:
        """Конфигурация батчинга. None — стадия не требует буферизации."""
        ...


# ════════════════════════════════════════════════════════════════════════════════
# Pipeline Orchestrator (TRANSFORM-DEC-004, Этап 1)
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class PipelineHooks:
    """
    Назначение:
        Двухуровневые lifecycle hooks для observability pipeline.

    Граница ответственности:
        - assembly hook (on_stage_bind): eager, вызывается при сборке цепочки в run().
        - execution hooks: lazy-aware, вызываются при реальном потреблении потока.
        - НЕ владеет логикой — чистые callbacks для внешней observability (логирование, метрики).

    Инварианты:
        - Все execution hooks — «data-flow events»: срабатывают только если стадия
          получила хотя бы один элемент (start_time guard в _monitored).
        - on_stage_complete: ТОЛЬКО при полном consumption (StopIteration). При пустом стриме
          НЕ вызывается (start_time остаётся None).
        - on_stage_error: НЕ вызывается если исключение возникло до первого pull.
        - Нет callbacks (None) — PipelineOrchestrator работает без ошибок.
    """

    # ── Assembly hook (eager) ─────────────────────────────────────────────
    on_stage_bind: Callable[[str], None] | None = None
    """Вызывается при регистрации стадии в цепочке — до потока данных."""

    # ── Execution hooks (lazy-aware) ──────────────────────────────────────
    on_stage_start: Callable[[str], None] | None = None
    """Вызывается при первом pull из stage output — реальный старт обработки.
    В lazy chain: срабатывает при первом pull с конца цепочки."""

    on_stage_complete: Callable[[str, float, dict | None], None] | None = None
    """Вызывается при полном исчерпании stage output (StopIteration).
    Аргументы: stage_name, duration_ms, stats ({"items": N})."""

    on_stage_error: Callable[[str, Exception, float], None] | None = None
    """Вызывается при исключении в стадии после первого pull.
    Аргументы: stage_name, exc, duration_ms."""

    on_stage_abort: Callable[[str, float], None] | None = None
    """Вызывается при GeneratorExit до полного consumption (partial consumption).
    Аргументы: stage_name, duration_ms."""


class PipelineOrchestrator:
    """
    Назначение:
        Управляет выполнением цепочки стадий от source до target.

    Граница ответственности:
        - Chains stages: передаёт output одной стадии как input следующей.
        - Batching: буферизует поток для стадий с ненулевым batch_config.
        - Lifecycle hooks: двухуровневые (assembly + execution) через PipelineHooks.
        - НЕ знает о DatasetSpec, StageExecutionContext, command-specific логике.
        - НЕ знает о типах TransformResult.row (работает type-erased).

    Инварианты:
        - Стадии выполняются строго в порядке, переданном в __init__.
        - _monitored() НИКОГДА не подавляет исключения — только re-raises после хука.
        - on_stage_complete вызывается ТОЛЬКО при полном consumption.
        - on_stage_start/error/abort/complete: только если start_time установлен.
    """

    def __init__(
        self,
        stages: Sequence[AnyStageContract],
        *,
        hooks: PipelineHooks | None = None,
    ) -> None:
        self._stages = list(stages)
        self._hooks = hooks or PipelineHooks()

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        """
        Назначение:
            Запустить цепочку стадий; вернуть lazy-итератор на выход последней стадии.

        Алгоритм:
            1. Для каждой стадии вызывает on_stage_bind (eager, во время run()).
            2. Оборачивает stage.run(current) в _monitored() (lazy execution).
            3. Стадии с BatchConfig получают буферизованный поток.
            4. Возвращает lazy итератор — данные не потребляются до первого pull caller'ом.
        """
        current: Iterable[TransformResult] = source
        for stage in self._stages:
            if self._hooks.on_stage_bind:
                self._hooks.on_stage_bind(stage.stage_name)  # eager: assembly time
            current = self._execute_stage(stage, current)
        return current

    def _execute_stage(
        self,
        stage: AnyStageContract,
        source: Iterable[TransformResult],
    ) -> Iterable[TransformResult]:
        batch_config: BatchConfig | None = getattr(stage, "batch_config", None)
        if batch_config is not None:
            raw = self._run_batched_stage(stage, source, batch_config)
        else:
            raw = stage.run(source)
        return self._monitored(stage, raw)

    def _run_batched_stage(
        self,
        stage: AnyStageContract,
        source: Iterable[TransformResult],
        batch_config: BatchConfig,
    ) -> Iterable[TransformResult]:
        """
        Назначение:
            Буферизовать source в батчи согласно batch_config, прогнать через stage.run().
        """
        batches = _buffer_into_batches(
            source,
            batch_size=batch_config.batch_size,
            key=batch_config.key,
        )
        for batch in batches:
            yield from stage.run(batch)

    def _monitored(
        self,
        stage: AnyStageContract,
        stream: Iterable[TransformResult],
    ) -> Iterator[TransformResult]:
        """
        Назначение:
            Monitoring wrapper: превращает eager-вызовы в lazy-aware события.

        Алгоритм:
            - start_time устанавливается при первом pull; до этого хуки не вызываются.
            - on_stage_complete: только при полном consumption (StopIteration).
              При пустом стриме (start_time is None) — НЕ вызывается.
            - on_stage_abort: при GeneratorExit (partial consumption); re-raises.
            - on_stage_error: при Exception ПОСЛЕ первого pull; re-raises.
              Если исключение до первого pull (start_time is None): только re-raises,
              on_stage_error НЕ вызывается (это control-flow события setup-фазы).
        """
        start_time: float | None = None
        items_count = 0
        try:
            for item in stream:
                if start_time is None:
                    start_time = time.monotonic()
                    if self._hooks.on_stage_start:
                        self._hooks.on_stage_start(stage.stage_name)
                items_count += 1
                yield item
            # Natural exhaustion — on_stage_complete только если стадия стартовала
            if start_time is not None and self._hooks.on_stage_complete:
                ms = (time.monotonic() - start_time) * 1000
                self._hooks.on_stage_complete(stage.stage_name, ms, {"items": items_count})
        except GeneratorExit:
            if start_time is not None and self._hooks.on_stage_abort:
                ms = (time.monotonic() - start_time) * 1000
                self._hooks.on_stage_abort(stage.stage_name, ms)
            raise
        except Exception as exc:
            if start_time is not None and self._hooks.on_stage_error:
                ms = (time.monotonic() - start_time) * 1000
                self._hooks.on_stage_error(stage.stage_name, exc, ms)
            raise


# ════════════════════════════════════════════════════════════════════════════════
# LEGACY — backward-compat; удаляются в Этапе 5 DEC-004
# ════════════════════════════════════════════════════════════════════════════════

class TransformStageProcessor(Protocol):
    """
    Назначение:
        Контракт процессора одной стадии трансформации.

    .. deprecated::
        Используйте StageContract[T_in, T_out] (TRANSFORM-DEC-004).
        Будет удалён в Этапе 5 миграции.
    """

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        ...


class StagePipeline:
    """
    Назначение:
        Последовательный запуск набора стадий (map/normalize/enrich/match/resolve).

    .. deprecated::
        Используйте PipelineOrchestrator (TRANSFORM-DEC-004).
        Будет удалён в Этапе 5 миграции.
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
    Назначение:
        Декоратор-маркер для стадий, которым нужен батч входных данных.

    .. deprecated::
        Используйте BatchableStage Protocol и BatchConfig (TRANSFORM-DEC-004).
        Будет удалён в Этапе 5 миграции.
    """

    def decorator(stage_cls):
        stage_cls._is_batched = True
        stage_cls._batch_size = batch_size
        stage_cls._batch_key = key
        return stage_cls

    return decorator


# ════════════════════════════════════════════════════════════════════════════════
# Batching helpers (shared between StagePipeline legacy и PipelineOrchestrator)
# ════════════════════════════════════════════════════════════════════════════════

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


# ════════════════════════════════════════════════════════════════════════════════
# Stage implementations
# ════════════════════════════════════════════════════════════════════════════════

class MapStage:
    """
    Назначение:
        Стадия map (source → mapped). Реализует StageContract[TransformResult, TransformResult].

    Инварианты:
        - Stateless functor: нет состояния на уровне instance между вызовами run().
        - Record-level ошибки маппинга → catalog; stage не бросает исключений per-record.
    """

    stage_name: str = "map"

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
    Назначение:
        Стадия normalize (mapped → normalized). Реализует StageContract.

    Инварианты:
        - Stateless functor.
        - Record-level ошибки нормализации → catalog.
    """

    stage_name: str = "normalize"

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
    Назначение:
        Стадия enrich (normalized → enriched). Реализует StageContract.

    Инварианты:
        - Stateless functor (per-record lookup через injected enricher).
        - Record-level enrich miss → catalog; stage не прерывает поток.
        - Допускает батчинг (BatchableStage): batch_config задаётся при создании стадии.
    """

    stage_name: str = "enrich"

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
    Назначение:
        Стадия match (enriched → matched). Реализует StageContract.

    Инварианты:
        - Stateless functor (match runtime инъецируется через matcher).
        - Record-level match miss → catalog.
        - UseCase ответственен за scope binding и micro-batching.
    """

    stage_name: str = "match"

    def __init__(self, matcher: MatchProcessor, catalog: ErrorCatalog) -> None:
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
                matched = self.matcher.match_with_source_dedup(enriched)
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
    Назначение:
        Стадия resolve (matched → resolved). Реализует StageContract.

    Инварианты:
        - Stateless functor (resolver инъецируется).
        - UseCase ответственен за транзакции и drain_expired.
        - dataset kwarg в run() deprecated: dataset перейдёт в context.metadata в Этапе 2.
    """

    stage_name: str = "resolve"

    def __init__(self, resolver: ResolveProcessor, catalog: ErrorCatalog) -> None:
        self.resolver = resolver
        self.catalog = catalog

    def run(
        self,
        source: Iterable[TransformResult[MatchedRow]],
        *,
        dataset: str | None = None,
    ) -> Iterable[TransformResult]:
        """
        Назначение:
            Обработать батч matched-записей: построить batch_index, разрешить каждую запись.

        Note:
            dataset kwarg deprecated — в Этапе 2 DEC-004 dataset перейдёт в
            StageExecutionContext.metadata.dataset_name. Вызов без dataset уже допустим
            (batch_index будет пустым, что корректно для run без context).
        """
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


# ════════════════════════════════════════════════════════════════════════════════
# Module-level helpers
# ════════════════════════════════════════════════════════════════════════════════

def _build_target_id_map(matched_rows: list[TransformResult[MatchedRow]]) -> dict[str, str]:
    """
    Назначение:
        Построить карту identity→target_id для resolve-стадии.

    Алгоритм:
        - Для matched берём _id из existing.
        - Иначе используем target_id из matched-строки.
    """
    mapping: dict[str, str] = {}
    for item in matched_rows:
        row = item.row
        if row is None:
            continue
        if resolve_decision_status(row) == MatchDecisionStatus.MATCHED and row.existing:
            target_id = row.existing.get("_id")
        else:
            target_id = row.target_id
        if target_id:
            mapping[row.identity.primary_value] = str(target_id)
    return mapping


def _build_batch_index(
    matched_rows: list[TransformResult[MatchedRow]],
    resolver: ResolveProcessor,
    dataset: str | None,
) -> dict[str, dict[str, list[str]]]:
    """
    Назначение:
        Подготовить индекс батча для resolve-правил.
    """
    if dataset is None:
        return {}
    return resolver.build_batch_index(matched_rows, dataset)
