# TRANSFORM-DEC-006: Pipeline segments в PipelineContainer — контейнер владеет композицией и lifecycle

> **Статус**: Закрыто
> **Дата принятия**: 2026-02-23
> **Решает проблему**: [TRANSFORM-PROBLEM-006](./TRANSFORM-PROBLEM-006-pipeline-composition-ownership.md)
> **Зависит от**: [PLANNER-DEC-001](../planner/PLANNER-DEC-001-pending-replay-at-resolve-boundary.md) (prerequisite)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

После TRANSFORM-DEC-004 `PipelineContainer` умеет создавать отдельные стадии (lazy DI), но не владеет их **композицией**. Знание о цепочке стадий для команды `import_plan` распределено между CLI и `ImportPlanService`. Lifecycle match-скоупа (`open_match_runtime`) живёт в `usecases/` — delivery-concern в wrong layer. Подробнее: [TRANSFORM-PROBLEM-006](./TRANSFORM-PROBLEM-006-pipeline-composition-ownership.md).

Prerequisite: [PLANNER-DEC-001](../planner/PLANNER-DEC-001-pending-replay-at-resolve-boundary.md) — pending replay должен быть перемещён в `ResolveUseCase.iter_resolved(pending_replay=...)` перед реализацией этого решения.

---

## 🎯 Решение

1. **`PipelineContainer` экспонирует `transform_segment`** — переименованный провайдер `transform_pipeline`, возвращает `PipelineOrchestrator([map, normalize, enrich])`. Все CLI-команды используют его вместо ручной сборки.

2. **`PipelineContainer` экспонирует `planning_pipeline`** — провайдер `providers.Factory(PlanningPipeline, ...)`. Класс `PlanningPipeline` в `connector/delivery/pipelines/planning_pipeline.py` инкапсулирует полный lifecycle конвейера import_plan: transform → match (с cleanup скоупа) → resolve (с pending replay). Метод `open(*, run_id, planning_runtime, report_items_limit)` — context manager, yields `Iterable[TransformResult[ResolvedRow]]`.

3. **`import_plan.py` handler напрямую строит план** через `PlanBuilder().build_from_stream(resolved_rows)` — `ImportPlanService` и `PlanUseCase` удалены в PLANNER-DEC-002; знание о стадиях и lifecycle инкапсулировано в `planning_pipeline()`.

4. **`planning_match_runtime.py` переносится в `connector/delivery/cli/`** как отдельный модуль — ответственность: lifecycle match-runtime (не растворяется в `containers.py`).

---

## 🏗️ Архитектурное решение

### Провайдер `transform_segment` и класс `PlanningPipeline`

```python
# connector/delivery/cli/containers.py

class PipelineContainer(DeclarativeContainer):
    ...

    # Провайдер (переименован из transform_pipeline):
    transform_segment = providers.Factory(
        build_transform_segment,   # переименована из build_transform_pipeline
        map_stage=map_stage,
        normalize_stage=normalize_stage,
        enrich_stage=enrich_stage,
    )

    # Провайдер для PlanningPipeline (lifecycle-aware класс):
    planning_pipeline = providers.Factory(
        PlanningPipeline,
        transform_segment=transform_segment,
        match_stage=match_stage,
        resolve_stage=resolve_stage,
        row_source=row_source,
        catalog=catalog,
        dataset_spec=dataset_spec,
        app_settings=app_settings,
    )
```

