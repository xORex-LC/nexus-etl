"""
Назначение:
    Lifecycle-aware конвейер для команды import_plan.

    Инкапсулирует полный цикл планирования:
      transform (map → normalize → enrich)
      → match (с очисткой runtime scope через IMatchScopeService)
      → resolve_context (буферизация + batch_index)
      → resolve (с pending replay из PLANNER-DEC-001).

    Создаётся через PipelineContainer.planning_pipeline (providers.Factory).
    Handler import_plan.py получает экземпляр и вызывает open() — не знает о
    стадиях, lifecycle match-runtime и деталях оркестрации.

Граница ответственности:
    - Owns: lifecycle match-scope (clear через IMatchScopeService в finally),
      сборку enriched/matched/contextualized/resolved потоков,
      вызов dedup_store.reset() перед каждым прогоном,
      передачу pending_replay и resolve lifecycle hooks в ResolveUseCase,
      очистку buffered expired pending после завершения open().
    - Does NOT: знать о vault, secrets, plan serialization, CLI-opts.
    - Does NOT: управлять lifecycle инфраструктурных ресурсов (engines, gateway) —
      это зона PipelineContainer / CacheContainer.

Эволюция:
    DEC-007: единственное изменение — transform_segment: PipelineOrchestrator
    заменяется на composer: PipelineComposer; open() и handler остаются без изменений.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable, Iterator

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.cache.roles import MatchRuntimePort
from connector.domain.transform.core.extractor import Extractor
from connector.domain.transform.core.iterators import iter_ok
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.matcher.ports import IMatchScopeService, ISourceDedupStore
from connector.domain.transform.resolver.ports import IPendingExpiryService
from connector.domain.transform.stages.stages import (
    MatchStage,
    PipelineOrchestrator,
    PipelineHooks,
    ResolveContextStage,
    ResolveStage,
)
from connector.usecases.resolve_usecase import ResolveUseCase


class PlanningPipeline:
    """
    Назначение:
        Lifecycle-aware конвейер для команды import_plan.
        Инкапсулирует: transform → match (scope cleanup) → resolve (pending replay).
        Создаётся PipelineContainer.planning_pipeline Factory.

    Инварианты:
        - open() гарантирует match_scope.clear_scope() при любом выходе
          (в т.ч. GeneratorExit, исключение в consumer-е).
        - Итератор resolved_rows валиден только внутри блока `with open(...)`.
          Консьюмировать снаружи — ошибка.
        - Expired pending из housekeeping sweep не репортятся здесь и дренируются
          в finally (репортинг — ответственность ResolveUseCase.run/resolve command).

    Эволюция (DEC-007):
        transform_segment: PipelineOrchestrator → composer: PipelineComposer.
        open() и handler import_plan.py не меняются.
    """

    def __init__(
        self,
        transform_segment: PipelineOrchestrator,
        match_stage: MatchStage,
        match_scope: IMatchScopeService,
        resolve_context_stage: ResolveContextStage,
        resolve_stage: ResolveStage,
        resolve_stage_hooks: PipelineHooks,
        pending_expiry: IPendingExpiryService,
        dedup_store: ISourceDedupStore,
        row_source: Any,
        catalog: ErrorCatalog,
        dataset_spec: Any,
        app_settings: Any,
    ) -> None:
        self._transform_segment = transform_segment
        self._match_stage = match_stage
        self._match_scope = match_scope
        self._resolve_context_stage = resolve_context_stage
        self._resolve_stage = resolve_stage
        self._resolve_stage_hooks = resolve_stage_hooks
        self._pending_expiry = pending_expiry
        self._dedup_store = dedup_store
        self._row_source = row_source
        self._catalog = catalog
        self._dataset_spec = dataset_spec
        self._app_settings = app_settings

    @contextmanager
    def open(
        self,
        *,
        run_id: str,
        planning_runtime: MatchRuntimePort,
        report_items_limit: int,
    ) -> Iterator[Iterable[TransformResult[Any]]]:
        """
        Назначение:
            Открыть конвейер планирования и передать поток разрезолвленных строк.

        Контракт:
            - Yields lazy iterable[TransformResult] — валиден только внутри with-блока.
            - При выходе (включая исключение в consumer-е) гарантированно вызывает
              match_scope.clear_scope() через finally.
            - planning_runtime должен быть открыт до вызова (получается из cache.roles()).
        """
        self._dedup_store.reset()

        app = self._app_settings
        dataset_name = self._dataset_spec.dataset_name

        extractor = Extractor(self._row_source, catalog=self._catalog)
        enriched = iter_ok(
            self._transform_segment.run(extractor.run()),
            should_skip=lambda item: item.row is None,
        )

        try:
            matched = iter_ok(
                self._match_stage.run(enriched),
                should_skip=lambda r: r.row is None,
            )
            # ResolveContextStage буферизует весь поток matched, строит batch_index,
            # и передаёт записи без изменений. get() в ResolveStage.run() уже корректен.
            contextualized = self._resolve_context_stage.run(matched)
            resolve_usecase = ResolveUseCase(
                report_items_limit=report_items_limit,
                include_resolved_items=False,
                batch_size=app.matching_runtime.resolve_batch_size,
                flush_interval_ms=app.matching_runtime.resolve_flush_interval_ms,
            )
            resolved = iter_ok(
                resolve_usecase.iter_resolved(
                    matched_source=contextualized,
                    resolve_stage=self._resolve_stage,
                    dataset=dataset_name,
                    pending_replay=planning_runtime,  # PLANNER-DEC-001
                    resolve_hooks=self._resolve_stage_hooks,
                )
            )
            try:
                yield resolved
            finally:
                # import_plan не репортит expired pending, но буфер sweep-сервиса
                # нужно очищать между вызовами/тестами того же PipelineContainer.
                self._pending_expiry.drain_expired()
        finally:
            self._match_scope.clear_scope()
