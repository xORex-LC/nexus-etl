# TRANSFORM-DEC-003: PipelineContainer — lazy per-stage сборка зависимостей через DI

> **Статус**: Принято — реализация запланирована
> **Дата принятия**: 2026-02-21
> **Решает проблему**: [TRANSFORM-PROBLEM-003](./TRANSFORM-PROBLEM-003-monolithic-pipeline-factory-eager-coupling.md)
> **Участники решения**: @xorex

---

## 📋 Контекст

Монолитная `build_pipeline_context()` строит весь граф зависимостей при каждом вызове, не различая, какая команда что реально использует. Это приводит к утечке `resolver_settings` в команды, которым она не нужна, к eager construction `planning_deps` в enrich/normalize, к передаче одного значения двумя путями в match, и к тому, что каждая новая capability требует обновления всех call sites. Подробно — в [TRANSFORM-PROBLEM-003](./TRANSFORM-PROBLEM-003-monolithic-pipeline-factory-eager-coupling.md).

---

## 🎯 Решение

Заменить монолитную `build_pipeline_context()` на `PipelineContainer` — `DeclarativeContainer` из `dependency-injector`, где каждая transform-стадия является отдельным `providers.Factory`. Команды запрашивают только нужные провайдеры. Контейнер резолвит только запрошенное. `resolver_settings` существует исключительно в ветке `planning_deps` и никогда не материализуется в командах, которые planning не используют.

`PipelineContainer` — это **composition root для transform-пайплайна**. Он не несёт бизнес-логику. Он декларирует граф зависимостей между стадиями и предоставляет чистый, изолированный от команд wiring.

---

## 🏗️ Архитектурное решение

### Компоненты

**`PipelineContainer`** в `connector/delivery/cli/containers.py`:

```python
class PipelineContainer(containers.DeclarativeContainer):
    # ── Внешние зависимости (приходят от вызывающей команды) ──────────────
    cache_roles     = providers.Dependency(instance_of=SqliteCacheRolePorts)
    dataset_spec    = providers.Dependency(instance_of=DatasetSpec)
    catalog         = providers.Dependency(instance_of=ErrorCatalog)
    csv_has_header  = providers.Dependency(instance_of=bool)

    # resolver_settings: только для planning-ветки (match/resolve)
    # Команды без planning не передают это значение → не резолвится
    resolver_settings = providers.Dependency(instance_of=(ResolverSettings, type(None)))

    # Опциональные capabilities: передаются только теми командами, которым нужны
    secret_store  = providers.Dependency(instance_of=(SecretStoreProtocol, type(None)))
    dictionaries  = providers.Dependency(instance_of=(DictionaryProviderPort, type(None)))

    # ── Transform stages (resolver_settings не участвует) ─────────────────
    enrich_deps = providers.Factory(
        _build_enrich_deps,
        spec=dataset_spec,
        cache_roles=cache_roles,
        secret_store=secret_store,
        dictionaries=dictionaries,
    )
    map_stage       = providers.Factory(_build_map_stage,       spec=dataset_spec, catalog=catalog)
    normalize_stage = providers.Factory(_build_normalize_stage, spec=dataset_spec, catalog=catalog)
    enrich_stage    = providers.Factory(_build_enrich_stage,    spec=dataset_spec,
                                        catalog=catalog, enrich_deps=enrich_deps)
    row_source      = providers.Factory(_build_row_source, spec=dataset_spec, csv_has_header=csv_has_header)

    # ── Planning stages (resolver_settings резолвится только здесь) ───────
    planning_deps = providers.Factory(
        _build_planning_deps,
        spec=dataset_spec,
        settings=resolver_settings,
        cache_roles=cache_roles,
    )
    match_stage   = providers.Factory(_build_match_stage,   spec=dataset_spec,
                                      planning_deps=planning_deps, catalog=catalog)
    resolve_stage = providers.Factory(_build_resolve_stage, spec=dataset_spec,
                                      planning_deps=planning_deps, catalog=catalog)
```

**Как каждая команда использует контейнер:**

