# Cache DSL

## Purpose / Scope / Status

### Purpose
Сделать cache-слой декларативным и архитектурно согласованным с DSL-подходом приложения:
1. Конфигурация cache (registry/dataset schema/sync/policy) задаётся YAML.
2. Compile-процесс отделён от runtime-исполнения.
3. Домен и use-case слой работают через role-based порты.
4. Infra-уровень использует namespaced gateway и единый lifecycle.

### Scope
Этот документ описывает:
1. Текущее состояние Cache DSL.
2. Какие проблемы были и как они закрыты.
3. Алгоритмические потоки (без привязки к кодовой реализации как к первичному источнику).
4. Code mapping для классов, портов и ключевых методов.
5. Текущие ограничения и техдолг.

### Status
1. Cache DSL для `registry + dataset specs + runtime compile` внедрён.
2. Legacy dataset cache modules удалены из production path.
3. Role-based cache boundaries введены и проверяются архитектурными тестами.
4. Часть drift/status/retention нюансов остаётся как техдолг (см. раздел `Tech Debt / Open Issues`).

---

## Problem Statement

### CACHE-PROBLEM-001: Кодовый реестр и кодовые dataset cache-spec
**Проблема:**
Ранее cache-схемы и порядок датасетов задавались кодом (`cache_registry.py`, dataset-specific `cache_spec.py`).

**Риски:**
1. Любое изменение структуры требует правок Python-кода.
2. Высокий риск расхождений между датасет-конфигом и runtime.
3. Низкая переносимость и слабая расширяемость.

**Закрытие:**
1. Введены декларативные `CacheRegistrySpec` и `CacheDatasetSpec`.
2. Загрузка выполняется через DSL loader.
3. Компиляция runtime выполняется через cache DSL compile-слой.

**Где реализовано:**
1. `connector/domain/dsl/specs.py`
2. `connector/domain/dsl/loader.py`
3. `connector/domain/cache_core/cache_dsl.py`

**Статус:** `Implemented`.

---

### CACHE-PROBLEM-002: Ручной порядок refresh/clear и слабая работа с зависимостями
**Проблема:**
Порядок сценариев и зависимости датасетов были неунифицированы.

**Риски:**
1. Ошибочный refresh/clear порядок.
2. Невоспроизводимое поведение при добавлении датасетов.

**Закрытие:**
1. Введён `CacheDependencyGraph`.
2. Refresh/clear планирование вынесено в чистые planners.
3. `depends_on` в registry становится источником истины.

**Где реализовано:**
1. `connector/domain/cache_core/cache_dependency_graph.py`
2. `connector/domain/cache_core/cache_refresh_planner.py`
3. `connector/domain/cache_core/cache_clear_planner.py`

**Статус:** `Implemented`.

---

### CACHE-PROBLEM-003: Размытые границы домен <-> infra
**Проблема:**
Ранее существовали риски прямого импорта infra-cache в домен/use-cases и неявного lifecycle.

**Риски:**
1. Нарушение clean architecture границ.
2. Рост связности и усложнение замены backend.

**Закрытие:**
1. Введены role-based порты (`CacheAdminPort`, `EnrichLookupPort`, `PlanningRuntimePort`, и т.д.).
2. Реализация портов собрана в infra adapters поверх `SqliteCacheGateway`.
3. Границы закреплены архитектурными тестами.

**Где реализовано:**
1. `connector/domain/ports/cache/roles.py`
2. `connector/infra/cache/roles/*`
3. `tests/architecture/test_cache_layer_boundaries.py`

**Статус:** `Implemented`.

---

### CACHE-PROBLEM-004: Смешение compile/runtime и неявная policy-цепочка
**Проблема:**
Build options и policy merge были недостаточно явно зафиксированы для cache.

**Риски:**
1. Трудно предсказать итоговые compile-policy.
2. Сложно объяснять и поддерживать precedence.

**Закрытие:**
Зафиксирована merge-цепочка:
1. `defaults`
2. `global(cache)`
3. `dataset override` (optional)
4. `CLI override`

**Где реализовано:**
1. `connector/domain/dsl/build_options.py`
2. `connector/domain/dsl/loader.py` (`load_cache_build_options_for_runtime`)
3. `tests/transform/test_dsl_build_options.py`

