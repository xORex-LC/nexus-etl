# Cache DSL

## Цель
Сделать кэш-слой декларативным и расширяемым, сохранив безопасное поведение в runtime:
- конфигурация кэша и зависимостей датасетов описывается в YAML;
- домен и use-case работают через role-based порты;
- infra/wiring использует namespaced gateway;
- исключаются dataset-specific ветки в общих миграциях SQLite.

---

## Принятые решения

### 1) Порядок и зависимости датасетов
Решение:
1. Канон в `datasets/registry.yml`: `depends_on` + `order_hint`.
2. Runtime строит topological порядок, `order_hint` используется как tie-break.

Как реализовано:
1. Компиляция графа и порядка — `connector/domain/dsl/cache_compiler.py`.
2. Runtime refresh order — `connector/infra/cache/dsl_runtime.py`.

Статус: `реализовано`.

### 2) Границы API
Решение:
1. Домен/use-case используют только role-based порты.
2. Внутри infra/wiring используется namespaced gateway.

Как реализовано:
1. Роли/порты — `connector/domain/ports/cache/roles.py`.
2. Wiring и lifecycle — `connector/delivery/cli/bootstrap.py`.
3. Infra gateway — `connector/infra/cache/cache_gateway.py`.

Статус: `реализовано`.

### 3) Разделение схем
Решение:
1. Service schema (meta/identity/pending/runtime_state) остаётся в SQLite migration слое.
2. Dataset schema описывается декларативно в `datasets/*.cache.yaml`.

Как реализовано:
1. Service schema migrations — `connector/infra/cache/backends/sqlite/schema.py`.
2. Dataset schema compile/ensure — `connector/domain/dsl/cache_compiler.py` -> `connector/infra/cache/backends/sqlite/handlers/generic_handler.py`.

Статус: `частично реализовано`.
1. Основная модель работает.
2. Остаётся legacy-хвост `_migrate_to_v2` с исторической привязкой к `users`.

### 4) Стратегия prod/dev по схеме
Решение:
1. Полный rebuild всей БД не используется как канон.
2. Гибрид: service schema via migrations, dataset schema via ensure/rebuild.

Как реализовано:
1. Service schema lifecycle — `schema.py`.
2. Dataset rebuild в drift-path — `CacheRefreshUseCase` + `cache_refresh.rebuild(...)`.

Статус: `реализовано` (с учётом legacy `_migrate_to_v2`).

### 5) Drift control через `schema_hash` (+опционально `sync_hash`)
Решение:
1. `schema_hash` обязателен для drift-control.
2. `sync_hash` опционален и не триггерит rebuild.
3. Режимы drift: `strict|soft`, действия: `fail|rebuild`.

Как реализовано:
1. Hash compile — `connector/domain/dsl/cache_compiler.py`.
2. Drift-оценка и действие в runtime — `connector/usecases/cache_refresh_service.py`.

Статус: `частично реализовано`.
1. `schema_hash` работает end-to-end.
2. `sync_hash` вычисляется, но пока не встроен в status-оценку как отдельный сигнал.

---

## Сверка статуса (факт на текущий момент)
Закрыто:
1. DSL runtime для cache (`registry + dataset specs + compiler + runtime bundle`).
2. Переход на generic `DslCacheSyncAdapter`.
3. Удаление legacy `cache_registry.py`, `load/cache_spec.py`, `load/cache_sync_adapter.py`.
4. Role-based границы и единый `open_cache(...)` lifecycle.

В работе / не доведено:
1. Выделение отдельного `CacheLifecycleEngine` (сейчас orchestration распределен по use-case слою).
2. Полная концентрация drift/status policy в `cache_core` (часть логики остаётся в use-case).
3. Финальная очистка service-schema legacy миграции (`_migrate_to_v2`).

---

## Что было не декларативно (статус после Plan B)
Закрыто:
1. Dataset cache specs больше не задаются кодом (`connector/datasets/*/load/cache_spec.py` удалены).
2. Кодовый registry больше не используется (`connector/datasets/cache_registry.py` удален).
3. `DatasetSpec.build_cache_specs()` удален из контрактов.
4. Dataset-specific sync adapters удалены, runtime использует `DslCacheSyncAdapter`.

Осталось:
1. В `connector/infra/cache/backends/sqlite/schema.py` остаётся миграция `_migrate_to_v2` с исторической привязкой к таблице `users`; это legacy-хвост service-schema эволюции, который нужно убрать отдельной cleanup-задачей.

---

## Встраивание в текущий dsl-core
Кэш использует тот же контур, что и другие DSL-слои:
1. Loader читает YAML (`domain/dsl/loader.py`).
2. Pydantic валидирует spec (`domain/dsl/specs.py`).
3. Compiler переводит в runtime `CacheSpec` (`infra/cache/cache_spec.py`).
4. `SqliteCacheGateway.open(..., cache_specs=...)` применяет ensure.
5. Loader/validator ошибки поднимаются как `DslLoadError`; в orchestration слое они переводятся в `DslIssue` -> `DiagnosticItem(stage=CACHE)`.

---

## Loader Contract (расширение под cache)

Loader для cache DSL расширяется без дублирования существующего поведения.

### Что переиспользуем
1. `_read_yaml(path)` — базовое чтение YAML mapping.
2. `_repo_root()` — разрешение путей.
3. Паттерн `raw -> pydantic.model_validate(raw)`.
4. Единый путь диагностики: `DslLoadError` -> (`DslIssue` в orchestration) -> `DiagnosticItem(stage=CACHE)`.

### Что добавлено (факт)
1. `load_cache_registry_spec(path: str | Path | None = None) -> CacheRegistrySpec`
2. `load_cache_registry_spec_for_runtime() -> CacheRegistrySpec`
3. `load_cache_dataset_spec(path: str | Path) -> CacheDatasetSpec`
4. `load_cache_dataset_spec_for_dataset(dataset: str) -> CacheDatasetSpec`