```python
# normalize.py — запрашивает только transform stages
container = PipelineContainer()
container.cache_roles.override(cache_roles)
container.dataset_spec.override(dataset_spec)
container.catalog.override(catalog)
container.csv_has_header.override(csv_has_header_value)
# resolver_settings — НЕ передаётся, НЕ переопределяется
# planning_deps — никогда не строится

row_source     = container.row_source()
map_stage      = container.map_stage()
normalize_stage = container.normalize_stage()
```

```python
# match.py — запрашивает planning stages (resolver_settings резолвится один раз)
container = PipelineContainer()
container.cache_roles.override(cache_roles)
container.dataset_spec.override(dataset_spec)
container.catalog.override(catalog)
container.csv_has_header.override(csv_has_header_value)
container.resolver_settings.override(app_settings.resolver)  # ОДИН раз, здесь

planning_deps = container.planning_deps()  # resolver_settings резолвится
match_stage   = container.match_stage()
```

### Граф зависимостей по командам

```
normalize  →  map_stage, normalize_stage, row_source
              (resolver_settings, planning_deps: не создаются)

enrich     →  map_stage, normalize_stage, enrich_stage, row_source
              (resolver_settings, planning_deps: не создаются)

match      →  stage_pipeline (map+norm+enrich), row_source
              match_stage → planning_deps → resolver_settings ← ТОЛЬКО ЗДЕСЬ
              (один источник, один путь)

resolve    →  resolve_stage → planning_deps → resolver_settings ← ТОЛЬКО ЗДЕСЬ
```

### Что происходит с `PipelineContext` и `build_pipeline_context()`

`build_pipeline_context()` удаляется. `PipelineContext` как dataclass-обёртка удаляется или сужается: команды больше не получают "весь контекст", они запрашивают конкретные providers из контейнера напрямую.

Если обратная совместимость нужна для переходного периода — `build_pipeline_context()` можно сохранить как тонкую обёртку над `PipelineContainer`, но без `resolver_settings` в сигнатуре для команд, которым он не нужен.

### Добавление новой capability (forward compatibility)

Новая capability (например, `telemetry_port`, `external_api_client`) добавляется как:
1. `telemetry = providers.Dependency(...)` в `PipelineContainer`
2. Новое значение в `_build_enrich_deps()` или в stage-builder, которому оно нужно
3. Команды, которые не используют — не передают, не видят

Остальные команды **не требуют изменений**. Это и есть open/closed на уровне wiring.

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **Lazy resolution**: normalize не строит `planning_deps` и не знает о `resolver_settings`
- ✅ **Один источник правды**: `resolver_settings` в match передаётся ровно один раз, в одном месте — через `container.resolver_settings.override()`
- ✅ **Explicit dependency graph**: граф зависимостей описан декларативно, не разбросан по command handlers
- ✅ **Open/closed для capabilities**: новая capability — новый провайдер в контейнере; остальные команды не меняются
- ✅ **Testability**: тест normalize overrides только `dataset_spec`, `catalog`, `csv_has_header` — без `cache_roles`, `resolver_settings`, `planning_deps`
- ✅ **Natural slot для TransformContext**: когда trigger-критерии TRANSFORM-DEC-002 будут достигнуты, `enrich_deps` провайдер меняет `TransformProviderDeps(...)` на `TransformContext.build(...)` — остальной граф не меняется

**Недостатки (компромиссы)**:
- ⚠️ Рефактор всех 6 command handlers — необходимая стоимость; компенсируется тем, что каждый handler становится проще
- ⚠️ `providers.Dependency` с `instance_of=(SomeType, type(None))` для опциональных значений — не самый элегантный способ объявить nullable dependency в dependency-injector; альтернатива — callable providers с default None

