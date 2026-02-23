# TRANSFORM-PROBLEM-006: Владение композицией конвейера разделено между CLI, ImportPlanService и planning_match_runtime

> **Статус**: Открыта / Решена в [TRANSFORM-DEC-006](./TRANSFORM-DEC-006-pipeline-segments-in-container.md)
> **Дата создания**: 2026-02-23
> **Затронутые компоненты**: `ImportPlanService`, `import_plan.py`, `planning_match_runtime.py`, `PipelineContainer`

---

## 📋 Контекст

[TRANSFORM-DEC-004](./TRANSFORM-DEC-004-modular-pipeline-scoped-execution-context.md) ввёл `PipelineContainer` как единую точку DI-сборки стадий и `PipelineOrchestrator` как механизм последовательного chain-инга. Контейнер умеет создавать отдельные стадии (map, normalize, enrich, match, resolve), но **не знает, как их комбинировать в конвейер для конкретной команды**. Это знание распределено вручную — между CLI-командами и use-case сервисами.

---

## ⚠️ Проблема

`import_plan` — единственная команда, требующая полного пятистадийного конвейера с lifecycle-управлением match-скоупа. Знание о составе этого конвейера разделено между тремя местами:

**Нарушение 1 — CLI вручную разбивает конвейер на части:**

```python
# import_plan.py
service.run(
    transform_pipeline=PipelineOrchestrator([
        pipeline.map_stage(),
        pipeline.normalize_stage(),
        pipeline.enrich_stage(),
    ]),
    match_stage=pipeline.match_stage(),      # отдельно
    resolve_stage=pipeline.resolve_stage(),   # отдельно
)
```

CLI знает, что map/normalize/enrich объединяются в оркестратор, а match и resolve — отдельные сущности. Добавление новой стадии (например, `validation_stage` между enrich и match) требует изменения CLI-команды.

**Нарушение 2 — `ImportPlanService` знает порядок стадий и управляет match lifecycle:**

```python
# import_plan_service.py
def run(self, ..., match_stage: MatchStage, resolve_stage: ResolveStage, ...):
    ...
    with open_match_runtime(match_stage=match_stage, ...):  # lifecycle стадии в use-case
        matched_rows = iter_matched_ok(...)
        ...
        resolve_usecase.iter_resolved(matched_rows, resolve_stage, ...)
```

`ImportPlanService` — application-level оркестратор — вынужден знать о конкретных типах `MatchStage` и `ResolveStage`, об их порядке (match → resolve), и управлять lifecycle match-скоупа (`open_match_runtime` с `clear_runtime_scope`). Это delivery-level concerns.

**Нарушение 3 — `planning_match_runtime.py` живёт в `usecases/`:**

`open_match_runtime()` и `iter_matched_ok()` — lifecycle-helpers для конкретной CLI-команды, но расположены в `connector/usecases/`. Lifecycle match-скоупа (создание, cleanup) является concern-ом DI/delivery слоя, а не use-case слоя.

---

## 🔍 Симптомы

- `ImportPlanService.run()` принимает `match_stage: MatchStage, resolve_stage: ResolveStage` — use-case зависит от конкретных типов delivery-layer стадий
- `import_plan.py` содержит ручную сборку `PipelineOrchestrator([map, normalize, enrich])` — знание о составе сегмента конвейера в CLI
- `connector/usecases/planning_match_runtime.py` содержит lifecycle-код (`clear_runtime_scope`) специфичный для одной команды — в слое use-cases
- 5 разных команд имеют 5 разных ручных сборок пайплайна (3 команды — только часть стадий, 2 команды — match+resolve, 1 команда — полный конвейер)

---

## 📊 Масштаб проблемы

- **Частота**: Структурная (существует всегда)
- **Критичность**: Средняя (функционально работает; нарушает OCP и Single Source of Truth для chain-описания)
- **Затронуто**: `import_plan` команда; при добавлении новых стадий — все 5 CLI-команд и соответствующие use-cases

---

## 🚫 Почему это проблема?

- **OCP нарушение**: добавление стадии (или изменение их порядка) требует изменения `ImportPlanService`, `import_plan.py` и потенциально `planning_match_runtime.py` — всё это не являются owners цепочки
- **SRP нарушение**: `ImportPlanService` одновременно управляет lifecycle инфраструктуры (match scope) и строит план — это два разных concern-а
- **Inconsistent ownership**: `PipelineContainer` отвечает за создание каждой стадии по отдельности, но не за их композицию — нет единой точки истины для "как конвейер собирается для данной команды"
- **Инверсия зависимостей**: use-case знает о delivery-level типах (`MatchStage`, `ResolveStage`) напрямую, а не через абстракцию

---

## 💡 Возможные решения (обсуждение)

### Вариант 1: Pipeline segments в `PipelineContainer`

- **Идея**: Контейнер экспонирует именованные сегменты пайплайна — `transform_segment()` → `PipelineOrchestrator([map, normalize, enrich])` и `planning_pipeline(...)` → context manager, возвращающий `Iterable[TransformResult[ResolvedRow]]` со встроенным lifecycle
- **Плюсы**: Единая точка истины о составе конвейера; CLI и use-cases не знают о стадиях; OCP восстановлен
- **Минусы**: `PipelineContainer` усложняется (содержит не только провайдеры стадий, но и segment-провайдеры); требует PLANNER-DEC-001 как prerequisite

### Вариант 2: Выделить `ImportPlanPipeline` как отдельный класс

- **Идея**: Новый класс `ImportPlanPipeline` в `usecases/` инкапсулирует полную оркестрацию конвейера для import_plan; `ImportPlanService` просто вызывает его
- **Плюсы**: Не меняет `PipelineContainer`; явная ответственность
- **Минусы**: Знание о составе стадий всё равно лежит в use-case слое, не в delivery/DI слое; не решает OCP проблему при добавлении стадий

### Вариант 3: Статус-кво + точечные улучшения

- **Идея**: Реализовать только PLANNER-DEC-001 (убрать pending десериализацию); не трогать оркестрацию стадий
- **Плюсы**: Минимальные изменения
- **Минусы**: Coupling `ImportPlanService` ↔ `MatchStage`/`ResolveStage` сохраняется; `planning_match_runtime.py` в wrong layer остаётся

---

## 🔗 Связанные документы

- [TRANSFORM-DEC-004](./TRANSFORM-DEC-004-modular-pipeline-scoped-execution-context.md) — ввёл `PipelineContainer` и `PipelineOrchestrator`
- [TRANSFORM-DEC-006](./TRANSFORM-DEC-006-pipeline-segments-in-container.md) — принятое решение
- [PLANNER-PROBLEM-001](../planner/PLANNER-PROBLEM-001-pending-replay-infra-leak.md) — смежная проблема (pending replay в планнере)
- [PLANNER-DEC-001](../planner/PLANNER-DEC-001-pending-replay-at-resolve-boundary.md) — prerequisite для DEC-006
- `connector/usecases/import_plan_service.py` — основной затронутый файл
- `connector/usecases/planning_match_runtime.py` — misplaced lifecycle helper

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-23 | Проблема обнаружена при анализе `ImportPlanService` после TRANSFORM-DEC-004 Stage 5 |
| 2026-02-23 | Решение принято в TRANSFORM-DEC-006 |