### Что остаётся как backlog
1. `load_cache_policy() -> CachePolicySpec`
2. `list_cache_enabled_datasets() -> list[str]`

Канон:
1. Sync-описание читается из секции `sync` внутри `CacheDatasetSpec` (`*.cache.yaml`).
2. Отдельный `*.cache_sync.yaml` допустим только как transitional-совместимость до cutover.

### Что НЕ делает loader
1. Не строит граф зависимостей (`depends_on`) и не сортирует порядок.
2. Не выполняет semantic-check между несколькими спеками.
3. Не компилирует `soft_delete -> is_deleted`.
4. Не проверяет drift/hash.

Это зона compile/runtime orchestration слоя.

### Семантические проверки (где должны быть)
1. `depends_on` cycles/missing deps.
2. `primary_key/index.fields` ссылочная корректность.
3. уникальность имен колонок/индексов.
4. соответствие `sync.projection.target` колонкам cache schema.
5. политика `soft_delete` vs `is_deleted`.

---

## Sink-spec и sink-storage-spec (границы и применение)

Чтобы не смешивать модель данных и транспорт/хранилище, фиксируются два независимых декларативных контракта.

### 1) `SinkModelSpec` (dataset-level)
Назначение:
1. Описывает, как выглядят данные сущности в sink:
   - поля, типы, required/nullable;
   - системные поля;
   - primary/identity keys;
   - managed/immutable поля.

Использование:
1. `map/normalize` — структура и типовая валидация.
2. `enrich` — targeted check только по изменяемым полям.
3. `match/resolve` — правила identity/op decision на основе контрактных полей.
4. `plan` — diff по managed полям и policy `ignored_fields`.
5. `apply` — формирование payload строго по контракту.

### 2) `SinkStorageSpec` (integration-level)
Назначение:
1. Описывает способ работы с конкретным sink backend/API:
   - endpoints/paths;
   - batch limits;
   - retry/timeout policy;
   - поддерживаемые операции (`create/update/delete`);
   - особенности формата идентификаторов/soft-delete.

Использование:
1. `apply` и `cache-refresh/sync` для transport/runtime поведения.
2. Не содержит бизнес-валидацию полей датасета.

### 3) Практическая граница
1. `SinkModelSpec` отвечает на вопрос: "какие данные допустимы".
2. `SinkStorageSpec` отвечает на вопрос: "как/куда отправляем и читаем".
3. Runtime использует только скомпилированные объекты spec, не raw YAML.

---

## Границы с TransformationEngine

### Базовое правило
`cache` не использует `TransformationEngine` напрямую внутри `gateway/repository` слоя.

Причины:
1. Разделение ответственности: cache отвечает за storage/lifecycle, не за бизнес-трансформацию.
2. Снижение связности: infra cache остаётся независимым от stage-движков.
3. Проще миграция backend (SQLite -> другой storage), без DSL transform-runtime внутри cache infra.

### Допустимый сценарий использования
Если нужны вычисления для snapshot (projection/derived fields), они выполняются:
1. в orchestration/use-case слое;
2. как pre-cache шаг;
3. и только затем в cache передается готовый `write_model`.

То есть: `transform/projection -> cache upsert`, но не `cache -> transform`.

---

## Cache архитектурная модель (Spec / Dsl / Engine / Core)

Для cache используется та же идея слоёв, что и в DSL-подходе, но с поправкой на природу cache:
cache — это lifecycle/infra orchestration, а не row-by-row stage transform.

### 1) `CacheSpec`
Назначение:
1. Pydantic-контракты (`registry/cache/sync/policy`).
2. Описание данных и поведения без runtime-логики.

### 2) `CacheDsl`
Назначение:
1. Компиляция YAML-описаний в runtime-конфиг.
2. Нормализация policy/defaults и подготовка compile-объектов.

### 3) `CacheEngine` (лучше `CacheLifecycleEngine`)
Назначение:
1. Оркестрация сценариев `refresh/status/clear`.
2. Работа с dependency-graph, drift-policy, clear-policy.
3. Координация вызовов только через role-based порты (infra gateway используется лишь во wiring/bootstrap).

Важно:
1. Это command-level engine, а не stage-engine обработки одной записи.

### 4) `CacheCore`
Назначение:
1. Чистая доменная логика lifecycle-решений без SQL/I/O:
   - вычисление порядка выполнения (`depends_on`);
   - вычисление drift-состояния;
   - выбор `rebuild/fail/skip`;
   - выбор clear-scope и каскада.

Важно:
1. `CacheCore` не равен `CacheGateway`.

### 5) `CacheGateway`
Назначение:
1. Infra adapter к конкретному backend (SQLite и др.).
2. Выполнение storage-операций (`ensure`, `upsert`, `meta`, `pending`, `identity`).

Граница:
1. `CacheCore` принимает решения.
2. `CacheGateway` выполняет I/O.

### Резюме границ
1. `Spec + Dsl + LifecycleEngine + Core` — доменно-орchestration часть cache DSL.
2. `Gateway + repositories/backends` — инфраструктурное исполнение.

---

## Infra-first этап (до DSL)

Перед DSL-миграцией фиксируем отдельный подготовительный этап, который закрывает только infra/cache и orchestration-границы.

### Что закрываем на этом этапе
1. Канонизируем runtime-границы:
   - domain/use-case работают только через role-based порты;
   - infra/wiring работает с namespaced gateway.
2. Устраняем прямые зависимости на конкретные infra-классы в use-case/command слое.
3. Централизуем lifecycle:
   - единый путь открытия/закрытия gateway;
   - единая транзакционная граница на уровне gateway/engine.
4. Подтягиваем архитектурные тесты границ:
   - domain/use-case не импортируют `connector.infra.cache.*`;
   - команды/сервисы используют role-based порты.
5. Убираем transitional-ветки, не завязанные на DSL контракт.