**Статус:** `Implemented`.

---

### CACHE-PROBLEM-005: Неразделённость lifecycle-логики cache сценариев
**Проблема:**
Оркестрация `refresh/status/clear` была распределена и менее предсказуема.

**Риски:**
1. Труднее поддерживать единое поведение команд.
2. Сложнее переиспользовать общую командную логику.

**Закрытие:**
1. Введён `CacheLifecycleEngine` как единая orchestration-точка command-level сценариев.
2. `status/clear` use-cases делегируют в lifecycle engine.
3. `refresh` делегирует в существующий refresh use-case, сохраняя I/O-heavy pipeline отдельно.

**Где реализовано:**
1. `connector/domain/cache_core/cache_lifecycle_engine.py`
2. `connector/usecases/cache_status_usecase.py`
3. `connector/usecases/cache_clear_usecase.py`

**Статус:** `Implemented`.

---

### CACHE-PROBLEM-006: Legacy сервисная миграция SQLite с dataset-specific хвостом
**Проблема:**
В service-schema migrations есть legacy `_migrate_to_v2` c исторической привязкой к `users`.

**Риски:**
1. Потенциальные коллизии при переименованиях/новых датасетах.
2. Повышенная хрупкость schema evolution.

**Закрытие:**
Пока не закрыто полностью: зафиксировано как cleanup-техдолг.

**Где находится:**
1. `connector/infra/cache/backends/sqlite/schema.py`

**Статус:** `Open`.

---

## Accepted Decisions

### CACHE-DEC-001: Единый compile-вход Cache DSL
1. Компиляция cache runtime выполняется через `CacheDsl`.
2. Канонический runtime-bundle формируется в `load_cache_dsl_runtime()`.

**Код:**
1. `connector/domain/cache_core/cache_dsl.py`
2. `connector/infra/cache/dsl_runtime.py`

### CACHE-DEC-002: Role-based API для домена/use-cases
1. Домен не зависит от `SqliteCacheGateway` напрямую.
2. Используются role-порты по зонам ответственности.

**Код:**
1. `connector/domain/ports/cache/roles.py`
2. `connector/infra/cache/roles/*.py`

### CACHE-DEC-003: Namespaced gateway в infra/wiring
1. `SqliteCacheGateway` агрегирует `cache/identity/pending` репозитории.
2. Lifecycle (`open/close/transaction`) контролируется в infra.

**Код:**
1. `connector/infra/cache/cache_gateway.py`
2. `connector/delivery/cli/bootstrap.py`

### CACHE-DEC-004: Compile policy precedence фиксируется и тестируется
1. Merge-цепочка фиксирована (см. выше).
2. Есть unit coverage для precedence.

**Код:**
1. `connector/domain/dsl/loader.py`
2. `tests/transform/test_dsl_build_options.py`

### CACHE-DEC-005: Drift-hash разделяется на schema/sync
1. `schema_hash` — сигнал schema drift.
2. `sync_hash` — отдельный сигнал sync-конфига (диагностика/runtime metadata).

**Код:**
1. `connector/domain/cache_core/cache_dsl.py`

---

## Current Architecture

### Component View
1. **DSL Specs Layer**
   1. Pydantic-модели cache DSL.
   2. Описывает registry, dataset schema, sync, policy.
2. **DSL Loader Layer**
   1. Загружает YAML и валидирует спецификации.
   2. Готовит build-options.
3. **Cache DSL Compile Layer**
   1. Компилирует validated spec в runtime bundle.
   2. Строит dependency graph и hash-факты.
4. **Cache Core Layer**
   1. Чистые planners/evaluators/drift service.
   2. Lifecycle orchestration на command-level.
5. **Infra Cache Layer**
   1. SQLite backend (engine/schema/handlers/repositories).
   2. Gateway + role adapters.
6. **Use-case / CLI Layer**
   1. Вызывает lifecycle/use-cases.
   2. Управляет runtime wiring.

