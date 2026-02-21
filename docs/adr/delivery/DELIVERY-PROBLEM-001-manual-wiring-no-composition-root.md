# DELIVERY-PROBLEM-001: Ручной wiring без Composition Root — разрозненное управление lifecycle

> **Статус**: Открыта — решение зафиксировано в [DELIVERY-DEC-001](./DELIVERY-DEC-001-di-container-hierarchy-and-migration-strategy.md)
> **Дата создания**: 2026-02-21
> **Затронутые компоненты**: `connector/delivery/cli/containers.py`, `connector/delivery/cli/runtime.py`, `connector/delivery/commands/*.py`

---

## 📋 Контекст

CLI-приложение включает 11 команд: `normalize`, `enrich`, `map`, `match`, `resolve`, `import-plan`, `import-apply`, `cache-clear`, `cache-status`, `cache-refresh`, `check-api`. Каждая из них требует различного набора инфраструктурных зависимостей: SQLite-движков, vault-сервисов, HTTP-клиента к внешнему API.

Проект уже использует библиотеку `dependency-injector`: `SqliteContainer` объявлен в `containers.py` с корректной структурой (Singleton engines + Resource providers). Однако **ни одна из 11 команд его не использует** — все обходят контейнер через вспомогательные функции: `build_cache()`, `open_cache()`, `ensure_vault_startup_ready()`, `open_secret_store()`, `build_target_runtime_with_info()`.

В итоге 90% объектного графа собирается вручную в каждом command handler: одни и те же паттерны дублируются, lifecycle ресурсов управляется через `try/finally` в handler'ах, а capabilities растут с ростом числа параметров в `build_pipeline_context()`.

---

## ⚠️ Проблема

Отсутствует единый Composition Root. Вместо него — набор utility-функций, каждая из которых самостоятельно открывает и закрывает инфра-ресурсы. Это приводит к следующим проблемам:

1. **Vault engine открывается 3 раза** в `import-apply`: `_VaultReadProviderRuntime`, `_VaultRetentionRuntime` и `ensure_vault_startup_ready()` каждый открывает свой SQLite-движок независимо.
2. **`resolver_settings` протекает в команды**, которым он не нужен: `normalize`, `enrich`, `mapping` передают `resolver_settings=app_settings.resolver` в `build_pipeline_context()`, но planning-стадии не используют.
3. **Монолитная `build_pipeline_context()`** строит весь граф зависимостей при каждом вызове, независимо от потребностей команды.
4. **8 точек ручного `gateway.close()`**: каждая из 8 команд с кешем управляет lifecycle `SqliteCacheGateway` через `try/finally`.
5. **Добавление capability** требует изменения всех call sites: параметр появляется в `build_pipeline_context()`, а все 6 команд, вызывающих функцию, становятся потенциальными точками обновления.

---

## 🔍 Симптомы

**Симптом 1 — `import-apply` открывает vault engine трижды:**

```python
# containers.py — _VaultReadProviderRuntime
class _VaultReadProviderRuntime:
    def __init__(self, ...):
        self._engine = open_sqlite(vault_db_cfg, vault_db_path)  # vault engine #2

# containers.py — _VaultRetentionRuntime
class _VaultRetentionRuntime:
    def __init__(self, ...):
        self._engine = open_sqlite(vault_db_cfg, vault_db_path)  # vault engine #3

# import_apply.py
ensure_vault_startup_ready(paths_settings=app_settings.paths)   # vault engine #1
# ... открывает, проверяет, закрывает — ещё до старта команды
```

Три отдельных SQLite-соединения к одному файлу на один вызов команды. Три отдельные точки teardown.

**Симптом 2 — 3 уровня вложенных `try/finally` в `import-apply`:**

```python
# import_apply.py
try:
    gateway, cache_roles, _cache_specs = build_cache(app_settings.paths)
    try:
        runtime, target_info = build_target_runtime_with_info(...)
        try:
            with open_secret_store(...) as secrets_provider:
                with build_secret_retention_hook(...) as retention:
                    # ... логика команды ...
        finally:
            runtime.close()
    finally:
        gateway.close()
finally:
    ...
```

