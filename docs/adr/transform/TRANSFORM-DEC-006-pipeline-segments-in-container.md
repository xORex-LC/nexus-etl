# TRANSFORM-DEC-006: Pipeline segments в PipelineContainer — контейнер владеет композицией и lifecycle

> **Статус**: Открыто
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

1. **`PipelineContainer` экспонирует `transform_segment()`** — именованный сегмент конвейера `PipelineOrchestrator([map, normalize, enrich])`. Все CLI-команды используют его вместо ручной сборки.

2. **`PipelineContainer` экспонирует `planning_pipeline(...)`** — context manager, который инкапсулирует полный lifecycle конвейера import_plan: transform → match (с cleanup скоупа) → resolve (с pending replay). Возвращает `Iterable[TransformResult[ResolvedRow]]`.

3. **`ImportPlanService` получает только поток разрезолвленных строк** — больше не знает о `MatchStage`, `ResolveStage`, их порядке и lifecycle. Единственная ответственность: `iter_ok(resolved_rows)` → `PlanUseCase.run()` → `write_plan_file()`.

4. **`planning_match_runtime.py` переносится в delivery слой** — либо становится приватным хелпером внутри `containers.py`, либо удаляется после поглощения его логики в `planning_pipeline()`.

---

## 🏗️ Архитектурное решение

### Новые провайдеры в `PipelineContainer`

```python
# connector/delivery/cli/containers.py

class PipelineContainer(DeclarativeContainer):
    ...

    def transform_segment(self) -> PipelineOrchestrator:
        """
        Сегмент конвейера map → normalize → enrich.
        Используется всеми командами для прохода через первые три стадии.
        """
        return PipelineOrchestrator([
            self.map_stage(),
            self.normalize_stage(),
            self.enrich_stage(),
        ])

    @contextmanager
    def planning_pipeline(
        self,
        *,
        run_id: str,
        planning_runtime: PlanningRuntimePort,
        matching_runtime_settings: MatchingRuntimeSettings,
        report_items_limit: int,
        catalog: ErrorCatalog,
    ) -> Iterator[Iterable[TransformResult]]:
        """
        Полный конвейер для import_plan: transform → match → resolve.
        Управляет lifecycle match-скоупа.
        При выходе (в т.ч. при ошибке) гарантирует cleanup runtime scope.
        Возвращает поток разрезолвленных строк — input для PlanUseCase.
        """
        dataset = self.dataset_spec().dataset
        extractor = Extractor(self.row_source(), catalog=catalog)
        enriched = iter_ok(self.transform_segment().run(extractor.run()), ...)

        with open_match_runtime(
            run_id=run_id,
            match_stage=self.match_stage(),
            match_runtime=planning_runtime,
            report_items_limit=report_items_limit,
            ...
        ) as match_runtime:
            matched = iter_matched_ok(runtime=match_runtime, enriched_source=enriched)
            resolve_usecase = ResolveUseCase(...)
            resolved = resolve_usecase.iter_resolved(
                matched_source=matched,
                resolve_stage=self.resolve_stage(),
                pending_replay=planning_runtime,   # ← PLANNER-DEC-001
                dataset=dataset,
            )
            yield iter_ok(resolved)
```

### Упрощённый `ImportPlanService`

```python
# connector/usecases/import_plan_service.py

class ImportPlanService:
    """
    Строит JSON-план импорта из потока разрезолвленных строк.
    Не знает о стадиях конвейера, их порядке и lifecycle.
    """

    def run(
        self,
        *,
        resolved_rows: Iterable[TransformResult],
        dataset: str,
        run_id: str,
        include_deleted: bool,
        report_dir: str,
        logger,
    ) -> CommandResult:
        plan_result = PlanUseCase().run(resolved_row_source=resolved_rows)
        plan_path = write_plan_file(...)
        ...
```

### Упрощённый `import_plan.py` command handler

```python
# connector/delivery/commands/import_plan.py

with pipeline.planning_pipeline(
    run_id=run_id,
    planning_runtime=cache_roles.planning_runtime,
    matching_runtime_settings=settings.matching_runtime,
    report_items_limit=...,
    catalog=catalog,
) as resolved_rows:
    service = ImportPlanService()
    return service.run(
        resolved_rows=resolved_rows,
        dataset=dataset_name,
        run_id=run_id,
        include_deleted=include_deleted_value,
        report_dir=report_dir,
    )
```

### Поток данных

```
import_plan command
    └─ pipeline.planning_pipeline(run_id, planning_runtime, ...)  [PipelineContainer]
         ├─ transform_segment().run(extractor)    →  enriched_rows
         ├─ open_match_runtime(match_stage, ...)  →  match lifecycle
         │       └─ iter_matched_ok(enriched)     →  matched_rows
         └─ ResolveUseCase.iter_resolved(
                matched_source=matched_rows,
                pending_replay=planning_runtime,   ← pending_codec (PLANNER-DEC-001)
                dataset=dataset,
            )                                      →  resolved_rows
                 yield resolved_rows  ←────────────────────────────────┐
                                                                        │
    └─ ImportPlanService.run(resolved_rows=resolved_rows)               │
         └─ PlanUseCase.run(resolved_rows) → plan → write_plan_file()   │
                                                                        │
    (на выходе из context manager: match_runtime.clear_runtime_scope()) ┘
```