### Data Contract Boundaries
1. DSL spec (`CacheRegistrySpec`, `CacheDatasetSpec`) — декларативный контракт.
2. Runtime spec (`CacheSpec`) — инфраструктурный контракт создания/ensure таблиц.
3. Role ports — доменный контракт взаимодействия с cache.
4. SQLite repositories — инфраструктурная реализация storage API.

---

## Algorithmic Flows

### Flow A: Cache runtime compile
1. Загрузить registry DSL.
2. Для включённых датасетов загрузить dataset DSL.
3. Собрать compile-policy (merge precedence).
4. Провести compile:
   1. проверить целостность dataset specs,
   2. построить граф зависимостей,
   3. вычислить refresh order,
   4. скомпилировать schema runtime specs,
   5. вычислить hash-факты.
5. Вернуть runtime bundle для infra/wiring.

**Код:**
1. `connector/infra/cache/dsl_runtime.py`
2. `connector/domain/cache_core/cache_dsl.py`

### Flow B: Cache refresh
1. Получить refresh plan (dataset scope + dependency policy).
2. Оценить drift-policy для scope.
3. Для каждого датасета прочитать страницы target API и применить sync adapter.
4. Выполнить upsert в cache.
5. Обновить identity index + обработать pending resolution.
6. Обновить meta/hashes и сформировать агрегированную статистику.

**Код:**
1. `connector/usecases/cache_refresh_service.py`
2. `connector/domain/cache_core/cache_refresh_planner.py`

### Flow C: Cache status
1. Прочитать global meta.
2. Для каждого датасета собрать snapshot (`counts + dataset meta`).
3. Свести status-модель (per-dataset + total).

**Код:**
1. `connector/domain/cache_core/cache_lifecycle_engine.py`
2. `connector/domain/cache_core/cache_status_evaluator.py`

### Flow D: Cache clear
1. Построить clear plan (dataset/cascade).
2. Открыть общую транзакцию.
3. Для каждого датасета в плане:
   1. снять pre-clear count,
   2. очистить данные,
   3. сбросить dataset meta.
4. Вернуть summary удалённых записей.

**Код:**
1. `connector/domain/cache_core/cache_lifecycle_engine.py`
2. `connector/domain/cache_core/cache_clear_planner.py`

---

## Code Mapping (Classes / Methods / Ports)

## DSL Contracts

### `CacheRegistrySpec` (`connector/domain/dsl/specs.py`)
**Назначение:**
1. Глобальный реестр cache runtime.
2. Хранит policy и список датасетов cache-контура.

**Ключевые поля:**
1. `policy` — refresh/drift/clear/status/retention defaults.
2. `datasets` — map dataset -> registry entry (`cache_spec`, `depends_on`, `order_hint`, `enabled`).

**Где используется:**
1. Loader (`load_cache_registry_spec_for_runtime`).
2. Компиляция runtime (`CacheDsl.compile_runtime`).

### `CacheDatasetSpec` (`connector/domain/dsl/specs.py`)
**Назначение:**
1. Декларативный dataset cache контракт.
2. Описывает таблицу, схему колонок/индексов, sync-блок.

**Где используется:**
1. Loader dataset spec.
2. Runtime compile -> `CacheSpec`.
3. Sync adapter construction.

### `CacheDslBuildOptions` (`connector/domain/dsl/build_options.py`)
**Назначение:**
Compile-policy флаги cache DSL компиляции.

**Где используется:**
1. Loader merge (`load_cache_build_options_for_runtime`).
2. `CacheDsl` compile runtime validations.

---

## DSL Loader

### `load_cache_registry_spec_for_runtime` (`connector/domain/dsl/loader.py`)
**Назначение:**
Загрузка registry DSL из runtime стандартного источника.

**Возвращает:**
1. `CacheRegistrySpec`.

### `load_cache_dataset_spec_for_dataset` (`connector/domain/dsl/loader.py`)
**Назначение:**
Загрузка cache dataset DSL по имени датасета.

**Инварианты:**
1. `spec.dataset` должен совпадать с ключом датасета.

### `load_cache_build_options_for_runtime` (`connector/domain/dsl/loader.py`)
**Назначение:**
Построить итоговый `CacheDslBuildOptions` с merge-precedence.

**Инвариант:**
1. Источник истины для compile-policy cache runtime.