```python
# connector/delivery/pipelines/planning_pipeline.py

class PlanningPipeline:
    """
    Lifecycle-aware конвейер для команды import_plan.
    Инкапсулирует: transform → match (scope cleanup) → resolve (pending replay).
    Создаётся PipelineContainer.planning_pipeline Factory.
    В DEC-007: transform_segment заменяется на composer: PipelineComposer.
    """

    def __init__(
        self,
        transform_segment: PipelineOrchestrator,
        match_stage: MatchStage,
        resolve_stage: ResolveStage,
        row_source,
        catalog: ErrorCatalog,
        dataset_spec,
        app_settings: AppSettings,
    ) -> None:
        self._transform_segment = transform_segment
        self._match_stage = match_stage
        self._resolve_stage = resolve_stage
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
    ) -> Iterator[Iterable[TransformResult]]:
        """
        Yields: поток разрезолвленных строк для PlanBuilder.
        При выходе (в т.ч. при ошибке) гарантирует cleanup runtime scope.
        """
        app = self._app_settings
        dataset_name = self._dataset_spec.dataset_name

        extractor = Extractor(self._row_source, catalog=self._catalog)
        enriched = iter_ok(
            self._transform_segment.run(extractor.run()),
            should_skip=lambda item: item.row is None,
        )

        with open_match_runtime(
            run_id=run_id,
            match_stage=self._match_stage,
            match_runtime=planning_runtime,
            report_items_limit=report_items_limit,
            include_matched_items=False,
            batch_size=app.matching_runtime.match_batch_size,
            flush_interval_ms=app.matching_runtime.match_flush_interval_ms,
        ) as match_runtime:
            matched = iter_matched_ok(runtime=match_runtime, enriched_source=enriched)
            resolve_usecase = ResolveUseCase(
                report_items_limit=report_items_limit,
                include_resolved_items=False,
                batch_size=app.matching_runtime.resolve_batch_size,
                flush_interval_ms=app.matching_runtime.resolve_flush_interval_ms,
            )
            resolved = iter_ok(resolve_usecase.iter_resolved(
                matched_source=matched,
                resolve_stage=self._resolve_stage,
                pending_replay=planning_runtime,   # ← PLANNER-DEC-001
                dataset=dataset_name,
            ))
            yield resolved
```

### `import_plan.py` command handler (целевой вид)

```python
# connector/delivery/commands/import_plan.py

plan_pipeline = pipeline.planning_pipeline()
planning_runtime = ctx.container.cache.roles().planning_runtime
with plan_pipeline.open(
    run_id=run_id,
    planning_runtime=planning_runtime,
    report_items_limit=report_items_limit_value,
) as resolved_rows:
    plan_result = PlanBuilder().build_from_stream(resolved_rows)
```

### Поток данных

```
import_plan command
    ├─ pipeline.planning_pipeline()    →  PlanningPipeline (Factory)
    ├─ cache.roles().planning_runtime  →  planning_runtime
    └─ plan_pipeline.open(run_id, planning_runtime, report_items_limit=N)
         ├─ transform_segment.run(extractor)     →  enriched_rows
         ├─ open_match_runtime(match_stage, ...)  →  match lifecycle
         │       └─ iter_matched_ok(enriched)     →  matched_rows
         └─ ResolveUseCase.iter_resolved(
                matched_source=matched_rows,
                pending_replay=planning_runtime,   ← pending_codec (PLANNER-DEC-001)
                dataset=dataset_name,
            )                                      →  resolved_rows
                 yield resolved_rows  ←────────────────────────────────┐
                                                                        │
    └─ PlanBuilder().build_from_stream(resolved_rows)                   │
         └─ plan_result → write_plan_file()                             │
                                                                        │
    (на выходе из open(): match_runtime.clear_runtime_scope())          ┘
```

### Расположение `open_match_runtime` после рефакторинга

`planning_match_runtime.py` переносится в `connector/delivery/cli/planning_match_runtime.py` как **отдельный модуль** (не вливается в `containers.py` или другие существующие файлы — у него своя ответственность: lifecycle match-runtime). Публичный re-export из `connector/usecases/planning_match_runtime.py` удаляется.

---

## 🔧 Уточнения к реализации

### `transform_segment` — переименованный провайдер, не новый метод

Существующий `transform_pipeline = providers.Factory(build_transform_pipeline, ...)` уже делает именно то, что нужно (`PipelineOrchestrator([map, normalize, enrich])`). Добавлять отдельный обычный метод нет смысла.

**Решение**: переименовать провайдер `transform_pipeline` → `transform_segment` и функцию `build_transform_pipeline` → `build_transform_segment` в `pipeline_registry.py`. Провайдер остаётся провайдером.

Провайдер `full_pipeline` (и `build_full_pipeline`) — удалить как мёртвые: ни одна команда их не использует, а lifecycle-aware аналог — `planning_pipeline()`.

### `PlanningPipeline` — класс, не метод контейнера

`PlanningPipeline` — отдельный класс в `connector/delivery/pipelines/planning_pipeline.py`, предоставляемый через `providers.Factory`. Это решение принято для подготовки к DEC-007 (см. ниже).

**Разделение конструктор / `open()`**:

