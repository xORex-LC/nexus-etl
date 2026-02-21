# TRANSFORM-PROBLEM-003: Монолитная `build_pipeline_context()` — сквозная утечка зависимостей между CLI-командами

> **Статус**: Открыта — решение зафиксировано в [TRANSFORM-DEC-003](./TRANSFORM-DEC-003-pipeline-container-lazy-stage-assembly.md)
> **Дата создания**: 2026-02-21
> **Затронутые компоненты**: `build_pipeline_context()`, `PipelineContext`, `connector/delivery/cli/containers.py`, `connector/delivery/commands/*.py`

---

## 📋 Контекст

`build_pipeline_context()` — единственная точка сборки transform-пайплайна для всех CLI-команд: normalize, enrich, map, match, resolve, import_plan. При каждом вызове функция немедленно строит полный граф: enrich_deps, planning_deps, map/normalize/enrich stages, row_source, stage_pipeline.

Результат упаковывается в `PipelineContext` — frozen dataclass с 8 полями — который команды затем деструктурируют, забирая нужные поля.

Архитектура сложилась органически: сначала был один пайплайн (map→normalize→enrich), потом добавились planning stages (match, resolve), потом vault, потом dictionaries. Каждая новая capability добавлялась как параметр фабричной функции. Накопился debt.

---

## ⚠️ Проблема

`build_pipeline_context()` строит весь граф зависимостей **eagerly** при каждом вызове, независимо от того, что реально нужно команде. Это означает: каждая команда обязана поставить все зависимости (включая те, которые она не использует), и каждая команда получает всё (включая то, что она не запросила).

---

## 🔍 Симптомы

**Симптом 1 — `resolver_settings` протекает во все команды без нужды.**

`normalize.py` строит только map + normalize pipeline. Planning-стадии ему не нужны. Но:

```python
# normalize.py
pipeline_ctx = build_pipeline_context(
    ...
    resolver_settings=app_settings.resolver,   # ← planning-настройка, normalize её не использует
)
usecase.run(
    row_source=pipeline_ctx.row_source,
    map_stage=pipeline_ctx.map_stage,
    normalize_stage=pipeline_ctx.normalize_stage,
    # planning_deps построен, но не трогается вообще
)
```

Та же картина в `enrich.py`: `resolver_settings` передаётся, `planning_deps` строится — и оба игнорируются командой.

**Симптом 2 — `resolver_settings` передаётся дважды в `match.py` (два источника правды).**

```python
# match.py
pipeline_ctx = build_pipeline_context(
    ...
    resolver_settings=app_settings.resolver,    # ← первый раз: идёт в planning_deps
)
planning_deps = pipeline_ctx.planning_deps

match_stage, _ = dataset_spec.build_planning_stages(
    planning_deps=planning_deps,
    settings=app_settings.resolver,             # ← второй раз: снова напрямую
)
```

`app_settings.resolver` прокидывается в одни и те же настройки двумя разными путями. Если они когда-нибудь рассинхронизируются (разные источники, разные defaults) — баг будет незаметным.

**Симптом 3 — `PipelineContext` смешивает несвязанные ответственности.**

```python
@dataclass(frozen=True)
class PipelineContext:
    map_stage: MapStage           # transform concern ✓
    normalize_stage: NormalizeStage
    enrich_stage: EnrichStage
    stage_pipeline: StagePipeline
    row_source: Iterable
    planning_deps: PlanningDependencies   # planning concern — не transform ✗
    report_items_limit: int               # observability concern — не pipeline ✗
    catalog: ErrorCatalog
    dataset_name: str
```

`planning_deps` нужен только командам match/resolve/import_plan. `report_items_limit` — observability-настройка, не относящаяся к pipeline. Dataclass стал catch-all зеркалом монолитной фабрики.

**Симптом 4 — Добавление новой capability требует обновления всех call sites.**

При добавлении Dictionary Layer в `build_pipeline_context()` добавили параметр `dictionaries: DictionaryProviderPort | None = None`. Все 6 команд, вызывающих функцию, стали потенциальными точками обновления — даже те, которые dictionaries не используют. Следующие capabilities (external API, telemetry, feature flags) дадут тот же эффект.

---

## 📊 Масштаб проблемы