---

## Cache DSL Compile Layer

### `CacheDsl` (`connector/domain/cache_core/cache_dsl.py`)
**Назначение:**
Канонический compile entrypoint для cache runtime.

**Ключевой метод:**
1. `compile_runtime(registry_spec, dataset_specs) -> CacheDslRuntime`.

### `CacheDslRuntime` (`connector/domain/cache_core/cache_dsl.py`)
**Назначение:**
Скомпилированный bundle для cache runtime.

**Поля:**
1. `cache_specs` — tuple runtime schema specs.
2. `sync_specs` — dataset -> sync spec.
3. `dependency_graph` — граф зависимостей.
4. `schema_hashes` — dataset -> schema hash.
5. `sync_hashes` — dataset -> sync hash.
6. `policy` — compiled global runtime policy.

### `compile_cache_runtime` (`connector/domain/cache_core/cache_dsl.py`)
**Назначение:**
Чистая функция компиляции specs в runtime bundle.

**Внутренние проверки:**
1. missing specs.
2. dataset mismatch.
3. unknown/cyclic dependencies.
4. semantic validations по compile-policy.

### `build_schema_hash` / `build_sync_hash`
**Назначение:**
Детерминированные hash-факты для drift/status.

---

## Cache Core (pure orchestration logic)

### `CacheDependencyGraph`
**Назначение:**
Единая модель зависимостей и порядка для refresh/clear.

**Ключевые методы:**
1. `refresh_order(dataset=None, include_dependencies=False)`.
2. `clear_order(dataset=None, cascade=False)`.

### `CacheRefreshPlanner`
**Назначение:**
Построить refresh plan из dependency graph.

### `CacheClearPlanner`
**Назначение:**
Построить clear plan из dependency graph.

### `CacheStatusEvaluator`
**Назначение:**
Свести runtime-факты status в единый ответ.

### `CacheDriftService`
**Назначение:**
Сравнение schema-version/hash фактов (чистая логика drift-оценки).

### `CacheLifecycleEngine`
**Назначение:**
Единый command-level orchestration для `refresh/status/clear`.

**Контракт:**
1. `refresh` делегирует в refresh use-case (I/O-heavy).
2. `status` и `clear` исполняются через core evaluators/planners.

---

## Infra Cache

### `SqliteCacheGateway` (`connector/infra/cache/cache_gateway.py`)
**Назначение:**
Infra фасад над SQLite engine и namespaced repositories.

**Поля/секции:**
1. `cache`
2. `identity`
3. `pending`

**Ключевые методы:**
1. `open(settings, cache_specs)`.
2. `from_engine(engine, cache_specs, owns_connection=False)`.
3. `transaction()`.
4. `close()` + context manager API.

**Инварианты:**
1. Все repository используют один `SqliteEngine`.

### Role adapters (`connector/infra/cache/roles/*.py`)
**Назначение:**
Адаптировать gateway/repositories к role-based портам домена.

**Сборка:**
1. `build_sqlite_cache_role_ports(gateway)` -> `SqliteCacheRolePorts`.

### DSL runtime wiring (`connector/infra/cache/dsl_runtime.py`)
**Назначение:**
Связка loader + compile + sync adapter construction.

---

## Use-case Layer

### `CacheRefreshUseCase` (`connector/usecases/cache_refresh_service.py`)
**Назначение:**
I/O-heavy refresh pipeline (target read -> mapping/sync -> cache writes).

**Связи:**
1. `TargetPagedReaderProtocol`.
2. `CacheRefreshPort`.
3. `CacheSyncAdapterProtocol`.
4. `CacheRefreshPlanner` / drift-policy.

### `CacheStatusUseCase` (`connector/usecases/cache_status_usecase.py`)
**Назначение:**
Тонкая обёртка над `CacheLifecycleEngine.status()`.

### `CacheClearUseCase` (`connector/usecases/cache_clear_usecase.py`)
**Назначение:**
Тонкая обёртка над `CacheLifecycleEngine.clear()`.

---

## Ports and Interfaces

### Role-based ports (`connector/domain/ports/cache/roles.py`)

1. `CacheAdminPort`
   1. Snapshot/admin API: count, clear, rebuild, meta, transaction.
