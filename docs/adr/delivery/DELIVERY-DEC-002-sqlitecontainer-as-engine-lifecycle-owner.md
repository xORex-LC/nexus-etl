# DELIVERY-DEC-002: Шаг 1 — SqliteContainer как реальный владелец SQLite engines

> **Статус**: Принято / Реализовано
> **Дата принятия**: 2026-02-21
> **Решает проблему**: [DELIVERY-PROBLEM-001](./DELIVERY-PROBLEM-001-manual-wiring-no-composition-root.md)
> **Часть плана**: [DELIVERY-DEC-001](./DELIVERY-DEC-001-di-container-hierarchy-and-migration-strategy.md) — Шаг 1 из 6
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

`SqliteContainer` уже объявлен в `containers.py` с тремя `Singleton` engines (`cache_engine`, `vault_engine`, `identity_engine`) и тремя `Resource` providers (`cache_ready`, `vault_ready`, `identity_ready`). Однако функции `build_cache()` и `open_cache()` напрямую вызывают `open_sqlite()`, обходя контейнер полностью. В результате SqliteContainer существует, но не задействован ни одной командой.

Шаг 1 — сделать SqliteContainer «живым»: `build_cache()` и `open_cache()` делегируют ему открытие движков. Внешний интерфейс функций не меняется; все 11 команд прозрачно получают container-managed engines.

---

## 🎯 Решение

`build_cache()` и `open_cache()` внутри создают `SqliteContainer`, вызывают нужные `Resource` providers для инициализации схем, получают готовые engines и передают их дальше. При `gateway.close()` — вызов `container.shutdown_resources()` закрывает engines. Внешний API функций (`build_cache()` → `(gateway, cache_roles, cache_specs)`) не меняется.

---

## 🏗️ Архитектурное решение

### До (текущее состояние)

```python
# containers.py — SqliteContainer существует но не используется
class SqliteContainer(containers.DeclarativeContainer):
    cache_engine    = providers.Singleton(open_sqlite, ...)
    vault_engine    = providers.Singleton(open_sqlite, ...)
    identity_engine = providers.Singleton(open_sqlite, ...)
    cache_ready     = providers.Resource(cache_startup_resource, ...)
    vault_ready     = providers.Resource(vault_startup_resource, ...)
    identity_ready  = providers.Resource(identity_startup_resource, ...)

# containers.py — build_cache() обходит SqliteContainer
def build_cache(paths_settings: PathsSettings):
    cache_db_config    = build_cache_db_config(sqlite_settings, paths_settings.cache_dir)
    identity_db_config = build_identity_db_config(sqlite_settings, ...)
    cache_engine    = open_sqlite(cache_db_config, cache_db_path)    # напрямую
    identity_engine = open_sqlite(identity_db_config, identity_db_path)
    ...
    return gateway, cache_roles, cache_specs
```

### После (целевое состояние Шага 1)

```python
# containers.py — build_cache() делегирует SqliteContainer
def build_cache(paths_settings: PathsSettings):
    container = SqliteContainer()
    container.settings.override(SqliteSettings())
    container.cache_dir.override(paths_settings.cache_dir)
    container.cache_specs.override(load_cache_dsl_runtime().cache_specs)
    container.cache_ready.init()
    container.identity_ready.init()
    cache_engine    = container.cache_engine()
    identity_engine = container.identity_engine()
    # ... дальнейшая логика gateway, roles, specs — без изменений ...
    # teardown: при gateway.close() вызывается container.shutdown_resources()
    return gateway, cache_roles, cache_specs
```

### Нюансы реализации

**`vault_startup_resource()` уже включает VaultStartupGuard**: Вопреки ожиданию, `vault_ready` Resource уже содержит полную проверку (`ensure_vault_schema` + `VaultStartupGuard.ensure_ready()`). Это было реализовано ранее. На Шаге 1 vault_ready НЕ вызывается — только `cache_ready` и `identity_ready`.

**Gateway с `owns_connection=False`**: SqliteContainer управляет engine lifecycle через Resource teardown. Gateway создаётся с `owns_connection=False` — при `gateway.close()` engines не закрываются (это делает контейнер).

**Transitional closure для gateway.close()**: `gateway.close()` оборачивается closure, которая после оригинального `close()` вызывает `container.shutdown_resources()`. Флаг `_shutdown_done` предотвращает двойной shutdown. Эта обёртка — transitional: будет убрана в Шаге 3 (CacheContainer).

