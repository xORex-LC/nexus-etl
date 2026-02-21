# TRANSFORM-PROBLEM-004: Отсутствие модульной pipeline-архитектуры — нет единого контракта стадий, scoped context, stage factory и orchestrator

> **Статус**: Открыта — решение зафиксировано в [TRANSFORM-DEC-004](./TRANSFORM-DEC-004-modular-pipeline-scoped-execution-context.md)
> **Дата создания**: 2026-02-22
> **Затронутые компоненты**: `TransformStageProcessor`, `StagePipeline`, `DatasetSpec`, `PipelineContext`, `build_pipeline_context()`, `TransformProviderDeps`, `PlanningDependencies`, все command handlers

---

## 📋 Контекст

Transform-конвейер вырос из одного потока (map→normalize→enrich) до пяти стадий (+ match, resolve), двух deps-контейнеров (`TransformProviderDeps`, `PlanningDependencies`), трёх port-семейств (cache, vault, dictionaries) и шести CLI-команд. Архитектура формировалась органически: каждая новая capability добавлялась инкрементально без пересмотра общей модели.

Ранее были зафиксированы две локальные проблемы:

- [TRANSFORM-PROBLEM-002](./TRANSFORM-PROBLEM-002-transform-provider-deps-coupling.md) — flat deps без capability scoping (domain layer)
- [TRANSFORM-PROBLEM-003](./TRANSFORM-PROBLEM-003-monolithic-pipeline-factory-eager-coupling.md) — eager monolithic wiring (delivery layer)

Эти проблемы — **симптомы одного корневого дефицита**: отсутствия целостной pipeline-архитектуры, которая определяет единый контракт стадии, scoped execution context, stage factory и orchestrator.

---

## ⚠️ Проблема

Pipeline-система не имеет целостной архитектурной модели. Пять стадий трансформации (map, normalize, enrich, match, resolve) используют три разных подхода к получению зависимостей, два разных механизма оркестрации и не имеют единого execution context. Добавление каждой новой стадии или capability требует правки 5+ файлов и дублирования wiring-логики.

---

## 🔍 Симптомы

### Разрыв 1 — Отсутствие единого Stage Contract

`TransformStageProcessor` определяет `run(source) → stream`, но:

- **Match и Resolve никогда не помещаются в `StagePipeline`**. `StagePipeline` собирается только из map+normalize+enrich. Planning stages оркестрируются ad-hoc в каждом command handler.
- **`ResolveStage.run()` нарушает протокол**: принимает `run(source, *, dataset=None)` — extra kwarg, который не предусмотрен `TransformStageProcessor`. `ResolveStage` не может быть частью `StagePipeline` без хаков.
- **`MatchProcessor` / `ResolveProcessor` — отдельные протоколы** с методами `match()`, `resolve()`, `build_batch_index()`, не вписывающиеся в единый stage contract.
- **Batching — через monkey-patch декоратор**: `@batched()` навешивает `_is_batched`, `_batch_size` через `setattr`. `StagePipeline` проверяет `getattr(stage, "_is_batched", False)` — runtime duck-typing вместо контрактного объявления.

### Разрыв 2 — Отсутствие Execution Context

Каждая стадия получает зависимости по-своему:

| Стадия | Что получает | Как получает |
|--------|-------------|--------------|
| Map | `ErrorCatalog` | Конструктор Stage |
| Normalize | `ErrorCatalog` | Конструктор Stage |
| Enrich | `TransformProviderDeps` + `ErrorCatalog` + `dataset` + `run_id` | deps-контейнер + конструктор Engine |
| Match | `PlanningDependencies` + `ErrorCatalog` + `include_deleted` | Другой deps-контейнер + конструктор Engine |
| Resolve | `PlanningDependencies` + `ErrorCatalog` + `SinkSpec` | Ещё один путь + конструктор Engine |

Нет единого объекта, который передаётся стадии при запуске и содержит: метаданные pipeline (`run_id`, `dataset`, `trace_id`), scoped services, data schema (`SinkSpec`), diagnostics (`ErrorCatalog`).

### Разрыв 3 — `DatasetSpec` как god-protocol вместо Stage Factory