Каждый уровень — ручное управление lifecycle отдельного ресурса.

**Симптом 3 — `resolver_settings` протекает в команды без planning-стадий:**

```python
# normalize.py — planning не используется, но resolver_settings обязателен
pipeline_ctx = build_pipeline_context(
    ...
    resolver_settings=app_settings.resolver,  # ← команде не нужно
)
usecase.run(
    row_source=pipeline_ctx.row_source,
    map_stage=pipeline_ctx.map_stage,
    normalize_stage=pipeline_ctx.normalize_stage,
    # planning_deps построен, но не используется вообще
)
```

Аналогично в `enrich.py` и `mapping.py`.

**Симптом 4 — `resolver_settings` передаётся дважды в `match.py`:**

```python
# match.py
pipeline_ctx = build_pipeline_context(
    resolver_settings=app_settings.resolver,    # ← первый раз
)
match_stage, _ = dataset_spec.build_planning_stages(
    settings=app_settings.resolver,             # ← второй раз
)
```

Два источника правды для одного значения — риск молчаливого расхождения.

**Симптом 5 — `SqliteContainer` существует, но не задействован:**

```python
# containers.py — SqliteContainer объявлен корректно
class SqliteContainer(containers.DeclarativeContainer):
    cache_engine    = providers.Singleton(open_sqlite, ...)
    vault_engine    = providers.Singleton(open_sqlite, ...)
    identity_engine = providers.Singleton(open_sqlite, ...)
    cache_ready     = providers.Resource(cache_startup_resource, ...)
    vault_ready     = providers.Resource(vault_startup_resource, ...)
    identity_ready  = providers.Resource(identity_startup_resource, ...)

# build_cache() — игнорирует SqliteContainer
def build_cache(paths_settings):
    cache_engine    = open_sqlite(...)  # напрямую, в обход контейнера
    identity_engine = open_sqlite(...)
    ...
```

---

## 📊 Масштаб проблемы

- **Частота**: При каждом вызове каждой из 11 CLI-команд
- **Критичность**: Средняя — не нарушает корректность напрямую, но создаёт риски расхождения настроек (два источника `resolver_settings`), усложняет добавление новых capabilities и снижает надёжность teardown
- **Затронуто**: Все 11 CLI-команд, `containers.py`, `runtime.py`

### Команды по профилю зависимостей

| Профиль | Команды |
|---------|---------|
| Cache only | `normalize`, `mapping`, `match`, `resolve`, `cache-clear`, `cache-status` |
| Cache + Vault write | `enrich`, `import-plan` |
| Cache + Vault read + Vault retention + Target | `import-apply` |
| Cache + Target | `cache-refresh` |
| Target only | `check-api` |

---

## 🧪 Как воспроизвести

**Симптом 1 (3× vault engine):**
1. Открыть `connector/delivery/commands/import_apply.py`
2. Найти `ensure_vault_startup_ready(...)` — открывает vault engine, проверяет, закрывает
3. Найти `open_secret_store(...)` — открывает `_VaultReadProviderRuntime`, который в `__init__` открывает vault engine
4. Найти `build_secret_retention_hook(...)` — открывает `_VaultRetentionRuntime`, который в `__init__` открывает vault engine
5. **Ожидаемый результат**: один vault engine на invocation
6. **Фактический результат**: три SQLite-соединения к vault.db

**Симптом 3 (resolver_settings leak):**
1. Открыть `connector/delivery/commands/normalize.py`
2. Найти `build_pipeline_context(..., resolver_settings=app_settings.resolver, ...)`
3. Найти в теле функции создание `planning_deps`
4. **Ожидаемый результат**: normalize не знает о `resolver_settings`
5. **Фактический результат**: обязан передать и `planning_deps` строится впустую

