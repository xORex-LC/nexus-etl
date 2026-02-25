# MATCHER-DEC-002: Интернализация micro-batch исполнения и scope cleanup в DI-сервисы — MatchStage как полноправный участник PipelineOrchestrator

> **Статус**: Принято
> **Дата принятия**: 2026-02-25
> **Решает проблему**: [MATCHER-PROBLEM-002](./MATCHER-PROBLEM-002-match-stage-external-batch-orchestration.md)
> **Зависит от**: [MATCHER-DEC-001](./MATCHER-DEC-001-externalize-dedup-state-to-di-service.md) — `ISourceDedupStore`, `PipelineRunContext`; [RESOLVER-DEC-001](../resolver/RESOLVER-DEC-001-externalize-mechanics-to-di-services.md) — шаблон DI-сервисов
> **Разблокирует**: [TRANSFORM-DEC-007](../transform/TRANSFORM-DEC-007-declarative-pipeline-checkpoints.md) — полноценный `PIPELINE_CHECKPOINTS.PLAN = [MAP..MATCH..RESOLVE]`
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

`MatchStage` не является полноправным участником `PipelineOrchestrator`: её исполнение требует внешнего обрамления через `open_match_runtime` (создаёт `MatchUseCase`, гарантирует `clear_runtime_scope()`) и `iter_matched_ok` (адаптер батч-итерации). В результате `CheckpointName.PLAN` декларирует `[MAP..MATCH..RESOLVE]`, но MATCH остаётся специальным case в `PlanningPipeline` и command handlers.

Это симметричная проблема с [RESOLVER-PROBLEM-001](../resolver/RESOLVER-PROBLEM-001-resolve-stage-mixed-responsibilities.md), решённой в [RESOLVER-DEC-001](../resolver/RESOLVER-DEC-001-externalize-mechanics-to-di-services.md): `ResolveStage` получил чистый `run(source)` за счёт выноса механик в DI-сервисы. Применяем тот же паттерн.

---

## 🎯 Решение

Две внешние механики Match выносятся в именованные DI-сервисы:

1. **`IMatchBatchSettings`** — `batch_size` и `flush_interval_ms` для micro-batch исполнения. Переезжают из per-command параметров `MatchUseCase` в DI Singleton.
2. **`IMatchScopeService`** — `clear_scope()` для очистки runtime scope после завершения стадии. Вызывается через `PipelineHooks.on_stage_complete` для стадии `"match"` — аналогично `IPendingExpiryService.sweep()` для `"resolve"`.

`MatchStage.run(source)` принимает полный поток и выполняет micro-batching внутри через `IMatchBatchSettings`. `open_match_runtime`, `MatchRuntime`, `iter_matched_ok` — удаляются.

Результат: `PIPELINE_CHECKPOINTS.PLAN = [MAP, NORMALIZE, ENRICH, MATCH, RESOLVE_CONTEXT, RESOLVE]` — все стадии uniform StageContract, `PipelineOrchestrator` обрабатывает единообразно.

---

## 🏗️ Архитектурное решение

### Компонент 1: IMatchBatchSettings

```python
# connector/domain/transform/matcher/ports.py (расширение)

class IMatchBatchSettings(Protocol):
    """Параметры micro-batch исполнения match-стадии.
    Singleton per pipeline run. Инжектируется в MatchStage — стадия не
    знает о per-command настройках; всё через DI."""

    batch_size: int
    flush_interval_ms: int
```

Реализация: `MatchBatchSettings` — dataclass, создаётся в PipelineContainer из `app_settings.matching_runtime`:

```python
# connector/domain/transform/matcher/match_deps.py (новый файл)

@dataclass(frozen=True)
class MatchBatchSettings:
    batch_size: int = 500
    flush_interval_ms: int = 500
```

### Компонент 2: IMatchScopeService

```python
# connector/domain/transform/matcher/ports.py (расширение)

class IMatchScopeService(Protocol):
    """Lifecycle cleanup match runtime scope после завершения стадии.
    Вызывается вне горячего пути — через PipelineHooks.on_stage_complete."""

    def clear_scope(self) -> None:
        """Очищает временный runtime scope текущего прогона.
        Аналог: IPendingExpiryService.sweep() для resolve-стадии."""
        ...
```

Реализация: `MatchScopeService` — держит `run_id` и `gateway` (MatchRuntimePort), вызывает `gateway.clear_runtime_scope(f"run:{run_id}")`.