### Что не делаем на этом этапе
1. Не вводим новые Pydantic cache DSL specs.
2. Не переводим registry/cache_sync/cache_spec на YAML.
3. Не меняем семантику `refresh/status/clear` ради DSL.

### Критерий готовности Infra-first
1. Все cache-сценарии работают через role-based порты.
2. Gateway остаётся только в infra/wiring lifecycle.
3. Архитектурные тесты стабильно проходят.

---

## Infra-first Execution Plan (детально, без DSL)

Ниже план только по infra/cache и orchestration. YAML/Pydantic/loader для cache DSL в этот план не входят.

Статус:
1. `Plan A` реализован и закрыт в runtime-коде.
2. Legacy на уровне infra-first зоны вычищен; дальнейшая миграция ведётся в `Plan B (DSL)`.

### Фаза 0. Baseline и safety rails
1. Зафиксировать текущее поведение `cache-refresh`, `cache-status`, `cache-clear`.
2. Убедиться, что есть smoke/интеграционные тесты команд.
3. Определить минимальный набор регрессионных тестов перед рефактором.

Файлы и тесты:
1. `tests/test_stage4_cache.py`
2. `tests/test_stage5_api_cache_refresh.py`
3. `tests/architecture/test_cache_layer_boundaries.py`

Done:
1. Базовые cache-команды зелёные на текущем коде.
2. Есть список тестов, которые нельзя ломать на следующих фазах.

### Фаза 1. Role-based границы и lifecycle
1. Проверить, что use-case/commands используют только role-based порты.
2. Зафиксировать единый lifecycle: открытие gateway в wiring, закрытие gateway через единый context-manager.
3. Запретить прямой импорт `connector.infra.cache.*` из domain/usecases.

Файлы:
1. `connector/delivery/commands/cache_refresh.py`
2. `connector/delivery/commands/cache_status.py`
3. `connector/delivery/commands/cache_clear.py`
4. `connector/usecases/cache_command_service.py`
5. `connector/usecases/cache_refresh_service.py`
6. `connector/usecases/cache_status_usecase.py`
7. `connector/usecases/cache_clear_usecase.py`
8. `tests/architecture/test_cache_layer_boundaries.py`

Done:
1. Все runtime вызовы идут через `connector/domain/ports/cache/roles.py`.
2. В CLI добавлен единый `open_cache(...)` lifecycle wrapper (`connector/delivery/cli/bootstrap.py`), команды не управляют `close()` вручную.
3. Архитектурный тест падает при попытке прямого infra-импорта.

### Фаза 2. Транзакционная дисциплина
1. Проверить единую транзакционную точку (`gateway.transaction()`).
2. Исключить вложенные/конкурирующие transaction-path в runtime слоях.
3. Гарантировать, что `cache/admin/identity/pending` работают на одном `sqlite engine`.

Файлы:
1. `connector/infra/cache/cache_gateway.py`
2. `connector/infra/cache/backends/sqlite/engine.py`
3. `connector/infra/cache/roles/*.py`
4. `connector/usecases/cache_refresh_service.py`
5. `connector/usecases/cache_clear_usecase.py`

Done:
1. Один transaction-path на команду.
2. `SqliteEngine.transaction()` явно запрещает вложенные транзакции (`RuntimeError`).
3. Тест на nested transaction добавлен: `tests/cache/test_sqlite_engine_transactions.py`.

### Фаза 3. Централизация чистых правил (без DSL)
1. Вынести чистую policy-логику из use-cases в сценарные классы:
   - `CacheRefreshPlanner`
   - `CacheStatusEvaluator`
   - `CacheClearPlanner`
2. Добавить core-сервисы для переиспользуемых решений:
   - `CacheDependencyGraph`
   - `CacheDriftService`
   - (`CacheScopeResolver`/`CachePolicyResolver` добавляем только при реальной необходимости).
3. Оставить в use-case только:
   - сбор фактов через порты,
   - вызов planner/evaluator,
   - исполнение I/O и отчётность.

Файлы (новые/изменяемые):
1. `connector/domain/cache_core/cache_refresh_planner.py`
2. `connector/domain/cache_core/cache_status_evaluator.py`
3. `connector/domain/cache_core/cache_clear_planner.py`
4. `connector/domain/cache_core/cache_dependency_graph.py`
5. `connector/domain/cache_core/cache_drift_service.py`
6. `connector/domain/cache_core/__init__.py`
7. `connector/usecases/cache_refresh_service.py`
8. `connector/usecases/cache_status_usecase.py`
9. `connector/usecases/cache_clear_usecase.py`
10. `tests/cache_core/test_cache_dependency_graph.py`
11. `tests/cache_core/test_cache_planners.py`
12. `tests/cache_core/test_cache_status_evaluator.py`
13. `tests/cache_core/test_cache_drift_service.py`

Done:
1. Чистая policy-логика вынесена в `domain/cache_core`.
2. Use-case слой сведен к orchestration + I/O через порты.
3. Добавлены unit-тесты чистой логики без SQLite.

### Фаза 4. Legacy cleanup (infra/orchestration только)
1. Удалить transitional кодовые ветки, не относящиеся к DSL.
2. Проверить, что старые helper-paths не используются в runtime.
3. Обновить доки и UML по финальному infra-first состоянию.

Файлы:
1. `docs/Cache_Architecture.md`
2. `docs/Cache_DSL.md`
3. `docs/uml/cache/*`

Done:
1. Удалены ручные lifecycle-ветки в cache-командах, переход на единый `open_cache`.
2. В коде нет transitional вызовов старой cache-factory ветки.
3. Доки синхронизированы с текущей infra-first реализацией.

### Контрольный прогон после каждой фазы
1. `pytest tests/architecture/test_cache_layer_boundaries.py`
2. `pytest tests/test_stage4_cache.py tests/test_stage5_api_cache_refresh.py`
3. Точечные cache/unit тесты из `tests/cache/*`