2. `EnrichLookupPort`
   1. Lookup API для enrich стадии (`find/find_one`).
3. `MatchRuntimePort`
   1. Lookup + runtime-state API для matcher.
4. `ResolveRuntimePort`
   1. Pending/identity lifecycle API для resolver.
5. `ApplyRuntimePort`
   1. Post-apply reconciliation API.
6. Композиты:
   1. `CacheRefreshPort` (`CacheAdminPort + ApplyRuntimePort`)
   2. `PendingReplayPort` (`ResolveRuntimePort`)
   3. `PlanningRuntimePort` (`MatchRuntimePort + ResolveRuntimePort`)

---

## Error / Diagnostics Model

### DSL load/compile errors
1. Loader/compile ошибки поднимаются как `DslLoadError`.
2. На orchestration-границе они транслируются в DSL issue/diagnostic контур.

**Ключевые модули:**
1. `connector/domain/dsl/issues.py`
2. `connector/domain/dsl/diagnostics.py`
3. runtime wiring/command boundary.

### Runtime cache errors
1. Runtime ошибки refresh/status/clear проходят через diagnostic/reporting слой use-case/command.
2. Row-level cache refresh ошибки фиксируются через report item со stage=`CACHE`.

---

## Tests & Architectural Guards

### Unit / behavior
1. `tests/unit/cache/test_cache_dependency_graph.py`
2. `tests/unit/cache/test_cache_planners.py`
3. `tests/unit/cache/test_cache_status_evaluator.py`
4. `tests/unit/cache/test_cache_drift_service.py`
5. `tests/unit/cache/test_cache_lifecycle_engine.py`
6. `tests/integration/cache/test_sqlite_engine_transactions.py`
7. `tests/integration/cache/test_pending_links_repository.py`
8. `tests/integration/cache/test_generic_cache_handler.py`
9. `tests/transform/test_dsl_build_options.py`

### Architectural tests
1. `tests/architecture/test_cache_layer_boundaries.py`

Что защищают:
1. Domain/usecases не импортируют `connector.infra.cache`.
2. `SqliteCacheGateway` импортируется только в wiring/infra/tests.
3. Legacy cache factory/registry/dataset modules не должны возвращаться.

---

## Tech Debt / Open Issues

1. Service-schema legacy migration `_migrate_to_v2` в SQLite schema модуле.
   1. Статус: `Open`.
   2. Риск: historical coupling к старой модели таблиц.

2. `sync_hash` пока не полностью встроен в status/degraded semantics как отдельный сигнал политики.
   1. Статус: `Open`.

3. Консистентное покрытие документации по всем cache командам и failure-mode matrix (strict/soft drift policy) требует выделенного runbook-документа.
   1. Статус: `Open`.

4. Исторический re-export `connector/domain/dsl/cache_compiler.py` удалён.
   1. Статус: `Implemented`.
   2. Каноничный compile-модуль: `connector/domain/cache_core/cache_dsl.py`.

---

## Quick Reference

### Где смотреть compile-конвейер cache DSL
1. `connector/infra/cache/dsl_runtime.py`
2. `connector/domain/cache_core/cache_dsl.py`
3. `connector/domain/dsl/loader.py`
4. `connector/domain/dsl/specs.py`

### Где смотреть runtime cache lifecycle
1. `connector/domain/cache_core/cache_lifecycle_engine.py`
2. `connector/usecases/cache_refresh_service.py`
3. `connector/usecases/cache_status_usecase.py`
4. `connector/usecases/cache_clear_usecase.py`

### Где смотреть infra adapters
1. `connector/infra/cache/cache_gateway.py`
2. `connector/infra/cache/roles/*`
3. `connector/domain/ports/cache/roles.py`

---

## Getting Started

### Быстрый старт (5 минут)
1. Проверить cache DSL конфиги:
   1. `datasets/registry.yml`
   2. `datasets/organizations.cache.yaml`
   3. `datasets/employees.cache.yaml`
2. Проверить, что в реестре включены нужные датасеты и корректны `depends_on`.
3. Запустить `cache refresh` и убедиться, что созданы dataset-таблицы и заполнена `meta`.
4. Запустить `cache status` и проверить:
   1. `schema_version`
   2. `by_dataset`
   3. `total`