### Компонент 3: MatchStage.run() — self-contained с micro-batching

После изменений `MatchStage.run()` принимает полный поток и управляет батчами внутри:

```python
class MatchStage:
    def __init__(
        self,
        engine: MatchProcessor,
        catalog: ErrorCatalog,
        batch_settings: IMatchBatchSettings,   # ← новый: DI Singleton
    ) -> None: ...

    # StageContract: run(source) → Iterable, без внешних kwargs
    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult[MatchedRow]]:
        for batch in iter_micro_batches(
            source,
            batch_size=self._batch_settings.batch_size,
            flush_interval_ms=self._batch_settings.flush_interval_ms,
        ):
            for matched in self._process_batch(batch):
                yield matched

    def _process_batch(self, batch: Iterable) -> Iterable:
        # per-record match — как сейчас внутри MatchStage.run(batch)
        for row in batch:
            yield self._engine.match_with_source_dedup(row)
```

`MatchStage` теперь самодостаточна: принимает полный поток, сама делит на батчи по `IMatchBatchSettings`.

### Компонент 4: PlanningPipelineHooks — расширение match-хуком

`PlanningPipelineHooks` получает `IMatchScopeService` и строит единый `PipelineHooks` для обоих событий:

```python
class PlanningPipelineHooks:
    def __init__(
        self,
        pending_expiry: IPendingExpiryService,
        match_scope: IMatchScopeService,          # ← новый
    ) -> None: ...

    def plan_hooks(self) -> PipelineHooks:
        """Lifecycle hooks для полного PLAN pipeline (match + resolve стадии)."""

        def _on_stage_complete(stage_name: str, _duration_ms: float, _stats: dict | None) -> None:
            if stage_name == "match":
                self._match_scope.clear_scope()      # ← cleanup scope, как в open_match_runtime.finally
            elif stage_name == "resolve":
                self._pending_expiry.sweep()          # ← как сейчас

        return PipelineHooks(on_stage_complete=_on_stage_complete)
```

### Компонент 5: PipelineContainer — wiring

```python
class PipelineContainer(containers.DeclarativeContainer):

    # Batch settings для MatchStage
    match_batch_settings = providers.Singleton(
        MatchBatchSettings,
        batch_size=providers.Factory(lambda s: s.matching_runtime.match_batch_size, s=app_settings),
        flush_interval_ms=providers.Factory(lambda s: s.matching_runtime.match_flush_interval_ms, s=app_settings),
    )

    # Scope cleanup сервис для match-стадии
    match_scope = providers.Singleton(
        MatchScopeService,
        gateway=providers.Factory(lambda roles: roles.planning_runtime, roles=cache_roles),
        run_id=run_id,
    )

    # plan_hooks: включает оба хука (match scope + resolve expiry)
    plan_hooks = providers.Singleton(
        PlanningPipelineHooks,
        pending_expiry=pending_expiry,
        match_scope=match_scope,               # ← новый
    )

    # Единые lifecycle hooks для всего PLAN pipeline
    resolve_stage_hooks = providers.Singleton(  # переименовать в plan_pipeline_hooks
        lambda hooks: hooks.plan_hooks(),
        hooks=plan_hooks,
    )

    # MatchStage: batch_settings injected, деdup_store уже есть (MATCHER-DEC-001)
    match_stage = providers.Factory(
        _create_stage,
        factory=stage_factory,
        stage_type="match",
        spec=...,
        ctx=planning_context,
        options=match_options,
        resolve_rules=compiled_resolve_rules,
        include_deleted=include_deleted,
        dedup_store=_dedup_store,
        batch_settings=match_batch_settings,   # ← новый
    )
```

### Поток исполнения после MATCHER-DEC-002

```
PlanningPipeline.open():
    self._dedup_store.reset()
    composer.compose(CheckpointName.PLAN, hooks=self._plan_hooks).run(extractor.run())
    ↓
PipelineOrchestrator (PLAN = [MAP, NORMALIZE, ENRICH, MATCH, RESOLVE_CONTEXT, RESOLVE]):
    map_stage.run(source)
    → normalize_stage.run(mapped)
    → enrich_stage.run(normalized)
    → match_stage.run(enriched)         ← micro-batching внутри + dedup через ISourceDedupStore
        on_stage_complete("match") → match_scope.clear_scope()
    → resolve_context_stage.run(matched) ← batch_index строится здесь
    → resolve_stage.run(contextualized)  ← per-record через batch_index
        on_stage_complete("resolve") → pending_expiry.sweep()
```