---

## Два детальных execution-плана

Ниже канонический rollout, разделенный на два независимых плана.

### Plan A: Infra-first (без DSL)

Цель:
1. Довести runtime-границы, lifecycle и транзакционную дисциплину до стабильного состояния.
2. Убрать архитектурные риски до начала DSL cutover.

Фазы:
1. `A0 Baseline`: зафиксировать текущее поведение cache-команд и контрольный тестовый набор.
2. `A1 Boundaries`: запрет прямых infra-import в domain/usecases, только role-based порты.
3. `A2 Lifecycle`: единая схема `open/close/transaction` через gateway.
4. `A3 Core extraction`: вынести чистые решения в сценарные классы и core-сервисы.
5. `A4 Cleanup`: удалить transitional-paths в infra/orchestration зоне и обновить доки/UML.

Основные артефакты:
1. `connector/usecases/cache_refresh_service.py`
2. `connector/usecases/cache_status_usecase.py`
3. `connector/usecases/cache_clear_usecase.py`
4. `connector/domain/ports/cache/roles.py`
5. `connector/infra/cache/cache_gateway.py`
6. `tests/architecture/test_cache_layer_boundaries.py`

Done-гейт Plan A:
1. Все cache use-cases работают через role-based порты.
2. Транзакции и lifecycle централизованы.
3. Архитектурные тесты проходят и защищают границы.

### Plan B: DSL migration (cache specs + runtime)

Цель:
1. Перевести cache schema/sync/policy на декларативную модель (`registry.yml` + `*.cache.yaml`).
2. Убрать кодовый registry и dataset-specific cache adapters.

Фазы:
1. `B0 Contract freeze`
   - финализировать канон `CacheRegistrySpec`, `CacheDatasetSpec`, `CacheSyncSpec`, policy specs;
   - зафиксировать CLI semantics и error mapping (`CACHE_DSL_*`).
2. `B1 Specs + Loader`
   - расширить `connector/domain/dsl/specs.py` под cache-контракты;
   - добавить loader API для registry/dataset cache specs.
3. `B2 Compiler`
   - реализовать compile `raw spec -> runtime CacheSpec/SyncPlan`;
   - включить semantic checks (deps graph, pk/index refs, projection compatibility, soft_delete policy).
4. `B3 Policy + Graph orchestration`
   - реализовать merge policy chain: `defaults -> registry -> dataset overrides -> CLI`;
   - реализовать topological/reverse-topological порядок и зависимые scope (deps/cascade).
5. `B4 Drift + hash`
   - canonical serialization и `schema_hash`;
   - optional `sync_hash` для status/диагностики;
   - strict/soft поведение по `schema_hash` mismatch с `drop+create` в soft.
6. `B5 Runtime integration`
   - перевести `cache-refresh/status/clear` на compiled DSL;
   - внедрить generic `DslCacheSyncAdapter` для sync-проекции.
7. `B6 Cutover + legacy removal`
   - удалить `connector/datasets/cache_registry.py`;
   - удалить dataset-specific cache sync adapters;
   - удалить dev fallback после final cutover.
8. `B7 Verification + docs`
   - unit/architecture/regression тесты;
   - обновить `docs/Cache_DSL.md`, `docs/Cache_Architecture.md`, `docs/uml/cache/*`.

Основные артефакты:
1. `connector/domain/dsl/specs.py`
2. `connector/domain/dsl/loader.py`
3. `connector/domain/dsl/diagnostics.py`
4. `connector/datasets/registry.yml`
5. `datasets/*.cache.yaml`
6. `connector/usecases/cache_refresh_service.py`
7. `connector/usecases/cache_status_usecase.py`
8. `connector/usecases/cache_clear_usecase.py`

Done-гейт Plan B:
1. Runtime не использует кодовый cache registry и dataset-specific sync adapters.
2. Новый dataset cache подключается через YAML без нового Python adapter/spec класса.
3. Drift-поведение и CLI exit semantics соответствуют разделам `Drift-policy` и `CLI Contract`.
4. Включен и зеленый тестовый контур (unit + architecture + stage cache scenarios).

### Рекомендуемый порядок выполнения
1. Полностью закрыть Plan A.
2. Запустить Plan B с `B0` и `B1`.
3. После `B5` пройти промежуточный regression gate.
4. `B6` (удаление legacy) выполнять только после зеленых тестов и проверки команд в dev.

---

## Нейминг сценарных классов (канон)

Для консистентности читаемости фиксируем единый стиль именования для command-level cache orchestration.

### Сценарные классы
1. `CacheRefreshPlanner` — строит refresh-план (scope/deps/drift decisions).
2. `CacheStatusEvaluator` — вычисляет статус-модель (`OK/DEGRADED/...`).
3. `CacheClearPlanner` — строит clear-план (scope/cascade/order).

### Общие доменные сервисы (core package)
1. `CacheDependencyGraph`
2. `CacheDriftService`
3. `CacheScopeResolver` (опционально, по мере роста сложности)
4. `CachePolicyResolver` (опционально, по мере роста сложности)

### Use-case слой
1. `CacheRefreshUseCase`, `CacheStatusUseCase`, `CacheClearUseCase` — orchestration и I/O.
2. Use-case не содержит policy-решений, только сбор фактов, вызов planner/evaluator и исполнение плана через порты.

### Правило нейминга модулей
1. Модули сценариев: `cache_refresh_planner.py`, `cache_status_evaluator.py`, `cache_clear_planner.py`.
2. Модули core-сервисов (минимум): `cache_dependency_graph.py`, `cache_drift_service.py`.
3. Дополнительные core-сервисы при необходимости: `cache_scope_resolver.py`, `cache_policy_resolver.py`.

---

## Cache Rules Model

Набор правил для cache DSL фиксируется отдельно от transform-rules.

### Категории правил
1. `DependencyRules`
   - `depends_on`, `order_hint`, `allow_partial_refresh`.