### Расположение `open_match_runtime` после рефакторинга

`planning_match_runtime.py` переносится в `connector/delivery/cli/` (или становится приватным модулем `_planning_pipeline.py` рядом с `containers.py`). Публичный re-export из `connector/usecases/planning_match_runtime.py` удаляется.

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ `PipelineContainer` — единственное место, знающее полный состав конвейера для каждой команды (Single Source of Truth)
- ✅ OCP восстановлен: добавление новой стадии требует изменения только контейнера (`transform_segment()` или `planning_pipeline()`), не CLI и не use-cases
- ✅ `ImportPlanService` становится чистым планнером: получает `Iterable[TransformResult[ResolvedRow]]`, строит план — никакого знания о стадиях
- ✅ Match lifecycle (`open_match_runtime`) перемещается в delivery слой — туда, где живут lifecycle-concerns
- ✅ CLI-команда `import_plan.py` становится симметричной другим командам: overrides → context manager → service call

**Недостатки (компромиссы)**:
- ⚠️ `PipelineContainer` берёт на себя больше ответственности (composition + lifecycle, не только DI). Компромисс оправдан: контейнер уже является Composition Root — именно здесь должно жить знание о сборке
- ⚠️ `planning_pipeline()` — context manager в контейнере нетипичен для `dependency-injector`. Можно реализовать как обычный метод (не провайдер), что вполне допустимо

**Альтернативы, которые отклонили**:
- ❌ **`ImportPlanPipeline` в `usecases/`**: знание о составе стадий всё равно лежит вне Composition Root; не решает OCP
- ❌ **Статус-кво + PLANNER-DEC-001**: pending десериализация уходит, но coupling `ImportPlanService` ↔ `MatchStage`/`ResolveStage` сохраняется

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/delivery/cli/containers.py` | Добавить `transform_segment()` и `planning_pipeline()` |
| `connector/delivery/commands/import_plan.py` | Использовать `pipeline.planning_pipeline(...)` вместо передачи стадий |
| `connector/delivery/commands/match.py` | Использовать `pipeline.transform_segment()` вместо ручной сборки |
| `connector/delivery/commands/resolve.py` | Использовать `pipeline.transform_segment()` вместо ручной сборки |
| `connector/usecases/import_plan_service.py` | Убрать `match_stage`, `resolve_stage`, `transform_pipeline`; получать `resolved_rows: Iterable` |
| `connector/usecases/planning_match_runtime.py` | Переместить в delivery слой или удалить (логика поглощается `planning_pipeline()`) |

### Инварианты

1. **`planning_pipeline()`** — гарантирует `clear_runtime_scope()` при любом выходе (в т.ч. при `GeneratorExit`, исключении в consumer-е)
2. **`ImportPlanService`** — не импортирует `MatchStage`, `ResolveStage`, `open_match_runtime`, `PipelineOrchestrator`
3. **`transform_segment()`** — используется всеми командами, требующими прохода через map/normalize/enrich; не дублируется
4. **Prerequisite PLANNER-DEC-001** должен быть реализован до начала работы над этим решением

---

## 🧪 Валидация решения

**Тесты**:
- ✅ `test_planning_pipeline_runs_full_chain` — transform → match → resolve end-to-end через `planning_pipeline()`
- ✅ `test_planning_pipeline_cleanup_on_exception` — `clear_runtime_scope()` вызывается даже при исключении в consumer-е
- ✅ `test_import_plan_service_receives_only_resolved_rows` — `ImportPlanService` не принимает стадии
- ✅ `test_transform_segment_returns_orchestrator` — `transform_segment()` возвращает корректный `PipelineOrchestrator`
- ✅ E2E: `test_e2e_import_plan_full_pipeline` — полный прогон через `planning_pipeline()`

**Проверка**:
- `ImportPlanService` не импортирует `MatchStage`, `ResolveStage`, `PipelineOrchestrator`, `open_match_runtime`
- `grep -r "planning_match_runtime" connector/usecases/` — пусто (перемещён в delivery)
- `grep -r "match_stage.*MatchStage\|resolve_stage.*ResolveStage" connector/usecases/` — пусто

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `PipelineContainer` | Расширение | Добавить `transform_segment()`, `planning_pipeline()` |
| `import_plan.py` | Упрощение | Использовать `planning_pipeline()`; убрать `match_stage`, `resolve_stage` из `service.run()` |
| `match.py`, `resolve.py` | Упрощение | Использовать `transform_segment()` вместо ручной сборки |
| `ImportPlanService` | Радикальное упрощение | Убрать всё о стадиях; только `PlanUseCase + write_plan_file` |
| `planning_match_runtime.py` | Перемещение | Delivery слой / удаление |
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