`open_match_runtime`, `iter_matched_ok`, `MatchRuntime` dataclass — удаляются.

---

## 🗑️ Удаление open_match_runtime

`connector/delivery/cli/planning_match_runtime.py` удаляется полностью:

| Удаляемый элемент | Заменяется на |
|-------------------|---------------|
| `open_match_runtime` context manager | `PipelineHooks.on_stage_complete("match")` → `match_scope.clear_scope()` |
| `MatchRuntime` dataclass | Не нужен: `MatchStage` и `MatchUseCase` не нуждаются в Runtime-обёртке |
| `iter_matched_ok` | Не нужен: `match_stage.run(source)` — прямой streaming |
| `MatchUseCase(batch_size=...)` per-command wiring | `IMatchBatchSettings` DI Singleton |

`MatchUseCase.iter_matched()` — удаляется как метод (заменяется `match_stage.run(source)` напрямую).
`MatchUseCase.run()` — остаётся для команды `match` (включает reporting), упрощается: больше не принимает `batch_size`/`flush_interval_ms`.

---

## 🔄 Переходное состояние: match команда до DEC-007

До реализации [TRANSFORM-DEC-007](../transform/TRANSFORM-DEC-007-declarative-pipeline-checkpoints.md) команда `match` **не использует `PipelineOrchestrator`** — она вызывает `MatchUseCase.run()` напрямую. `PipelineHooks.on_stage_complete` не стреляет, поэтому `IMatchScopeService.clear_scope()` нужно вызывать явно.

### Переходный паттерн: `match.py` после DEC-002, до DEC-007

```python
# connector/delivery/commands/match.py
#
# TRANSITIONAL (DEC-002 → DEC-007):
#   match_scope.clear_scope() вызывается явно в finally, так как PipelineOrchestrator
#   здесь не используется — hooks не срабатывают.
#   После реализации DEC-007: убрать try/finally, добавить hooks в compose():
#       composer.compose(CheckpointName.MATCH, hooks=plan_pipeline_hooks)
#   IMatchScopeService.clear_scope() автоматически вызовется через on_stage_complete("match").
#
match_scope = pipeline.match_scope()
try:
    return match_usecase.run(
        enriched_rows,
        match_stage,
        dataset=dataset_name,
        report=report,
    )
finally:
    match_scope.clear_scope()
```

### Docstring для `MatchUseCase.run()` в переходный период

```python
def run(self, enriched_source, match_stage, dataset, report) -> CommandResult:
    """
    ...

    Lifecycle-замечание (переходное, DEC-002):
        Caller отвечает за вызов IMatchScopeService.clear_scope() после завершения run().
        В match.py это обёрнуто в try/finally.
        После DEC-007: scope cleanup переезжает в PipelineHooks.on_stage_complete("match");
        явный вызов из caller упраздняется.
    """
```

### Инвариант переходного периода

После DEC-002 `open_match_runtime` **удалён**. Для `match` команды `clear_scope()` вызывается вручную в handler'е через `try/finally`. Для `resolve` / `import_plan` команд `clear_scope()` вызывается через `PipelineHooks` (в этих сценариях уже используется `PipelineOrchestrator`). После DEC-007 все сценарии переходят на единый hook-механизм.

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ `MatchStage.run(source)` — StageContract без внешних зависимостей: принимает поток, отдаёт поток
- ✅ `PIPELINE_CHECKPOINTS.PLAN` полностью декларативен — MATCH как обычная стадия, не special case
- ✅ `PlanningPipeline.open()` сводится к `dedup_store.reset()` + `composer.compose(PLAN, hooks=...).run(source)` — не знает о внутренностях match
- ✅ Дублирование `open_match_runtime + iter_matched_ok` в двух handler'ах устраняется
- ✅ `batch_size`/`flush_interval_ms` — единая точка конфигурации через `IMatchBatchSettings` DI Singleton
- ✅ Паттерн симметричен RESOLVER-DEC-001: тот же подход, те же типы провайдеров, те же инварианты

**Недостатки (компромиссы)**:
- ⚠️ `MatchScopeService` захватывает `run_id` при materialisation — если один `PipelineContainer` переиспользуется для нескольких прогонов без пересоздания (чего сейчас нет), `run_id` окажется устаревшим. В текущей модели (один CLI-вызов = один контейнер) это не проблема.
- ⚠️ `MatchBatchSettings` — новый тип в DI. Минимален (dataclass из двух полей), но требует обновления при добавлении новых batch-параметров.