2. `SchemaRules`
   - `table`, `columns`, `indexes`, `primary_key`, `unique`, service flags.
3. `DriftRules`
   - `mode: strict|soft`,
   - `on_hash_mismatch: fail|rebuild`,
   - `rebuild_scope: dataset|all`.
4. `ClearRules`
   - `cascade_default`,
   - `preserve_service_tables`,
   - `reset_meta_on_clear`.
5. `StatusRules`
   - критерии `OK/DEGRADED/MISSING/BROKEN_DEPENDENCY`,
   - orphan-check policy.
6. `RetentionRules` (опционально)
   - `pending_retention_days`,
   - `identity_retention_days`,
   - `sweep_interval_seconds`.

### Пример YAML-скелета

```yaml
cache:
  policy:
    drift:
      mode: strict
      on_hash_mismatch: fail
      rebuild_scope: dataset
    clear:
      cascade_default: false
      preserve_service_tables: true
      reset_meta_on_clear: true
    status:
      enable_orphan_check: true
      degraded_on_hash_mismatch: true
    retention:
      pending_retention_days: 30
      identity_retention_days: 90
      sweep_interval_seconds: 300

datasets:
  organizations:
    cache_spec: organizations.cache.yaml
    depends_on: []
    order_hint: 10
    allow_partial_refresh: false

  employees:
    cache_spec: employees.cache.yaml
    depends_on: [organizations]
    order_hint: 20
    allow_partial_refresh: false
```

Пример `employees.cache.yaml`:
```yaml
dataset: employees
table: users
schema:
  primary_key: _id
  columns:
    - name: _id
      type: string
      required: true
    - name: login
      type: string
      required: true
    - name: email
      type: string
      required: false
  indexes:
    - name: idx_users_login
      fields: [login]
      unique: false
flags:
  include_deleted: true
```

---

## Cache Sync DSL (миграция адаптеров)

### Состояние после cutover
1. Dataset-specific адаптеры удалены.
2. Реестр адаптеров в коде удален.
3. Runtime строит адаптеры из DSL через `connector/infra/cache/dsl_runtime.py` и generic `DslCacheSyncAdapter`.

Что это дало:
1. rules `key/deleted/projection` переехали в YAML;
2. новый датасет подключается без нового Python adapter класса;
3. для projection используется единый набор DSL ops.

### Целевая модель
1. Оставить runtime-контракт `CacheSyncAdapterProtocol`.
2. Заменить dataset-specific классы на один generic `DslCacheSyncAdapter`.
3. Dataset-специфику перенести в YAML (`*.cache.yaml`, секция `sync`):
   - `dataset`
   - `list_path`
   - `report_entity`
   - `item_key` правило
   - `is_deleted` правило
   - `projection` в cache write-model.
   - канон: секция `sync` внутри `*.cache.yaml`;
   - отдельный `*.cache_sync.yaml` допустим только как transitional-совместимость до cutover.
4. Кодовый `cache_registry.py` уже удален (выполнено).

### Границы ответственности
1. `DslCacheSyncAdapter` работает в orchestration-слое cache-refresh.
2. `SqliteCacheGateway` и репозитории остаются без DSL-логики.
3. Поток: `target payload -> DslCacheSyncAdapter -> write_model -> cache upsert`.

### План перехода без риска
1. Ввести generic `DslCacheSyncAdapter`.
2. Перевести сначала `organizations` (минимальная сложность).
3. Перевести `employees` с полным паритетом полей/правил.
4. Удалить legacy адаптеры и кодовый registry.

---

## Cache Sync Ops Policy

### Ops, которые переиспользуются из dsl-core
1. `coalesce`
2. `default_if_null`
3. `to_string`
4. `to_int`
5. `to_bool` (или эквивалент)
6. `trim`
7. `lowercase` / `uppercase`
8. `parse_date` / `to_iso8601` (при необходимости)

### Ops, которые добавляются как универсальные
1. `pick_first` — первое непустое значение из списка полей.
2. `required` — fail/issue при пустом обязательном поле.
3. `normalize_text` — каноническая нормализация текстовых полей.
4. `to_bool_int` — приведение bool-представлений к `0/1`.
5. `build_delimited_key` — универсальная сборка составного ключа.
6. `deleted_when` — декларативная логика soft-delete.
7. `from_path` (опционально) — чтение вложенных полей по пути.

### Ограничения
1. Имена ops не должны быть dataset-specific.
2. Ops для cache-sync не превращаются в validate-движок.
3. Если логика нужна только одному датасету и не повторяется, сначала проверяем, стоит ли вообще выносить её в op.

---

## Набор Pydantic Specs (канон)

Этот раздел фиксирует целевой набор Pydantic-моделей для cache DSL.

### A) Registry-level specs

1. `CacheRegistrySpec`
- Назначение: корневой контракт реестра cache-конфигураций.
- Поля:
  - `version: int`
  - `policy: CachePolicySpec`
  - `datasets: dict[str, CacheRegistryDatasetSpec]`

2. `CacheRegistryDatasetSpec`
- Назначение: описание одного dataset в registry.
- Поля:
  - `cache_spec: str` — путь до `*.cache.yaml`
  - `depends_on: list[str] = []`
  - `order_hint: int = 100`
  - `allow_partial_refresh: bool = False`
  - `enabled: bool = True`

3. `CachePolicySpec`
- Назначение: общие политики поведения cache-команд.
- Поля:
  - `drift: DriftPolicySpec`
  - `clear: ClearPolicySpec`
  - `status: StatusPolicySpec`
  - `retention: RetentionPolicySpec | None`

4. `DriftPolicySpec`
- Назначение: поведение при рассинхроне DSL-спеки и БД.
- Поля:
  - `mode: Literal["strict", "soft"]`
  - `on_hash_mismatch: Literal["fail", "rebuild"]`
  - `rebuild_scope: Literal["dataset", "all"]`