Конструктор (через Factory, статические зависимости):
- `transform_segment`, `match_stage`, `resolve_stage` — стадии из `PipelineContainer`
- `row_source`, `catalog`, `dataset_spec`, `app_settings` — контекст датасета/прогона

`open()` параметры (runtime, передаются из handler-а):
- `run_id: str` — идентификатор прогона
- `planning_runtime: MatchRuntimePort` — получается в handler-е через `ctx.container.cache.roles().planning_runtime`
- `report_items_limit: int` — opts-overridable, вычисляется в handler-е

Разделение позволяет DEC-007 оставить `open()` и handler **без изменений** — меняется только конструктор (`transform_segment` → `composer: PipelineComposer`).

Расширенный вариант (вынести `report_items_limit` в overridable провайдер) отложен как техдолг.

### Статус `ImportPlanService`

`ImportPlanService` и `PlanUseCase` удалены в PLANNER-DEC-002. `import_plan.py` handler использует `PlanBuilder().build_from_stream(resolved_rows)` напрямую. Таблица ключевых файлов обновлена соответственно.

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ `PipelineContainer` / `PlanningPipeline` — единственное место, знающее состав конвейера для каждой команды (Single Source of Truth в рамках DEC-006; в DEC-007 переходит в `PIPELINE_CHECKPOINTS`)
- ✅ OCP восстановлен: добавление новой стадии требует изменения только контейнера (`transform_segment` или `planning_pipeline()`), не CLI и не use-cases
- ✅ `import_plan.py` handler сводится к двум строкам: `planning_pipeline(...)` + `PlanBuilder().build_from_stream()` — не знает о стадиях и lifecycle
- ✅ Match lifecycle (`open_match_runtime`) перемещается в delivery слой — туда, где живут lifecycle-concerns
- ✅ CLI-команда `import_plan.py` становится симметричной другим командам: overrides → context manager → build result

**Недостатки (компромиссы)**:
- ⚠️ `PipelineContainer` предоставляет `transform_segment` (переходный провайдер, удаляется в DEC-007). Небольшой технический долг с явным сроком
- ⚠️ `normalize`/`enrich` usecases до DEC-007 всё ещё строят оркестраторы внутри себя — осознанный и документированный временный gap

**Альтернативы, которые отклонили**:
- ❌ **`ImportPlanPipeline` в `usecases/`**: знание о составе стадий всё равно лежит вне Composition Root; не решает OCP
- ❌ **Статус-кво + PLANNER-DEC-001**: pending десериализация уходит, но coupling `ImportPlanService` ↔ `MatchStage`/`ResolveStage` сохраняется

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/delivery/pipelines/__init__.py` | Создать: пустой пакет |
| `connector/delivery/pipelines/planning_pipeline.py` | Создать: класс `PlanningPipeline` с `open()` |
| `connector/delivery/cli/containers.py` | Переименовать `transform_pipeline` → `transform_segment`; удалить `full_pipeline`; добавить `planning_pipeline = providers.Factory(PlanningPipeline, ...)` |
| `connector/delivery/cli/pipeline_registry.py` | Переименовать `build_transform_pipeline` → `build_transform_segment`; удалить `build_full_pipeline` |
| `connector/delivery/cli/planning_match_runtime.py` | Создать: перенести из `connector/usecases/planning_match_runtime.py` |
| `connector/usecases/planning_match_runtime.py` | Удалить (перенесён в delivery/cli/) |
| `connector/delivery/commands/import_plan.py` | Использовать `pipeline.planning_pipeline().open(run_id, planning_runtime, ...)` + `PlanBuilder().build_from_stream()` |
| `connector/delivery/commands/match.py` | Использовать `pipeline.transform_segment()` вместо ручной сборки |
| `connector/delivery/commands/resolve.py` | Использовать `pipeline.transform_segment()` вместо ручной сборки |

### Preconditions для вызова `planning_pipeline()`

`PlanningPipeline` создаётся через Factory внутри override-контекста. Следующие провайдеры должны быть override-нуты **до вызова `pipeline.planning_pipeline()`**:

| Provider | Обязателен | Источник |
|----------|------------|---------|
| `dataset_spec` | ✅ | `build_dataset_spec()` |
| `run_id` | ✅ | `ctx.run_id` |
| `csv_has_header` | ✅ | opts / app_settings |
| `catalog` | ✅ | `build_diagnostics_catalog()` |
| `include_deleted` | ✅ | opts / app_settings |
| `secret_store` | по условию | vault write service, если vault enabled |

Нарушение контракта (вызов без override-ов) даёт runtime failure от `providers.Dependency` — не compile-time ошибку. Это известный компромисс dependency-injector.

### Lifetime-контракт `resolved_rows`

`PlanningPipeline.open()` возвращает **lazy iterable**, валидный только внутри блока `with`:

```python
with plan_pipeline.open(...) as resolved_rows:
    plan_result = PlanBuilder().build_from_stream(resolved_rows)  # ✅