**Альтернативы, которые отклонили**:
- ❌ **MATCH как lifecycle-граница (Вариант A)**: `compose(ENRICH)` + `open_match_runtime` + `compose(RESOLVE_TAIL)`. `PlanningPipeline` всё ещё знает о match-инфраструктуре; `PIPELINE_CHECKPOINTS` не достигает полноты; дублирование паттерна остаётся.
- ❌ **BatchableStage абстракция**: вводит специальный StageContract для батчевых стадий — нарушает uniform-контракт, который является целью TRANSFORM-DEC-007.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform/matcher/ports.py` | Добавить: `IMatchBatchSettings`, `IMatchScopeService` |
| `connector/domain/transform/matcher/match_deps.py` | Новый: `MatchBatchSettings` dataclass; `MatchScopeService` |
| `connector/domain/transform/stages/stages.py` | `MatchStage.__init__`: добавить `batch_settings: IMatchBatchSettings`; `MatchStage.run()`: интернализировать `iter_micro_batches` |
| `connector/delivery/cli/containers.py` | `PipelineContainer`: добавить `match_batch_settings`, `match_scope`; расширить `plan_hooks`; передать `batch_settings` в `match_stage` |
| `connector/delivery/pipelines/planning_pipeline_hooks.py` | `PlanningPipelineHooks.__init__`: добавить `match_scope: IMatchScopeService`; `resolve_stage_hooks()` → `plan_hooks()`: обрабатывать и "match" и "resolve" |
| `connector/delivery/cli/planning_match_runtime.py` | Удалить полностью |
| `connector/usecases/match_usecase.py` | Удалить `iter_matched()` и `_iter_matched()`; `run()` упростить: не принимает `batch_size`/`flush_interval_ms` |

### Целевая структура модулей

```
connector/domain/transform/
└── matcher/
    ├── match_deps.py             # НОВЫЙ: MatchBatchSettings, MatchScopeService
    │                             #        (по аналогии с resolver/resolve_deps.py)
    ├── match_core.py             # БЕЗ ИЗМЕНЕНИЙ (уже чистый после MATCHER-DEC-001)
    ├── match_engine.py           # МИНИМАЛЬНО: пробросить batch_settings в MatchStage
    └── ports.py                  # РАСШИРЕН: IMatchBatchSettings, IMatchScopeService

connector/domain/transform/
└── stages/
    └── stages.py                 # ИЗМЕНЁН: MatchStage — добавить batch_settings,
                                  #          run() принимает полный source + iter_micro_batches

connector/delivery/
├── cli/
│   ├── containers.py             # ИЗМЕНЁН: добавить match_batch_settings, match_scope,
│   │                             #          расширить plan_hooks wiring
│   └── planning_match_runtime.py # УДАЛЁН полностью
├── pipelines/
│   ├── planning_pipeline.py      # УПРОЩЁН: убрать open_match_runtime/iter_matched_ok;
│   │                             #          open() → dedup_store.reset() + composer.compose(PLAN)
│   └── planning_pipeline_hooks.py # РАСШИРЕН: match_scope в __init__,
│                                  #           plan_hooks() вместо resolve_stage_hooks()
└── commands/
    ├── resolve.py                # УПРОЩЁН: убрать open_match_runtime/iter_matched_ok
    └── match.py                  # МИНИМАЛЬНО: MatchUseCase.run() без batch_size/flush