5. Для отладки drift-поведения:
   1. изменить schema в одном `*.cache.yaml`,
   2. повторить `cache refresh`,
   3. проверить реакцию в зависимости от policy (`strict/soft`, `fail/rebuild`).

### Что смотреть при отладке
1. DSL загрузка/валидация: `connector/domain/dsl/loader.py`.
2. Compile runtime bundle: `connector/domain/cache_core/cache_dsl.py`.
3. Runtime wiring: `connector/infra/cache/dsl_runtime.py`.
4. Refresh runtime: `connector/usecases/cache_refresh_service.py`.

---

## Canonical YAML Examples

### Пример `cache` registry
Источник: `datasets/registry.yml`.

```yaml
cache:
  version: 1
  policy:
    refresh:
      with_deps_default: true
    drift:
      mode: strict
      on_hash_mismatch: fail
      rebuild_scope: dataset
  datasets:
    organizations:
      cache_spec: organizations.cache.yaml
      depends_on: []
      order_hint: 10
      enabled: true
    employees:
      cache_spec: employees.cache.yaml
      depends_on: [organizations]
      order_hint: 20
      enabled: true
```

#### Пояснение ключей (`cache` registry)
1. `cache.version` — версия формата registry; используется loader/compiler для совместимости.
2. `cache.policy.refresh.with_deps_default` — дефолт поведения `cache refresh`: подтягивать зависимости или нет, если CLI-флаг не задан явно.
3. `cache.policy.drift.mode` — стратегия drift-режима (`strict`/`soft`).
4. `cache.policy.drift.on_hash_mismatch` — действие при несовпадении `schema_hash` (`fail`/`rebuild`).
5. `cache.policy.drift.rebuild_scope` — масштаб rebuild при drift (`dataset`/`all`).
6. `cache.datasets.<name>.cache_spec` — путь к YAML-спецификации датасета.
7. `cache.datasets.<name>.depends_on` — граф зависимостей для порядка refresh/clear.
8. `cache.datasets.<name>.order_hint` — tie-break при сортировке, если зависимости не задают строгий порядок.
9. `cache.datasets.<name>.enabled` — участвует ли датасет в runtime компиляции.
10. `cache.datasets.<name>.allow_partial_refresh` — признак частичного refresh для датасета (используется policy-слоем при оркестрации).

### Пример dataset cache spec
Источник: `datasets/employees.cache.yaml`.

```yaml
dataset: employees
table: users
schema:
  primary_key: _id
  columns:
    - name: _id
      type: string
      required: true
    - name: _ouid
      type: int
      required: true
  indexes:
    - name: uidx_users_ouid
      fields: [_ouid]
      unique: true
sync:
  dataset: employees
  list_path: /ankey/managed/user
  report_entity: user
  projection:
    - target: _id
      sources: [_id, id]
      ops:
        - op: coalesce
        - op: trim
      required: true
      on_error: error
```

#### Пояснение ключей (`dataset cache spec`)
1. `dataset` — логическое имя датасета; должно совпадать с ключом в `cache.datasets`.
2. `table` — имя snapshot-таблицы в cache storage.
3. `schema.primary_key` — PK таблицы (`str` для одного поля или `list[str]` для composite key).
4. `schema.columns[].name` — имя колонки в cache-таблице.
5. `schema.columns[].type` — DSL-тип (`string|int|float|bool|datetime|json`), компилируется в backend-тип.
6. `schema.columns[].required` — обязательность значения на уровне cache schema/runtime checks.
7. `schema.columns[].default` — дефолт колонки (если задан).
8. `schema.columns[].source` — исходное поле для трассировки происхождения значения.
9. `schema.indexes[].name` — техническое имя индекса.
10. `schema.indexes[].fields` — поля индекса в порядке применения.
11. `schema.indexes[].unique` — признак уникальности индекса.
12. `sync.dataset` — датасет для sync-контура (обычно равен `dataset`).
13. `sync.list_path` — endpoint/path источника для refresh.
14. `sync.report_entity` — идентификатор сущности для отчётов refresh.
15. `sync.item_key` — выражение построения ключа внешней записи (дедуп/трассировка).
16. `sync.projection[].target` — целевая колонка cache-таблицы.
17. `sync.projection[].source|sources` — источник(и) значения для `target`.
18. `sync.projection[].ops` — цепочка DSL-операций преобразования.
19. `sync.projection[].required` — обязательность правила проекции.
20. `sync.projection[].on_error` — поведение при ошибке (`error|warning|skip|set_null`).
21. `flags.*` — runtime-флаги поведения sync-адаптера (например, `include_deleted`).