`DatasetSpec` содержит 15+ методов:
- `build_map_spec()`, `build_normalize_spec()`, `build_enrich_spec()`, `build_match_spec()`, `build_resolve_spec()`, `build_sink_spec()` — загрузка DSL
- `build_map_stage()`, `build_normalize_stage()`, `build_enrich_stage()`, `build_match_stage()`, `build_resolve_stage()` — сборка стадий
- `build_enrich_deps()`, `build_planning_deps()` — сборка зависимостей
- `build_transform_stages()`, `build_planning_stages()` — батч-сборка
- `build_record_source()`, `get_report_adapter()`, `get_apply_adapter()`, `get_diagnostic_catalog()` — остальное

Это минимум 4 ответственности в одном протоколе: DSL-загрузка, dependency assembly, stage construction, I/O adapters. Стадии не регистрируются динамически — все hardcoded.

### Разрыв 4 — Отсутствие Pipeline Orchestrator

- `StagePipeline` — наивный chain для 3 из 5 стадий.
- `build_pipeline_context()` — монолитный eager wiring, не оркестратор.
- Оркестрация match/resolve размазана по command handlers (`match.py`, `resolve.py`, `import_plan.py`) с дублированием.
- Нет lifecycle hooks (before/after stage), error recovery, observability на уровне pipeline.
- `open_match_runtime()` — ad-hoc lifecycle только для match.

### Разрыв 5 — Неконсистентный routing зависимостей

- **`ResolverSettings` передаётся двумя путями** в `match.py`: через `build_pipeline_context(resolver_settings=...)` → `PlanningDependencies` и отдельно через `build_planning_stages(settings=...)`.
- **`ErrorCatalog` дублируется**: передаётся и в Engine, и в Stage-обёртку.
- **`SinkSpec` маршрутизируется неконсистентно**: передаётся в конструктор Engine напрямую, но не каждая стадия его получает.
- **`ProviderGateway.with_defaults()`** hardcoded в `EnricherEngine.__init__()` вместо DI.

### Разрыв 6 — Зависимости стадий не декларируются

DSL YAML не содержит секции "этой стадии нужен cache" или "этой стадии нужен vault". Зависимости неявны — определяются тем, какие providers используются в enrich-правилах. Обнаружить, что стадии не хватает dependency, можно только при runtime (`AttributeError`). Нет механизма проверки "все capabilities доступны" до запуска pipeline.

### Разрыв 7 — I/O в domain layer

Методы `build_*_stage()` в `DatasetSpec` вызывают `load_*_build_options_for_dataset()`, который обращается к файловой системе (читает YAML). Domain-логика не должна делать I/O — это нарушение hexagonal boundaries.

---

## 📊 Масштаб проблемы

- **Частота**: Присутствует в каждом вызове каждой CLI-команды и при каждом добавлении capability/стадии
- **Критичность**: Высокая — не нарушает корректность прямо сейчас, но блокирует масштабирование: добавление новой стадии или capability = правка 5+ файлов, два источника правды для settings, дублирование wiring в 3 command handlers
- **Затронуто**: Все 5 стадий, все 6 CLI-команд, `DatasetSpec`, `PipelineContext`, `containers.py`, все будущие capabilities

---

## 🧪 Как воспроизвести

**Разрыв 1 (match/resolve вне pipeline):**
1. Открыть `connector/domain/transform/stages/stages.py`
2. `StagePipeline.__init__` принимает `Sequence[TransformStageProcessor]`
3. `ResolveStage.run()` имеет `*, dataset=None` — не соответствует `TransformStageProcessor.run(source)`
4. **Ожидаемый результат**: все 5 стадий могут быть частью одного pipeline
5. **Фактический результат**: только 3 стадии в `StagePipeline`; match/resolve — ad-hoc

**Разрыв 2 (нет execution context):**
1. Открыть `connector/domain/transform/enrich/enricher_engine.py` — получает `deps`, `secret_store`, `dataset`, `run_id` как отдельные параметры
2. Открыть `connector/domain/transform/matcher/match_engine.py` — получает `cache_gateway` напрямую
3. **Ожидаемый результат**: единый context-объект со scoped services
4. **Фактический результат**: каждый engine имеет свой набор конструкторных параметров