5. `ClearPolicySpec`
- Назначение: поведение `cache-clear`.
- Поля:
  - `cascade_default: bool`
  - `preserve_service_tables: bool`
  - `reset_meta_on_clear: bool`

6. `StatusPolicySpec`
- Назначение: поведение `cache-status`.
- Поля:
  - `enable_orphan_check: bool`
  - `degraded_on_hash_mismatch: bool`

7. `RetentionPolicySpec`
- Назначение: политики очистки runtime-данных.
- Поля:
  - `pending_retention_days: int | None`
  - `identity_retention_days: int | None`
  - `sweep_interval_seconds: int | None`

### B) Dataset cache schema specs

1. `CacheDatasetSpec`
- Назначение: декларативный контракт snapshot-таблицы dataset.
- Поля:
  - `dataset: str`
  - `table: str`
  - `schema: CacheTableSchemaSpec`
  - `sync: CacheSyncSpec | None = None`
  - `flags: CacheDatasetFlagsSpec = ...`
  - `policy_overrides: CacheDatasetPolicyOverridesSpec | None = None`

2. `CacheTableSchemaSpec`
- Назначение: схема таблицы и индексов.
- Поля:
  - `primary_key: str`
  - `columns: list[CacheColumnSpec]`
  - `indexes: list[CacheIndexSpec] = []`

3. `CacheColumnSpec`
- Назначение: описание колонки snapshot-таблицы.
- Поля:
  - `name: str`
  - `type: Literal["string", "int", "float", "bool", "datetime", "json"]`
  - `required: bool = False`
  - `default: Any | None = None`

Type mapping (DSL -> SQLite):
1. `string` -> `TEXT`
2. `int` -> `INTEGER`
3. `float` -> `REAL`
4. `bool` -> `INTEGER` (0/1)
5. `datetime` -> `TEXT` (ISO-8601)
6. `json` -> `TEXT` (serialized JSON)

4. `CacheIndexSpec`
- Назначение: индекс таблицы.
- Поля:
  - `name: str`
  - `fields: list[str]`
  - `unique: bool = False`

5. `CacheDatasetFlagsSpec`
- Назначение: служебные флаги dataset.
- Поля:
  - `include_deleted: bool = False`

6. `CacheDatasetPolicyOverridesSpec`
- Назначение: dataset-level overrides поверх `registry.policy`.
- Поля:
  - `drift: DriftPolicySpec | None`
  - `clear: ClearPolicySpec | None`
  - `status: StatusPolicySpec | None`
  - `retention: RetentionPolicySpec | None`

### C) Cache sync specs (внутри `CacheDatasetSpec.sync`)

1. `CacheSyncSpec`
- Назначение: контракт преобразования payload из target в cache write-model.
- Поля:
  - `dataset: str`
  - `list_path: str`
  - `report_entity: str`
  - `item_key: ValueExprSpec`
  - `is_deleted: ValueExprSpec | None`
  - `soft_delete: SoftDeleteSpec | None`
  - `projection: list[CacheProjectionRuleSpec]`

2. `CacheProjectionRuleSpec`
- Назначение: правило проекции поля в cache write-model.
- Поля:
  - `target: str`
  - `source: str | list[str] | None`
  - `ops: list[OperationSpec] = []`
  - `required: bool = False`
  - `on_error: Literal["error", "warning", "skip", "set_null"] = "error"`

3. `SoftDeleteSpec`
- Назначение: декларативное описание soft-delete без дублирования runtime-логики.
- Поля:
  - `mode: Literal["any_of", "all_of"] = "any_of"`
  - `rules: list[SoftDeleteRuleSpec]`

4. `SoftDeleteRuleSpec` (минимальный набор)
- `field_equals`:
  - `field: str`
  - `value: Any`
  - `normalize: list[str] = []` (например: `["trim", "lowercase"]`)
- `field_not_null`:
  - `field: str`

### D) Compile-time правило для soft-delete

1. В runtime используется только `is_deleted`.
2. Если задан `soft_delete`, компилятор обязан преобразовать его в `is_deleted`-выражение.
3. Одновременное задание `is_deleted` и `soft_delete`:
   - либо запрещаем (ошибка compile),
   - либо объявляем явный приоритет.
4. Рекомендуемый канон: запрещать совместное использование, чтобы избежать неявной логики.

### E) Что валидирует Pydantic, а что компилятор

1. Pydantic:
- структура YAML;
- типы полей;
- обязательные/enum значения.

2. Compiler/semantic validation:
- граф `depends_on` (cycles/missing deps);
- корректность `primary_key` и `indexes.fields`;
- уникальность имен колонок/индексов;
- совместимость `projection.target` с `CacheDatasetSpec.schema.columns`;
- политика `soft_delete` vs `is_deleted`.

---

## Поведенческая матрица (refresh/status/clear)

Этот раздел фиксирует целевую операционную семантику cache DSL.

### Глобальные правила
1. Источник истины для dataset cache — `datasets/registry.yml` + `datasets/*.cache.yaml`.
2. Любая операция сначала валидирует registry/spec.
3. Порядок исполнения всегда topological (`depends_on`, `order_hint` только tie-break).
4. Service schema (`meta`, `identity_index`, `pending_links`, `identity_runtime_state`) не удаляется в dataset-операциях.

### `cache-refresh`

#### Режимы вызова
1. `cache-refresh` (без `--dataset`):
   - обрабатывает все датасеты из registry в topological порядке.
2. `cache-refresh --dataset X`:
   - по умолчанию включает зависимости `X` (режим `with_deps=true`).
   - `--no-deps` отключает автодогрузку зависимостей (экспертный режим).

#### Поведение
1. Валидирует registry/spec.
2. Применяет service schema migrations (если нужны).
3. Для каждого dataset:
   - ensure dataset schema по DSL;
   - проверка `schema_hash`;
   - при mismatch:
     - `strict`: ошибка, refresh для dataset не выполняется;
     - `soft`: rebuild snapshot-таблицы dataset и запись нового hash.