**Двойной вызов `ensure_cache_ready`**: `cache_startup_resource` вызывает `ensure_cache_ready(engine, specs)`, а `SqliteCacheGateway.from_engine()` вызывает его повторно. Операция идемпотентна (CREATE TABLE IF NOT EXISTS), поэтому двойной вызов безопасен.

### Граф провайдеров SqliteContainer (без изменений)

| Provider | Тип | Ответственность |
|----------|-----|----------------|
| `settings` | `Dependency[SqliteSettings]` | Конфиг SQLite (из ENV) |
| `cache_dir` | `Dependency[Path]` | Путь к директории кеша |
| `cache_specs` | `Dependency[...]` | DSL-спецификации схемы |
| `cache_engine` | `Singleton` | SQLite-движок для кеша |
| `identity_engine` | `Singleton` | SQLite-движок для identity |
| `vault_engine` | `Singleton` | SQLite-движок для vault |
| `cache_ready` | `Resource` | `ensure_cache_schema()` → yield → `engine.close()` |
| `identity_ready` | `Resource` | `ensure_identity_schema()` → yield → `engine.close()` |
| `vault_ready` | `Resource` | `ensure_vault_schema()` → yield → `engine.close()` |

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **Без изменений для команд**: `build_cache()` возвращает тот же `(gateway, roles, specs)` — 11 команд прозрачно получают container-managed engines
- ✅ **SqliteContainer начинает работать**: доказывает жизнеспособность контейнера, открывает путь к Шагам 3–5
- ✅ **Дублирующийся код открытия engines**: удаляется из `build_cache()` — логика переходит в `SqliteContainer` providers
- ✅ **Тестируемость**: можно написать integration test: `SqliteContainer` инициализируется с test-путями, teardown корректен

**Недостатки (компромиссы)**:
- ⚠️ `build_cache()` становится тонкой обёрткой над контейнером — до Шага 3, когда она deprecates. Два слоя абстракции временно.

**Альтернативы, которые отклонили**:
- ❌ **Сразу мигрировать команды на AppContainer**: требует Шагов 2–5 готовыми; риск больших незавершённых изменений
- ❌ **Сохранить прямые `open_sqlite()`**: откладывает интеграцию SqliteContainer на неопределённый срок

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/delivery/cli/containers.py` | `build_cache()` и `open_cache()` делегируют `SqliteContainer` |
| `connector/delivery/cli/containers.py` | `SqliteContainer` — добавить `Dependency` providers для параметров если нужно |

### Инварианты

1. **Внешний интерфейс `build_cache()` не меняется**: возвращает `(SqliteCacheGateway, SqliteCacheRolePorts, CacheSpecs)`
2. **Vault engine не открывается**: `build_cache()` инициализирует только `cache_ready` и `identity_ready`; `vault_ready` не вызывается
3. **Один SqliteContainer на вызов `build_cache()`**: не переиспользуется между командами
4. **Teardown**: при `gateway.close()` вызывается `container.shutdown_resources()` — engines корректно закрываются

---

## 🧪 Валидация решения

**Тесты**:
- ✅ `test_build_cache_uses_sqlite_container(tmp_path)` — `SqliteContainer` инициализируется, engines открываются, при teardown закрываются
- ✅ `test_build_cache_does_not_open_vault_engine(tmp_path)` — vault engine не открывается при `build_cache()`
- ✅ Существующие тесты команд проходят без изменений (`pytest tests/unit/ -x -q`)

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- `build_cache()` остаётся как обёртка — до Шага 3 (DELIVERY-DEC-004), когда `CacheContainer` делает её ненужной

**Риски**:
- ~~⚠️ `SqliteContainer` в текущем виде может требовать доработки `Dependency` providers~~ — **Resolved**: SqliteContainer уже имел корректные Dependency providers; `override()` работает без изменений

---

## 🔗 Связанные документы

- [DELIVERY-PROBLEM-001](./DELIVERY-PROBLEM-001-manual-wiring-no-composition-root.md) — решаемая проблема
- [DELIVERY-DEC-001](./DELIVERY-DEC-001-di-container-hierarchy-and-migration-strategy.md) — общая стратегия миграции
- [DELIVERY-DEC-003](./DELIVERY-DEC-003-vault-container-single-vault-engine.md) — Шаг 2: VaultContainer
- `connector/delivery/cli/containers.py` — `SqliteContainer`, `build_cache()`

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-21 | Решение предложено и принято как Шаг 1 DI-миграции |
| 2026-02-21 | Реализовано: build_cache() делегирует SqliteContainer; gateway.close() → container.shutdown_resources(); 391 unit test pass |
