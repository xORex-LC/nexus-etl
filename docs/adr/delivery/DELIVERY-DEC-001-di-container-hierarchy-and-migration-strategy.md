# DELIVERY-DEC-001: Иерархия DI-контейнеров и стратегия поэтапной миграции CLI

> **Статус**: Принято — реализация по шагам DELIVERY-DEC-002…007
> **Дата принятия**: 2026-02-21
> **Решает проблему**: [DELIVERY-PROBLEM-001](./DELIVERY-PROBLEM-001-manual-wiring-no-composition-root.md)
> **Участники решения**: @xorex

---

## 📋 Контекст

CLI-приложение имеет `SqliteContainer`, объявленный в `containers.py`, но никем не используемый: все 11 команд обходят его через функции `build_cache()`, `ensure_vault_startup_ready()` и т.д. В результате — 3× открытие vault engine в `import-apply`, `resolver_settings` в командах без planning-стадий, монолитная `build_pipeline_context()`, 8 независимых точек `gateway.close()`. Подробно — в [DELIVERY-PROBLEM-001](./DELIVERY-PROBLEM-001-manual-wiring-no-composition-root.md).

---

## 🎯 Решение

Построить единый `AppContainer` как Composition Root (CR) поверх существующего `SqliteContainer`, добавив три новых субконтейнера: `CacheContainer`, `VaultContainer`, `TargetContainer`. CR создаётся в `run_with_report()`, инициализирует только нужные ресурсы через `_init_container_for_requirements()`, команды получают зависимости через `ctx.container.*`. Все lifecycle ресурсов — container-managed.

Миграция выполняется в **6 шагов** (каждый — отдельный DELIVERY-DEC), сохраняя обратную совместимость на каждом промежуточном этапе.

---

## 🏗️ Архитектурное решение

### Целевая иерархия контейнеров

```
AppContainer  ← единственный CR, создаётся в run_with_report()
├── SqliteContainer     — 3 SQLite движка + startup schemas
├── CacheContainer      — SqliteCacheGateway + SqliteCacheRolePorts
├── VaultContainer      — cipher + services + repository
└── TargetContainer     — httpx.Client + TargetGateway lifecycle
```

`PipelineContainer` (TRANSFORM-DEC-003) — отдельный шаг для transform-слоя, не входит в этот план.

### Принципы деления на контейнеры

- **По инфра-ресурсу**: один ресурс с lifecycle — один субконтейнер
- **НЕ по слою**: нет `DomainContainer` или `UsecasesContainer` — бизнес-объекты не требуют DI
- **Один CR**: `AppContainer` создаётся только в `run_with_report()`, не в command handlers

### Сводная таблица провайдеров

| Объект | Provider | Обоснование |
|--------|----------|-------------|
| `SqliteEngine` (×3) | `Singleton` + `Resource`-генератор | Один движок на invocation; schema init + `engine.close()` при teardown |
| `SqliteCacheGateway` | `Resource` | Имеет `close()`; `owns_connection=False` — lifecycle у SqliteContainer |
| `SqliteCacheRolePorts` | `Singleton` | Frozen dataclass-адаптер, lifecycle нет |
| `SqliteVaultRepository` | `Singleton` | Thin wrapper, lifecycle у engine |
| `FernetEnvelopeCipher` | `Singleton` | Stateless |
| `EnvVaultKeyProvider` | `Singleton` | Читает ENV один раз |
| `SecretLocatorService` | `Singleton` | Stateless |
| `SecretVaultReadService` | `Factory` | Per-invocation (`default_run_id`), не переиспользуется |
| `SecretVaultWriteService` | `Factory` | Условный (vault_enabled) |
| `VaultRetentionService` | `Factory` | Условный (vault_enabled) |
| `TargetRuntimeBuildResult` | `Resource` | Обёртка над `build_target_runtime_with_info()`; lifecycle: `runtime.close()` при teardown |
| `AppSettings` | `Dependency` | Внешний ввод, загружается до создания контейнера |
| `SqliteSettings` | `Singleton` | Читает ENV один раз |

### Условная инициализация ресурсов

```python
def _init_container_for_requirements(container: AppContainer, req: Requirements) -> None:
    if req.requires_cache:
        container.sqlite.cache_ready.init()
        container.sqlite.identity_ready.init()
        container.cache.gateway.init()
    if req.requires_vault_init:
        container.sqlite.vault_ready.init()   # VaultStartupGuard внутри
    if req.requires_api:
        container.target.runtime.init()
```

`requires_vault_init` — **статический флаг** в `Requirements`: vault-команды (`enrich`, `import-plan`, `import-apply`) всегда инициализируют vault engine при старте. Команды без vault (`normalize`, `match`, `resolve` и др.) не имеют этого флага — vault engine **никогда не открывается** для них.

### AppContainer: структура