---

## Error Scenarios

### Типовые сценарии

| Сценарий | Сигнал ошибки | Диагностика | Восстановление |
|---|---|---|---|
| Невалидный cache DSL YAML | `DslLoadError` | `dsl diagnostics` + `DiagnosticItem(stage=CACHE)` | Исправить YAML, повторить запуск |
| Отсутствует dataset в registry | `DslLoadError` (`CACHE_DSL_DEP_MISSING`) | Ошибка compile runtime | Добавить dataset в `datasets/registry.yml` |
| Цикл зависимостей `depends_on` | `DslLoadError` (`CACHE_DSL_DEP_CYCLE`) | Ошибка графа зависимостей | Разорвать цикл, проверить topology |
| Drift schema hash в strict/fail | runtime exception в refresh | Ошибка refresh, status показывает mismatch | Согласовать schema или сменить drift policy |
| Некорректный `projection.target` | compile validation error | Сигнал compile-policy | Исправить projection или sink/cache schema |

### Политики отказа
1. `strict + fail`: при drift refresh останавливается.
2. `strict + rebuild`: выполняется rebuild в пределах policy scope.
3. `soft + fail`: фиксируется degraded signal, но rebuild не выполняется автоматически.
4. `soft + rebuild`: допускается автоматическое восстановление по policy.

---

## Extending The DSL

### Добавление нового cache dataset
1. Добавить `<dataset>.cache.yaml` с блоками `schema` и `sync`.
2. Подключить dataset в `datasets/registry.yml` (`cache.datasets`).
3. При необходимости указать `depends_on` и `order_hint`.
4. Прогнать refresh/status и проверить hash/meta.

### Добавление нового sync поведения
1. Сначала использовать существующие DSL ops в `projection`.
2. Если ops не хватает, добавить универсальную op в dsl-core и покрыть тестом.
3. Не добавлять dataset-specific Python ветку, если поведение можно выразить DSL.

### Добавление новой global policy
1. Расширить `CachePolicySpec` в `connector/domain/dsl/specs.py`.
2. Пробросить в `CacheDslRuntimePolicy` в `connector/domain/cache_core/cache_dsl.py`.
3. Подключить использование в lifecycle/use-case.
4. Добавить unit + architecture/contract тесты.

---

## Visualization

### Зависимости датасетов (ASCII)

```text
organizations  --->  employees
     (root)         (depends_on organizations)
```

### Порядок операций
1. `refresh(with_deps=true, dataset=employees)`: `organizations -> employees`.
2. `clear(cascade=true, dataset=organizations)`: `employees -> organizations`.

### UML
1. Основные диаграммы cache находятся в `docs/uml/cache/`.
2. Для структуры каталогов и перечня диаграмм см. `docs/uml/cache/README.md`.

---

## Versioning & Migration

### Версионирование
1. Версия cache registry задаётся в `cache.version` (`datasets/registry.yml`).
2. Изменения schema влияют на `schema_hash`.
3. Изменения sync-конфига влияют на `sync_hash`.

### Правила эволюции схемы
1. Обратимо-совместимые изменения (новые nullable колонки/индексы) — preferred.
2. Ломающие изменения должны сопровождаться drift policy решением (`fail` или `rebuild`).
3. Service schema migrations и dataset schema compile не смешиваются по ответственности.

### Миграционный протокол
1. Обновить YAML спецификации.
2. Проверить compile runtime (loader + compiler).
3. Выполнить `cache refresh` в контролируемом окружении.
4. Проверить `cache status` и meta/hash.
5. После валидации перенести изменения в рабочий контур.