**Разрыв 3 (DatasetSpec god-protocol):**
1. Открыть `connector/datasets/spec.py` — 15+ методов в одном протоколе
2. Попытаться добавить новую стадию — нужно добавить `build_new_spec()` + `build_new_stage()` + обновить `build_pipeline_context()` + обновить все command handlers
3. **Ожидаемый результат**: добавление стадии = регистрация плагина
4. **Фактический результат**: правка 5+ файлов

---

## 🚫 Почему это проблема?

- **Отсутствие единой модели**: пять стадий, три подхода к зависимостям, два механизма оркестрации. При таком росте каждая новая фича множит несогласованность.
- **Coupling через god-protocol**: `DatasetSpec` знает обо всех стадиях, всех зависимостях. Любое изменение в одной стадии потенциально затрагивает протокол.
- **Дублирование оркестрации**: match/resolve логика (open_match_runtime, flush, batch) дублируется между command handlers.
- **Нет pay-for-what-you-use**: команды получают зависимости, которые не используют (PROBLEM-002). Wiring строит зависимости, которые не нужны (PROBLEM-003). Два аспекта одного дефицита.
- **Нет plugin-расширяемости**: добавление новой стадии или capability — ручная правка множества файлов вместо регистрации в registry.
- **Нарушение hexagonal boundaries**: domain делает I/O при загрузке build_options.

---

## 💡 Возможные решения (обсуждение)

### Вариант A: Решать PROBLEM-002 и PROBLEM-003 по отдельности

- **Идея**: Реализовать DEC-002 (TransformContext) и DEC-003 (PipelineContainer) независимо
- **Плюсы**: Инкрементальный подход, меньший scope каждого изменения
- **Минусы**: Не решает разрывы 1 (match/resolve вне pipeline), 3 (god-protocol), 4 (нет orchestrator), 6 (недекларативные deps), 7 (I/O в domain). Два независимых решения создадут несогласованную полуархитектуру

### Вариант B: Modular Pipeline with Scoped Execution Context (принято)

- **Идея**: Целостная архитектура из 4 компонентов: Stage Contract, Execution Context, Stage Factory, Pipeline Orchestrator — собираемая через PipelineContainer (DI)
- **Плюсы**: Решает все 7 разрывов. Единый контракт для всех стадий. Scoped зависимости. Plugin-расширяемость. Чистые hexagonal boundaries.
- **Минусы**: Значительный scope рефактора; требует поэтапной миграции

---

## 🔗 Связанные документы

- [TRANSFORM-DEC-004](./TRANSFORM-DEC-004-modular-pipeline-scoped-execution-context.md) — принятое решение
- [TRANSFORM-PROBLEM-002](./TRANSFORM-PROBLEM-002-transform-provider-deps-coupling.md) — подпроблема: flat deps без capability scoping
- [TRANSFORM-PROBLEM-003](./TRANSFORM-PROBLEM-003-monolithic-pipeline-factory-eager-coupling.md) — подпроблема: eager monolithic wiring
- [TRANSFORM-DEC-002](./TRANSFORM-DEC-002-transform-context-capability-registry.md) — частное решение, поглощено DEC-004
- [TRANSFORM-DEC-003](./TRANSFORM-DEC-003-pipeline-container-lazy-stage-assembly.md) — частное решение, поглощено DEC-004
- `connector/domain/transform/stages/stages.py` — stage protocols и StagePipeline
- `connector/datasets/spec.py` — DatasetSpec god-protocol
- `connector/delivery/cli/containers.py` — build_pipeline_context(), PipelineContext
- `connector/delivery/commands/` — все command handlers

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-22 | Корневая проблема обнаружена при gap-анализе текущей архитектуры vs. целевой модели "Modular Pipeline with Scoped Execution Context" |
| 2026-02-22 | PROBLEM-002 и PROBLEM-003 идентифицированы как подпроблемы единого архитектурного дефицита |
| 2026-02-22 | Решение зафиксировано в TRANSFORM-DEC-004 |