```

### Инварианты

1. `MatchStage.run(source)` — принимает неограниченный lazy poток; делит на батчи самостоятельно через `IMatchBatchSettings`
2. `IMatchScopeService.clear_scope()` вызывается строго через `PipelineHooks.on_stage_complete("match")` — не в hot path
3. `MatchScopeService` инициализируется с `run_id` текущего прогона при materialisation из PipelineContainer
4. `MatchBatchSettings` — Singleton в PipelineContainer; не создаётся в command handler'ах
5. `open_match_runtime` не существует — `PlanningPipeline` и command handlers не вызывают его
6. `PIPELINE_CHECKPOINTS.PLAN` включает MATCH как обычную стадию — без исключений в `PipelineComposer`

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `MatchStage` | Расширение | Принять `batch_settings: IMatchBatchSettings`; `run()` → `iter_micro_batches` внутри |
| `MatchUseCase` | Упрощение | Удалить `iter_matched()`, `_iter_matched()`; `run()` без batch параметров |
| `open_match_runtime` / `iter_matched_ok` | Удаление | Полное удаление `planning_match_runtime.py` |
| `PlanningPipeline` | Упрощение | `open()` → `dedup_store.reset()` + `composer.compose(PLAN, hooks=plan_hooks).run(extractor.run())` |
| `PlanningPipelineHooks` | Расширение | `match_scope` в конструктор; `plan_hooks()` заменяет `resolve_stage_hooks()` |
| `PipelineContainer` | Расширение | Добавить `match_batch_settings`, `match_scope`; расширить `plan_hooks`; `match_stage` + `batch_settings` |
| `resolve.py` command | Упрощение | Убрать `open_match_runtime + iter_matched_ok` |
| Тесты `MatchStage` | Обновление | Добавить `batch_settings` в фабрики; убрать `open_match_runtime` из test setup |

---

## 🧪 Тест-стратегия

### Существующие тесты — что меняется

| Файл | Изменение | Причина |
|------|-----------|---------|
| `tests/unit/planning/test_matcher_*.py` | `_build_matcher()` / тест-фабрики: добавить `batch_settings=MatchBatchSettings()` | `MatchStage` принимает `batch_settings` |
| Тесты с `open_match_runtime` | Убрать wrapper, заменить прямым `match_stage.run(source)` | `open_match_runtime` удалён |
| Тесты `MatchUseCase` | Убрать `batch_size`/`flush_interval_ms` из конструктора | Параметры перешли в `MatchBatchSettings` |

### Новые тесты

#### Unit — доменные сервисы

| Файл | Что тестирует |
|------|--------------|
| `tests/unit/transform/matcher/test_match_scope_service.py` | `clear_scope()` делегирует к `gateway.clear_runtime_scope(f"run:{run_id}")`; вызывается ровно один раз при триггере |
| `tests/unit/transform/matcher/test_match_batch_settings.py` | Корректные дефолты; wiring из `app_settings.matching_runtime` |

#### Unit — изменённая стадия

| Файл | Что тестирует |
|------|--------------|
| `tests/unit/transform/test_match_stage.py` | `run(source)` — lazy generator; micro-batching происходит внутри (mock `iter_micro_batches` с счётчиком); `StageContract` — `stage_name`, сигнатура `run()` |

#### Архитектурные

| Тест | Инвариант |
|------|-----------|
| `test_match_scope_not_called_in_hot_path()` | `IMatchScopeService.clear_scope()` не вызывается из `MatchCore.match()` — только из hooks |
| `test_plan_hooks_fires_match_scope_on_match_complete()` | `PlanningPipelineHooks.plan_hooks()` → `on_stage_complete("match")` → `match_scope.clear_scope()` |
| `test_match_stage_satisfies_stage_contract()` | `MatchStage` — структурный подтип `StageContract` |

---

## 🔗 Связанные документы

- [MATCHER-PROBLEM-002](./MATCHER-PROBLEM-002-match-stage-external-batch-orchestration.md) — решаемая проблема
- [MATCHER-DEC-001](./MATCHER-DEC-001-externalize-dedup-state-to-di-service.md) — предыдущее решение; `ISourceDedupStore` и `PipelineRunContext` уже реализованы
- [RESOLVER-DEC-001](../resolver/RESOLVER-DEC-001-externalize-mechanics-to-di-services.md) — шаблон решения: вынесение механик в DI-сервисы; `ResolveStage` как аналог цели
- [TRANSFORM-DEC-007](../transform/TRANSFORM-DEC-007-declarative-pipeline-checkpoints.md) — разблокируемое решение; `PIPELINE_CHECKPOINTS.PLAN` становится полностью декларативным

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-25 | Решение сформулировано как симметричное к RESOLVER-DEC-001 в ходе анализа MATCHER-PROBLEM-002 |
| 2026-02-25 | Принято; разблокирует TRANSFORM-DEC-007 для полного `PIPELINE_CHECKPOINTS.PLAN = [MAP..RESOLVE]` |
| 2026-02-25 | Зафиксирован переходный паттерн для `match` команды: явный `try/finally` с `match_scope.clear_scope()` до реализации DEC-007; после DEC-007 cleanup переезжает в `on_stage_complete` hook |