```python
class AppContainer(containers.DeclarativeContainer):
    app_settings = providers.Dependency(instance_of=AppSettings)

    # Вспомогательные слайсы (Callable, не Singleton — работают как property)
    _sqlite_cfg   = providers.Singleton(SqliteSettings)
    _cache_dir    = providers.Callable(lambda s: s.paths.cache_dir, s=app_settings)
    _api_settings = providers.Callable(lambda s: s.api, s=app_settings)
    _cache_dsl    = providers.Singleton(load_cache_dsl_runtime)
    _cache_specs  = providers.Callable(lambda b: b.cache_specs, b=_cache_dsl)

    sqlite = providers.Container(SqliteContainer,
        settings=_sqlite_cfg, cache_dir=_cache_dir, cache_specs=_cache_specs)

    cache = providers.Container(CacheContainer,
        cache_engine=sqlite.cache_engine,
        identity_engine=sqlite.identity_engine,
        cache_specs=_cache_specs)

    vault = providers.Container(VaultContainer,
        vault_engine=sqlite.vault_engine)

    target = providers.Container(TargetContainer,
        api_settings=_api_settings,
        transport=providers.Object(None))
```

### Что намеренно остаётся вне DI

| Объект | Причина |
|--------|---------|
| `AppSettings` | Загружается до создания контейнера; bootstrapping paradox |
| `ErrorCatalog` | Stateless lookup table, нет lifecycle |
| `DatasetSpec` registry | Simple dict + factory, stateless |
| UseCase objects | Stateless coordinators; конструируются с scalar параметрами |
| `PipelineContext` / `build_pipeline_context()` | Frozen dataclass без lifecycle; остаётся до TRANSFORM-DEC-003 |

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **Vault engine 1× вместо 3×**: `vault_engine` — `Singleton` в `SqliteContainer`; `VaultStartupGuard`, `SecretVaultReadService` и `VaultRetentionService` используют один движок
- ✅ **Декларативный lifecycle**: порядок teardown управляется `shutdown_resources()`, не ручными `try/finally`
- ✅ **Условная инициализация**: `normalize` не инициализирует vault и target — ресурсы не открываются
- ✅ **Testability**: unit-тест переопределяет нужные провайдеры через `.override()`; не нужно поднимать полный граф
- ✅ **Forward compatibility**: новая capability → новый провайдер в нужном субконтейнере; команды, которые не используют, не меняются

**Недостатки (компромиссы)**:
- ⚠️ Поэтапная миграция 11 команд — значительный объём работы; компенсируется изоляцией шагов и обратной совместимостью
- ⚠️ `providers.Dependency` для optional значений требует явного `.override(None)` в тестах

**Альтернативы, которые отклонили**:
- ❌ **Per-profile utility функции (Вариант A)**: снижает симптомы, root cause остаётся — ручной lifecycle, дублирование wiring
- ❌ **Per-command фабрики**: максимальная изоляция, но дублирование; консистентность трудно поддерживать

---

## 🛠️ Реализация

### Стратегия 6 шагов

| Шаг | ADR | Что меняется | Результат |
|-----|-----|-------------|---------|
| 1 | [DELIVERY-DEC-002](./DELIVERY-DEC-002-sqlitecontainer-as-engine-lifecycle-owner.md) | `build_cache()` делегирует `SqliteContainer` | SqliteContainer используется, engines container-managed |
| 2 | [DELIVERY-DEC-003](./DELIVERY-DEC-003-vault-container-single-vault-engine.md) | `VaultContainer`; `vault_ready` поглощает `VaultStartupGuard`; `_VaultReadProviderRuntime` / `_VaultRetentionRuntime` удаляются | Vault engine открывается 1× вместо 3× |
| 3 | [DELIVERY-DEC-004](./DELIVERY-DEC-004-cache-container-gateway-roles.md) | `CacheContainer`; `build_cache()` deprecates | 8 точек `gateway.close()` → container teardown |
| 4 | [DELIVERY-DEC-005](./DELIVERY-DEC-005-target-container-runtime-lifecycle.md) | `TargetContainer`; `build_target_runtime_with_info()` deprecates | `try/finally runtime.close()` → container teardown |
| 5 | [DELIVERY-DEC-006](./DELIVERY-DEC-006-app-container-composition-root-integration.md) | `AppContainer`; `run_with_report()` как CR; `CommandContext.container`; команды мигрируют | Единый CR; handlers без `try/finally` |
| 6 | [DELIVERY-DEC-007](./DELIVERY-DEC-007-remove-manual-wiring-utilities.md) | Удаление `build_cache()`, `ensure_vault_startup_ready()` и др. | `containers.py` — только декларации |

### Ключевые файлы