---

## 🚫 Почему это проблема?

- **Vault надёжность**: три соединения к одному файлу создают конкуренцию за WAL-блокировку; teardown любого из трёх может провалиться молча
- **Два источника правды**: `resolver_settings` в `match` передаётся дважды через разные пути; рассинхронизация даст молчаливый баг в планировщике
- **Масштабируемость**: каждая новая capability (`dictionaries`, `telemetry`, `feature_flags`) добавляет параметр в `build_pipeline_context()` и обновление во всех 6 вызовах
- **Тестируемость**: тест `normalize` обязан поставить `cache_roles` и `resolver_settings` — зависимости, не нужные normalize-логике
- **Сложность teardown**: 3 уровня вложенных `try/finally` в `import-apply` трудно корректно расширять; порядок закрытия ресурсов имеет значение, но не выражен декларативно

---

## 💡 Возможные решения (обсуждение)

### Вариант A: Разбить utility-функции по профилям команд

- **Идея**: `build_cache_context()` (cache only), `build_vault_context()` (vault), `build_target_context()` (target) — per-profile функции
- **Плюсы**: Минимальное изменение, понятно читается
- **Минусы**: Не решает root cause — ручной lifecycle остаётся; vault engine открывается по-прежнему 3 раза; добавление capability всё равно распространяется на все функции

### Вариант B: AppContainer как единый Composition Root (принято)

- **Идея**: `AppContainer` с субконтейнерами (`SqliteContainer`, `CacheContainer`, `VaultContainer`, `TargetContainer`); `run_with_report()` создаёт контейнер, инициализирует нужные ресурсы, teardown — в `shutdown_resources()`; команды получают зависимости через `ctx.container.*`
- **Плюсы**: Vault engine открывается один раз; декларативный граф зависимостей; условная инициализация по профилю команды; `try/finally` исчезает из command handlers; forward-compatible для новых capabilities
- **Минусы**: Требует постепенной миграции всех 11 команд; добавляет концепцию контейнерной иерархии в codebase

---

## 🔗 Связанные документы

- [DELIVERY-DEC-001](./DELIVERY-DEC-001-di-container-hierarchy-and-migration-strategy.md) — принятое решение: архитектура + стратегия 6 шагов
- [DELIVERY-DEC-002](./DELIVERY-DEC-002-sqlitecontainer-as-engine-lifecycle-owner.md) — Шаг 1: SqliteContainer как владелец engines
- [DELIVERY-DEC-003](./DELIVERY-DEC-003-vault-container-single-vault-engine.md) — Шаг 2: VaultContainer, устранение 3× vault engine
- [DELIVERY-DEC-004](./DELIVERY-DEC-004-cache-container-gateway-roles.md) — Шаг 3: CacheContainer
- [DELIVERY-DEC-005](./DELIVERY-DEC-005-target-container-runtime-lifecycle.md) — Шаг 4: TargetContainer
- [DELIVERY-DEC-006](./DELIVERY-DEC-006-app-container-composition-root-integration.md) — Шаг 5: AppContainer CR
- [DELIVERY-DEC-007](./DELIVERY-DEC-007-remove-manual-wiring-utilities.md) — Шаг 6: удаление utility wiring функций
- [TRANSFORM-PROBLEM-003](../transform/TRANSFORM-PROBLEM-003-monolithic-pipeline-factory-eager-coupling.md) — смежная проблема монолитной `build_pipeline_context()`
- `connector/delivery/cli/containers.py` — существующий `SqliteContainer`; `build_pipeline_context()`
- `connector/delivery/commands/import_apply.py` — самый сложный пример (4 lifecycle, 3 vault engines)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-21 | Проблема обнаружена при анализе `import-apply` (3× vault engine) и `normalize` (resolver_settings leak) |
| 2026-02-21 | Решение зафиксировано в DELIVERY-DEC-001 (AppContainer как Composition Root, 6 шагов миграции) |