4. Обновляет dataset meta (`last_refresh_at`, `schema_hash`, `row_count`; optional `sync_hash`).

#### Что не делает
1. Не очищает `pending_links`, `identity_index` и `identity_runtime_state` автоматически.
2. Не удаляет dataset, отсутствующие в текущем запуске (если вызов точечный).

### `cache-status`

#### Режимы вызова
1. `cache-status`:
   - показывает все датасеты из registry и service schema.
2. `cache-status --dataset X`:
   - показывает состояние только X + его dependencies summary.

#### Состояния dataset
1. `OK`:
   - таблица существует, schema валидна, `schema_hash` совпадает.
2. `DEGRADED`:
   - таблица есть, но `schema_hash` mismatch или частичное несоответствие индексов/колонок.
3. `MISSING`:
   - dataset объявлен в registry, но таблица отсутствует.
4. `INVALID_SPEC`:
   - YAML невалиден или отсутствует обязательная часть spec.
5. `BROKEN_DEPENDENCY`:
   - зависимость датасета отсутствует/невалидна/в цикле.

#### Дополнительно в статусе
1. Признак циклов/ошибок графа зависимостей.
2. Признак `orphan` таблиц (есть в БД, но нет в registry).
3. Сервисные метрики (`pending_count`, `identity_count`) как справочная секция.

### `cache-clear`

#### Режимы вызова
1. `cache-clear`:
   - очищает snapshot-таблицы всех датасетов из registry в reverse-topological порядке.
2. `cache-clear --dataset X`:
   - по умолчанию очищает только X.
   - `--cascade` очищает X и все зависимые datasets (dependents).

#### Поведение
1. Удаляет/очищает только dataset snapshot-данные.
2. Service schema сохраняется.
3. Для очищенных datasets сбрасывает dataset-мета (`last_refresh_at`, `row_count`, `schema_hash`, optional `sync_hash`).

#### Что не делает
1. Не удаляет записи `pending_links`/`identity_index`/`identity_runtime_state` для других датасетов.
2. Не удаляет service tables.

### Drift-policy (унифицировано для команд)
1. `strict`:
   - `refresh`: fail fast на mismatch.
   - `status`: `DEGRADED/INVALID_SPEC`.
   - `clear`: выполняется только при валидном registry/spec; при DSL/config ошибке — fail fast (`exit 2`).
2. `soft`:
   - `refresh`: auto-rebuild dataset snapshot на mismatch.
   - `status`: `DEGRADED` с рекомендацией refresh.
   - `clear`: выполняется только при валидном registry/spec; режим `soft` не понижает DSL/config ошибки.

### Ошибки и диагностические коды (целевые)
1. `CACHE_DSL_REGISTRY_INVALID`
2. `CACHE_DSL_SPEC_INVALID`
3. `CACHE_DSL_DEP_CYCLE`
4. `CACHE_DSL_DEP_MISSING`
5. `CACHE_DSL_HASH_MISMATCH`
6. `CACHE_SCHEMA_ENSURE_FAILED`
7. `CACHE_SCHEMA_REBUILD_FAILED`

Все ошибки маппятся в `DiagnosticItem(stage=CACHE)`.

---

## CLI Contract (точные флаги и дефолты)

Этот раздел фиксирует внешний контракт CLI для cache DSL.

### Общие флаги для cache-команд
1. `--dataset <name>`:
   - ограничивает операцию одним dataset.
2. `--strict/--no-strict`:
   - переопределяет глобальный diagnostics/cache strict-режим.
3. `--format table|json` (для status):
   - формат вывода.

### `cache-refresh` (контракт)
1. Синтаксис:
   - `cache-refresh`
   - `cache-refresh --dataset employees`
   - `cache-refresh --dataset employees --no-deps`
2. Флаги:
   - `--dataset <name>`
   - `--deps/--no-deps` (default: `--deps`)
   - `--strict/--no-strict` (default: из settings)
3. Дефолты:
   - без dataset: refresh всех datasets;
   - с dataset: refresh dataset + dependencies.
4. Exit semantics:
   - `0`: refresh выполнен;
   - `2`: DSL/config error (`CACHE_DSL_*`);
   - `3`: schema/runtime error (`CACHE_SCHEMA_*`).

### `cache-status` (контракт)
1. Синтаксис:
   - `cache-status`
   - `cache-status --dataset employees`
   - `cache-status --format json`
2. Флаги:
   - `--dataset <name>`
   - `--format table|json` (default: `table`)
   - `--strict/--no-strict` (влияет на итоговый код возврата при деградации)
3. Дефолты:
   - показывает все datasets + service schema summary.
4. Exit semantics:
   - `0`: все `OK`;
   - `1`: есть `DEGRADED/MISSING/BROKEN_DEPENDENCY` (операция не упала, но система не в green);
   - `2`: DSL/config error (`CACHE_DSL_*`).

### `cache-clear` (контракт)
1. Синтаксис:
   - `cache-clear`
   - `cache-clear --dataset employees`
   - `cache-clear --dataset organizations --cascade`
2. Флаги:
   - `--dataset <name>`
   - `--cascade` (default: `false`)
   - `--strict/--no-strict`
3. Дефолты:
   - без dataset: clear всех snapshot datasets в reverse-topological порядке;
   - с dataset без cascade: clear только выбранного dataset.
4. Exit semantics:
   - `0`: clear завершен;
   - `2`: DSL/config error (`CACHE_DSL_*`);
   - `3`: runtime clear error.

### Политика совместимости и перехода
1. До завершения миграции допустим fallback на кодовый registry только в dev-режиме, с warning.
2. После finalize:
   - fallback отключается;
   - отсутствие/невалидность YAML registry/spec считается ошибкой запуска.

---

## Черновой YAML-контракт (минимум)