**Альтернативы, которые отклонили**:
- ❌ **Вариант A (split на несколько функций)**: снижает симптомы, не устраняет корневую причину — eager construction и рост числа параметров при добавлении capabilities
- ❌ **Per-command фабрики**: дублирование wiring-логики; консистентность между командами сложнее поддерживать

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/delivery/cli/containers.py` | Добавить `PipelineContainer`; удалить или deprecate `build_pipeline_context()`, `PipelineContext` |
| `connector/delivery/commands/normalize.py` | Использовать `PipelineContainer`; убрать `resolver_settings` из вызова |
| `connector/delivery/commands/enrich.py` | Использовать `PipelineContainer`; убрать `resolver_settings` из вызова |
| `connector/delivery/commands/match.py` | Использовать `PipelineContainer`; убрать дублирование `resolver_settings` |
| `connector/delivery/commands/resolve.py` | Использовать `PipelineContainer` |
| `connector/delivery/commands/mapping.py` | Использовать `PipelineContainer` |
| `connector/delivery/commands/import_plan.py` | Использовать `PipelineContainer` |
| `connector/usecases/import_plan_service.py` | Принимать явные stage-параметры вместо `PipelineContext` |
| `tests/unit/delivery/` | Обновить fixtures: override только нужных providers |

### Инварианты

1. `PipelineContainer` — stateless контейнер: один экземпляр на вызов команды, не переиспользуется между вызовами
2. `resolver_settings` не появляется в командах normalize/enrich/map/mapping — ни как параметр, ни в impory
3. `planning_deps` не строится в командах, которые не используют match/resolve stages
4. Каждый `providers.Factory` — чистая функция без side-effects; side-effects (открытие соединений) остаются в `SqliteContainer`

---

## 🧪 Валидация решения

**Тесты:**
- ✅ `test_normalize_pipeline_does_not_require_resolver_settings()` — `PipelineContainer` для normalize не требует `resolver_settings.override()`
- ✅ `test_match_pipeline_resolver_settings_single_source()` — один `resolver_settings.override()`, результат используется и в `planning_deps`, и в `build_planning_stages()`
- ✅ `test_enrich_only_pipeline_no_planning_deps_created()` — `planning_deps()` не вызывается в enrich-пути
- ✅ `test_new_capability_does_not_affect_normalize()` — добавление нового провайдера в `PipelineContainer` не ломает normalize-тест

---

## ⚠️ Риски и ограничения

**Известные ограничения:**
- `providers.Dependency` для опциональных значений требует явного `None`-override в тестах — иначе `Dependency` бросит при резолвинге
- Порядок override важен: все зависимости должны быть переопределены до вызова провайдеров

**Риски:**
- ⚠️ Команда забывает override нужного провайдера → runtime error при резолвинге (а не на старте)
  - **Митигация**: Явные integration-тесты каждой команды; `Dependency(instance_of=...)` даёт понятный error
- ⚠️ Случайный override глобального состояния при тестировании (стандартная проблема DI в тестах)
  - **Митигация**: Создавать новый экземпляр `PipelineContainer()` в каждом тесте (не переиспользовать)

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `build_pipeline_context()` | Удаляется | Заменяется `PipelineContainer` |
| `PipelineContext` dataclass | Удаляется или сужается | Команды получают stages напрямую из контейнера |
| CLI commands (6 файлов) | Средний рефактор | Переход от деструктуризации `PipelineContext` к вызову providers |
| `import_plan_service.py` | Минимальный | Принимать stage-параметры напрямую |
| `TransformProviderDeps` / `TransformContext` | Нет | `enrich_deps` провайдер — natural slot для замены при триггере TRANSFORM-DEC-002 |
| Тесты | Упрощение | Меньше setup-кода: override только нужных providers |

---

## 🔗 Связанные документы

- [TRANSFORM-PROBLEM-003](./TRANSFORM-PROBLEM-003-monolithic-pipeline-factory-eager-coupling.md) — решаемая проблема
- [TRANSFORM-PROBLEM-002](./TRANSFORM-PROBLEM-002-transform-provider-deps-coupling.md) — deps coupling в domain (PipelineContainer создаёт slot для TransformContext)
- [TRANSFORM-DEC-002](./TRANSFORM-DEC-002-transform-context-capability-registry.md) — TransformContext: при достижении trigger-критериев слот `enrich_deps` провайдера принимает `TransformContext.build(...)`
- `connector/delivery/cli/containers.py` — место реализации `PipelineContainer`

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-21 | Решение предложено и принято |
| 2026-02-21 | Зафиксирована связь с TRANSFORM-DEC-002 (natural slot для TransformContext) |