# Здесь clear_runtime_scope() уже вызван — resolved_rows невалиден
```

**Invariant**: `resolved_rows` **должен быть полностью консьюмирован внутри `with plan_pipeline.open(...)`**. Сохранять итератор и консьюмировать его снаружи — ошибка.

### Инварианты

1. **`PlanningPipeline.open()`** — гарантирует `clear_runtime_scope()` при любом выходе (в т.ч. при `GeneratorExit`, исключении в consumer-е)
2. **`transform_segment`** — провайдер (не метод); используется командами match и resolve вместо ручной сборки стадий
3. **`import_plan.py`** — не импортирует `MatchStage`, `ResolveStage`, `open_match_runtime`, `PipelineOrchestrator`; вся оркестрация внутри `PlanningPipeline`
4. **Prerequisite PLANNER-DEC-001** реализован (PLANNER-DEC-002 завершён)

### Скоуп: команды вне DEC-006

`mapping`, `normalize`, `enrich` передают стадии поштучно в свои usecases, которые строят `PipelineOrchestrator` внутри (`enrich_usecase.py`, `normalize_usecase.py`). Это та же категория нарушения — знание о составе в неправильном слое — но разрешается в **[TRANSFORM-DEC-007](./TRANSFORM-DEC-007-declarative-pipeline-checkpoints.md)**: `PipelineComposer.compose("normalize")`/`compose("enrich")` заменяют ручную сборку, одновременно меняя сигнатуры use-cases на приём `PipelineOrchestrator`.

DEC-006 покрывает три команды с ручной сборкой **в handler-е**: `match`, `resolve`, `import_plan`.

### Обновление docstring `containers.py`

После DEC-006 `PipelineContainer` остаётся pure DI — теперь предоставляет и stage-провайдеры (`map_stage`, `normalize_stage`, ...), и `planning_pipeline` Factory (который создаёт `PlanningPipeline`). Lifecycle-логика живёт в `PlanningPipeline`, не в контейнере.

При реализации обновить модульный docstring `pipeline_registry.py` (убрать упоминание `build_full_pipeline`). В `containers.py` docstring достаточно отразить появление нового провайдера `planning_pipeline`.

---

### Эволюция к DEC-007

DEC-006 — сознательный промежуточный шаг:

| Артефакт | DEC-006 | DEC-007 |
|----------|---------|---------|
| `PipelineContainer.transform_segment` | Провайдер `PipelineOrchestrator([map, normalize, enrich])` | **Удалён** — заменён `PipelineComposer.compose("enrich")` |
| `PlanningPipeline.__init__` | `transform_segment: PipelineOrchestrator` | `composer: PipelineComposer` — **единственное изменение** |
| `PlanningPipeline.open()` | без изменений | без изменений |
| Handler `import_plan.py` | без изменений | без изменений |
| `NormalizeUseCase`, `EnrichUseCase` | получают отдельные стадии (без изменений) | получают `PipelineOrchestrator` от handler-а |
| `PipelineContainer` | `transform_segment` + `planning_pipeline` | остаётся pure DI (только stage-провайдеры) |

DEC-007 не требует структурной реструктуризации — только замена одного параметра конструктора `PlanningPipeline` и добавление `PipelineComposer` в `AppContainer`.

---

## 🧪 Валидация решения

### Архитектурные guard-тесты (`tests/architecture/test_planner_layer_boundaries.py`)

**`test_planning_match_runtime_moved_to_delivery`** — `planning_match_runtime.py` перенесён, отсутствует в `usecases/`:
```python
def test_planning_match_runtime_moved_to_delivery() -> None:
    path = USECASES_ROOT / "planning_match_runtime.py"
    assert not path.exists(), (
        "planning_match_runtime.py должен быть в connector/delivery/cli/, не в usecases/ (TRANSFORM-DEC-006)"
    )