### `datasets/registry.yml`
```yaml
version: 1
policy:
  drift:
    mode: strict
    on_hash_mismatch: fail
    rebuild_scope: dataset
  clear:
    cascade_default: false
    preserve_service_tables: true
    reset_meta_on_clear: true
  status:
    enable_orphan_check: true
    degraded_on_hash_mismatch: true
  retention: null

datasets:
  organizations:
    cache_spec: organizations.cache.yaml
    depends_on: []
    order_hint: 10
  employees:
    cache_spec: employees.cache.yaml
    depends_on: [organizations]
    order_hint: 20
```

### `datasets/employees.cache.yaml`
```yaml
dataset: employees
table: users
schema:
  primary_key: _id
  columns:
    - name: _id
      type: string
      required: true
    - name: login
      type: string
      required: true
    - name: email
      type: string
      required: false
  indexes:
    - name: idx_users_login
      fields: [login]
      unique: false
sync:
  list_path: users
  report_entity: users
  item_key:
    source: _id
    ops: [to_string]
  is_deleted:
    source: is_deleted
    ops: [to_bool]
  projection:
    - target: _id
      source: _id
      required: true
      on_error: error
      ops: [to_string]
    - target: login
      source: login
      required: true
      on_error: error
      ops: [trim]
flags:
  include_deleted: true
policy_overrides: {}
```

Примечание: точный набор полей (`type`, `required`, `flags`, `policy_overrides`) доуточняется при реализации компилятора.

---

## План внедрения (кратко, факт)
1. **Infra-first**: зафиксировать role-based границы, lifecycle gateway и архитектурные тесты.
2. Ввести Pydantic cache-spec в `domain/dsl/specs.py`.
3. Добавить loader функции для `registry.yml` и `*.cache.yaml`.
4. Реализовать компиляцию YAML -> `CacheSpec`.
5. Перевести `build_cache()` на loader/compile путь и runtime bundle (`dsl_runtime`).
6. Убрать legacy `connector/datasets/cache_registry.py`, `load/cache_spec.py`, `load/cache_sync_adapter.py`.
7. Оставить в SQLite schema только service schema миграции (в процессе: остался `_migrate_to_v2`).
8. Добавить `schema_hash` в `meta` и проверку drift (optional `sync_hash` для статуса).
9. Добавить архитектурные тесты границ и порядка.

---

## Критерии завершения
1. Добавление нового dataset cache не требует изменений в cache infra/registry/handlers (обычно только YAML + регистрация; в редких случаях — добавление универсальной op).
2. Порядок определяется зависимостями, а не ручным hardcode.
3. В schema-модулях нет dataset-specific SQL.
4. Drift между DSL и БД обнаруживается детерминированно.
5. Домен/use-case не зависит от infra gateway напрямую.

---

## Execution Checklist (оформлено, без реализации)

### A) Решения, которые надо финализировать до старта реализации
1. Финальный layout `*.cache.yaml`:
   - подтверждаем разделы `schema/sync/flags/policy_overrides`;
   - фиксируем обязательные поля и default-значения.
2. Приоритет политик:
   - `defaults -> registry.policy -> dataset.policy_overrides -> CLI flags`.
3. Контракт hash:
   - canonical JSON (sorted keys, stable serialization);
   - `schema_hash` хранится в `meta` и управляет drift/rebuild;
   - optional `sync_hash` хранится отдельно для статуса/диагностики;
   - поведение на `schema_hash` mismatch по `strict/soft`.
4. Rebuild semantics при drift:
   - фиксировано: `drop+create` для dataset snapshot-таблицы;
   - `truncate+ensure` не используется как drift-strategy;
   - service schema (`pending_links`, `identity_index`, `identity_runtime_state`, `meta`) не затрагивается;
   - dataset meta (`row_count`, `last_refresh_at`) пересчитывается после rebuild, `schema_hash` обновляется.
5. Поведение команд с зависимостями:
   - `cache-refresh --dataset X`: default `--deps`;
   - `cache-clear --dataset X`: default без каскада, `--cascade` для dependents.
6. Loader API формально:
   - фиксировано: loader работает через `raise DslLoadError`;
   - `DslIssue` формируется на уровне orchestration/diagnostics-adapter;
   - список `CACHE_DSL_*` кодов задается на каждом failure point.
7. Semantic compile checks (обязательный минимум):
   - dep cycles/missing deps;
   - pk/index field refs;
   - projection target compatibility;
   - правило `soft_delete` vs `is_deleted`.
   - фиксировано: перечисленные нарушения считаются `error` (fail-fast).
   - `warning` используется для observational проблем (например, orphan tables в status).
8. План отключения legacy:
   - `datasets/cache_registry.py` удален;
   - `datasets/*/load/cache_sync_adapter.py` удалены;
   - временный dev-fallback удален после cutover.

### B) Что считаем done по миграции cache DSL
1. Runtime не использует кодовый registry/adapters для dataset cache/sync.
2. Новая cache-интеграция датасета:
   - добавляется через YAML + запись в `registry.yml`;
   - без изменений в cache infra/registry/handlers (в редких случаях допускается добавление универсальной op).
3. Все три cache-сценария (`refresh/status/clear`) работают по DSL-конфигу.
4. Drift контроль (`schema_hash`) включен и покрыт тестами для `strict` и `soft` (optional `sync_hash` для status-only).
5. CLI flags и defaults соответствуют разделу `CLI Contract` в этом документе.
6. Архитектурные тесты проверяют:
   - отсутствие прямого domain/use-case доступа к infra cache classes;
   - отсутствие legacy путей после cutover.
7. Удалены transitional модули и обратная совместимость, если это зафиксировано для текущего этапа.

### C) Выходные артефакты по завершению
1. Обновленные доки:
   - `docs/Cache_DSL.md`
   - `docs/Cache_Architecture.md`
2. Обновленные UML по cache DSL/runtime.
3. Набор unit + architecture tests на новый контракт.