- **Частота**: Присутствует в каждом вызове каждой CLI-команды
- **Критичность**: Средняя — не нарушает корректность прямо сейчас, но создаёт two-sources-of-truth риск (симптом 2) и ограничивает расширяемость
- **Затронуто**: Все 6 CLI-команд (`normalize`, `enrich`, `map`, `match`, `resolve`, `import_plan`), `containers.py`, future dataset specs

---

## 🧪 Как воспроизвести

**Симптом 1 (resolver_settings leak):**
1. Открыть `connector/delivery/commands/normalize.py`
2. Найти вызов `build_pipeline_context(..., resolver_settings=app_settings.resolver, ...)`
3. Найти в теле `build_pipeline_context()` строку `planning_deps = dataset_spec.build_planning_deps(resolver_settings, ...)`
4. **Ожидаемый результат**: normalize не должен знать о resolver_settings
5. **Фактический результат**: resolver_settings обязателен для вызова, planning_deps строится впустую

**Симптом 2 (дублирование в match):**
1. Открыть `connector/delivery/commands/match.py`
2. Найти `build_pipeline_context(..., resolver_settings=app_settings.resolver, ...)`
3. Найти ниже `dataset_spec.build_planning_stages(..., settings=app_settings.resolver)`
4. **Ожидаемый результат**: один источник для resolver_settings
5. **Фактический результат**: одно значение передаётся двумя разными путями

---

## 🚫 Почему это проблема?

- **Нарушение ISP на wiring-уровне**: команды вынуждены объявлять зависимость от `resolver_settings` и `planning_deps`, которые они не используют — потому что фабрика монолитная
- **Два источника правды**: `resolver_settings` в `match` передаётся дважды через разные пути; рассинхронизация даст молчаливый баг в планировщике
- **Рост числа параметров**: каждая новая capability (`dictionaries`, vault, telemetry) добавляет параметр в `build_pipeline_context()` и потенциально во все 6 command call sites
- **Сложность тестирования**: тест `normalize` обязан поставить `cache_roles` (для `planning_deps`), `resolver_settings` — зависимости, не нужные normalize-логике
- **Смешение ответственностей в PipelineContext**: dataclass содержит planning concern + observability concern рядом с transform stages

---

## 💡 Возможные решения (обсуждение)

### Вариант A: Разбить `build_pipeline_context()` на несколько функций

- **Идея**: `build_transform_context()` (map/normalize/enrich) + `build_planning_context()` (match/resolve deps)
- **Плюсы**: Минимальное изменение, понятно читается
- **Минусы**: Не решает корневую причину — eager construction остаётся; каждая новая capability всё равно добавляет параметр; тестирование не упрощается кардинально

### Вариант B: PipelineContainer — lazy per-stage провайдеры (принято)

- **Идея**: DI-контейнер с provider на каждую stage; команды запрашивают только нужное; `resolver_settings` живёт только в ветке `planning_deps`
- **Плюсы**: Lazy resolution, explicit dependency graph, open/closed для новых capabilities, natural slot для TransformContext (TRANSFORM-DEC-002), testability через provider override
- **Минусы**: Требует рефактора всех command handlers; добавляет новую концепцию в codebase

### Вариант C: Per-command фабрики

- **Идея**: Каждая команда имеет свою фабричную функцию
- **Плюсы**: Максимальная изоляция
- **Минусы**: Значительное дублирование wiring-логики; трудно обеспечить консистентность

---

## 🔗 Связанные документы

- [TRANSFORM-DEC-003](./TRANSFORM-DEC-003-pipeline-container-lazy-stage-assembly.md) — принятое решение
- [TRANSFORM-PROBLEM-002](./TRANSFORM-PROBLEM-002-transform-provider-deps-coupling.md) — связанная проблема deps coupling в domain
- [TRANSFORM-DEC-002](./TRANSFORM-DEC-002-transform-context-capability-registry.md) — TransformContext как domain-решение (PipelineContainer создаёт natural slot для его интеграции)
- `connector/delivery/cli/containers.py` — `build_pipeline_context()`, `PipelineContext`
- `connector/delivery/commands/` — все затронутые команды

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-21 | Проблема обнаружена при анализе утечки `resolver_settings` в `normalize.py` и дублирования в `match.py` |
| 2026-02-21 | Решение зафиксировано в TRANSFORM-DEC-003 (PipelineContainer) |