```

**`test_import_plan_does_not_import_orchestrator_symbols`** — `import_plan.py` не знает о стадиях и match lifecycle:
```python
def test_import_plan_does_not_import_orchestrator_symbols() -> None:
    path = REPO_ROOT / "connector" / "delivery" / "commands" / "import_plan.py"
    imports = _imports(path)
    forbidden = {
        "connector.domain.transform.stages.stages",
        "connector.usecases.planning_match_runtime",
        "connector.usecases.resolve_usecase",
    }
    violations = [m for m in imports if m in forbidden]
    assert violations == [], (
        "import_plan.py не должен знать о стадиях и match lifecycle (TRANSFORM-DEC-006):\n"
        + "\n".join(violations)
    )
```

### Интеграционные тесты wiring (`tests/integration/delivery/test_pipeline_container.py`, класс `TestStageWiring`)

**`test_transform_segment_wiring`** — новый провайдер `transform_segment` создаёт `PipelineOrchestrator`:
```python
def test_transform_segment_wiring(self):
    from connector.domain.transform.stages.stages import PipelineOrchestrator
    container = _make_pipeline_container()
    _apply_command_overrides(container)
    assert isinstance(container.transform_segment(), PipelineOrchestrator)
```

**`test_planning_pipeline_wiring`** — провайдер `planning_pipeline` (Factory) создаёт `PlanningPipeline`:
```python
def test_planning_pipeline_wiring(self):
    from connector.delivery.pipelines.planning_pipeline import PlanningPipeline
    container = _make_pipeline_container()
    _apply_command_overrides(container)
    assert isinstance(container.planning_pipeline(), PlanningPipeline)
```

### Техдолг (после DEC-007)

Unit-тест `test_planning_pipeline_cleanup_on_exception` (гарантия `clear_runtime_scope()` при исключении в consumer-е) — отложен. Cleanup гарантируется `try/finally` в `open_match_runtime`; текущее покрытие через e2e `test_plan_pipeline.py` достаточно для DEC-006.

**Проверка**:
- `grep -r "planning_match_runtime" connector/usecases/` — пусто (перенесён в delivery/cli/)
- `grep -r "PipelineOrchestrator\|open_match_runtime\|ResolveUseCase" connector/delivery/commands/import_plan.py` — пусто
- `grep -r "map_stage\|normalize_stage\|enrich_stage" connector/delivery/commands/match.py connector/delivery/commands/resolve.py` — пусто

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `connector/delivery/pipelines/planning_pipeline.py` | Новый файл | Создать `PlanningPipeline` с `open()` |
| `PipelineContainer` | Расширение | Переименовать `transform_pipeline` → `transform_segment`; удалить `full_pipeline`; добавить `planning_pipeline = providers.Factory(PlanningPipeline, ...)` |
| `pipeline_registry.py` | Упрощение | Переименовать `build_transform_pipeline` → `build_transform_segment`; удалить `build_full_pipeline` |
| `import_plan.py` | Упрощение | Использовать `pipeline.planning_pipeline().open(run_id, planning_runtime, ...)`; убрать ручную сборку стадий |
| `match.py`, `resolve.py` | Упрощение | Использовать `pipeline.transform_segment()` вместо ручной сборки |
| `planning_match_runtime.py` | Перемещение | `usecases/` → `delivery/cli/` (отдельный модуль) |
| `ImportPlanService`, `PlanUseCase` | Нет изменений | Удалены ранее в PLANNER-DEC-002 |
| `ResolveUseCase` | Нет изменений | Уже получает `pending_replay` после PLANNER-DEC-001 |

---

## 🔗 Связанные документы

- [TRANSFORM-PROBLEM-006](./TRANSFORM-PROBLEM-006-pipeline-composition-ownership.md) — решаемая проблема
- [TRANSFORM-DEC-004](./TRANSFORM-DEC-004-modular-pipeline-scoped-execution-context.md) — базовая архитектура, которую расширяем
- [PLANNER-DEC-001](../planner/PLANNER-DEC-001-pending-replay-at-resolve-boundary.md) — prerequisite (pending replay в `ResolveUseCase`)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-23 | Решение принято |