| Файл | Роль в миграции |
|------|----------------|
| `connector/delivery/cli/containers.py` | Все новые контейнеры объявляются здесь; utility functions удаляются по шагам |
| `connector/delivery/cli/runtime.py` | `run_with_report()` — точка создания AppContainer и `shutdown_resources()` |
| `connector/delivery/cli/context.py` | `CommandContext` получает `container: AppContainer \| None` |
| `connector/delivery/commands/import_apply.py` | Самый сложный случай (4 lifecycle); canonical before/after |
| `connector/delivery/commands/normalize.py` | Простейший случай; первым мигрирует на Шаге 5 |

### Инварианты

1. **Один CR**: `AppContainer()` создаётся только в `run_with_report()`, никогда в command handlers
2. **Один vault engine**: `SqliteContainer.vault_engine` — Singleton; все vault-сервисы получают один экземпляр
3. **Статичный vault init**: `vault_ready.init()` вызывается для команд с `req.requires_vault_init=True` (enrich, import-plan, import-apply); решение принимается при регистрации команды, не в runtime
4. **`owns_connection=False`**: `CacheContainer.gateway` не закрывает engines (lifecycle у `SqliteContainer`)

---

## 🧪 Валидация решения

**Тесты (по шагам)**:
- ✅ После Шага 1: `test_build_cache_uses_sqlite_container()` — SqliteContainer инициализируется и teardown работает
- ✅ После Шага 2: `test_vault_container_single_engine()` — один engine shared между guard + read + retention
- ✅ После Шага 3: `test_cache_container_gateway_teardown()` — `gateway.close()` вызывается при `shutdown_resources()`
- ✅ После Шага 4: `test_target_container_runtime_lifecycle()` — `runtime.close()` вызывается при `shutdown_resources()`
- ✅ После Шага 5: `test_normalize_handler_no_try_finally()` — handler не содержит явных `close()` или `try/finally`
- ✅ После Шага 6: `grep -r "build_cache\|open_cache" connector/delivery/commands/` — пусто

**Финальный критерий**: `import_apply.py` не содержит ни одного явного `close()` или `try/finally` для lifecycle ресурсов.

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- `PipelineContainer` (TRANSFORM-DEC-003) — отдельный шаг, не входит в данный план; `build_pipeline_context()` остаётся до завершения трансформ-рефактора
- Условная инициализация через `_init_container_for_requirements()` требует явного указания `Requirements` для каждой команды

**Риски**:
- ⚠️ Команда забывает вызвать `vault_ready.init()` до запроса vault-сервиса → runtime error при первом использовании
  - **Митигация**: Явные integration-тесты каждой команды; `Dependency(instance_of=...)` даёт понятный error
- ⚠️ `shutdown_resources()` вызывается в `finally` — если ресурс не был инициализирован, зависит от поведения библиотеки
  - **Митигация**: Тест полного lifecycle для каждого субконтейнера

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `containers.py` | Основной файл изменений | Новые контейнеры; utility functions удаляются по шагам |
| `runtime.py` | CR точка | `run_with_report()` создаёт AppContainer, вызывает init/shutdown |
| `context.py` | Пробрасывает CR | `CommandContext.container: AppContainer \| None` |
| 11 command handlers | Постепенный рефактор | Переход от `build_cache()` к `ctx.container.cache.*` |
| `import_apply.py` | Наибольшее изменение | 4 lifecycle → container-managed; 3-уровневый `try/finally` → `shutdown_resources()` |
| `normalize.py` | Минимальное изменение | Первым мигрирует; убирается `try/finally gateway.close()` |

---

## 🔗 Связанные документы

- [DELIVERY-PROBLEM-001](./DELIVERY-PROBLEM-001-manual-wiring-no-composition-root.md) — решаемая проблема
- [DELIVERY-DEC-002](./DELIVERY-DEC-002-sqlitecontainer-as-engine-lifecycle-owner.md) — Шаг 1
- [DELIVERY-DEC-003](./DELIVERY-DEC-003-vault-container-single-vault-engine.md) — Шаг 2
- [DELIVERY-DEC-004](./DELIVERY-DEC-004-cache-container-gateway-roles.md) — Шаг 3
- [DELIVERY-DEC-005](./DELIVERY-DEC-005-target-container-runtime-lifecycle.md) — Шаг 4
- [DELIVERY-DEC-006](./DELIVERY-DEC-006-app-container-composition-root-integration.md) — Шаг 5
- [DELIVERY-DEC-007](./DELIVERY-DEC-007-remove-manual-wiring-utilities.md) — Шаг 6
- [TRANSFORM-DEC-003](../transform/TRANSFORM-DEC-003-pipeline-container-lazy-stage-assembly.md) — PipelineContainer (смежный, отдельный шаг)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-21 | Решение предложено и принято |
| 2026-02-21 | Зафиксирована стратегия 6 шагов; каждый шаг описан в отдельном DELIVERY-DEC |
| 2026-02-21 | Обновлено: TargetKernel Singleton убран (Resource оборачивает build_target_runtime_with_info целиком); requires_vault → requires_vault_init (статический флаг) |
