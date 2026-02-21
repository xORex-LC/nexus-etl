# DELIVERY-DEC-004: Шаг 3 — CacheContainer: gateway и roles под управлением контейнера

> **Статус**: ✅ Реализовано
> **Дата принятия**: 2026-02-21
> **Решает проблему**: [DELIVERY-PROBLEM-001](./DELIVERY-PROBLEM-001-manual-wiring-no-composition-root.md)
> **Часть плана**: [DELIVERY-DEC-001](./DELIVERY-DEC-001-di-container-hierarchy-and-migration-strategy.md) — Шаг 3 из 6
> **Участники решения**: @xorex

---

## 📋 Контекст

После Шага 2 `SqliteContainer` управляет `cache_engine` и `identity_engine` как Singleton. Однако `build_cache()` по-прежнему создаёт `SqliteCacheGateway` вручную и возвращает его вызывающей стороне, которая обязана вызвать `gateway.close()` в `finally`. Это 8 независимых точек закрытия в 8 command handlers.

Шаг 3 — создать `CacheContainer`, который обёртывает `SqliteCacheGateway` и `SqliteCacheRolePorts` как провайдеры. `build_cache()` deprecates и становится не нужной.

---

## 🎯 Решение

`CacheContainer` получает `cache_engine` и `identity_engine` от `SqliteContainer` (через `AppContainer`) как `Dependency` провайдеры. `gateway` — `Resource` provider с `owns_connection=False`: lifecycle engines остаётся у `SqliteContainer`. `roles` — `Singleton`: frozen dataclass без lifecycle.

`build_cache()` deprecates; команды получают `gateway` и `roles` через `ctx.container.cache.*` (Шаг 5).

---

## 🏗️ Архитектурное решение

### CacheContainer

```python
class CacheContainer(containers.DeclarativeContainer):
    # Внешние зависимости — engines приходят от SqliteContainer
    cache_engine    = providers.Dependency(instance_of=SqliteEngine)
    identity_engine = providers.Dependency(instance_of=SqliteEngine)
    cache_specs     = providers.Dependency()

    # DSL-bundle — загружается один раз
    cache_dsl_bundle = providers.Singleton(load_cache_dsl_runtime)

    # Gateway — Resource: имеет close(), lifecycle у SqliteContainer
    gateway = providers.Resource(
        cache_gateway_resource,
        cache_engine=cache_engine,
        identity_engine=identity_engine,
        cache_specs=cache_specs,
    )

    # Roles — Singleton: frozen dataclass, нет lifecycle
    roles = providers.Singleton(
        build_sqlite_cache_role_ports,
        gateway=gateway,
    )
```

### Resource-генератор для gateway

```python
def cache_gateway_resource(
    cache_engine: SqliteEngine,
    identity_engine: SqliteEngine,
    cache_specs,
) -> Iterator[SqliteCacheGateway]:
    gateway = SqliteCacheGateway.from_engine(
        cache_engine=cache_engine,
        identity_engine=identity_engine,
        specs=cache_specs,
        owns_connection=False,   # ← lifecycle engines у SqliteContainer
    )
    yield gateway
    gateway.close()              # ← очищает внутренний флаг _closed; engines не закрывает
```

### Почему `gateway` — `Resource`, а не `Singleton`

`SqliteCacheGateway.close()` должен быть вызван: он очищает внутренний флаг `_closed` и освобождает внутренние ресурсы. Resource-генератор (`yield gateway; gateway.close()`) выражает это декларативно и гарантирует вызов при `shutdown_resources()`.

### Почему `owns_connection=False`

`cache_engine` и `identity_engine` переданы от `SqliteContainer` как Singleton. Только `SqliteContainer` имеет право их закрывать — при вызове `cache_ready.shutdown()` и `identity_ready.shutdown()`. Двойное закрытие недопустимо.

### Почему `roles` — `Singleton`

`SqliteCacheRolePorts` — frozen dataclass-адаптер над `gateway`. Нет собственного lifecycle: не открывает соединений, не держит ресурсов. `Singleton` корректно выражает "создаётся один раз, переиспользуется".

### Было / Станет: normalize handler

**Было**:
```python
# normalize.py
gateway = None
try:
    gateway, cache_roles, _cache_specs = build_cache(app_settings.paths)
    pipeline_ctx = build_pipeline_context(
        cache_roles=cache_roles,
        ...
    )
    return usecase.run(...)
except sqlite3.Error as exc:
    return sqlite_cache_error_result(...)
finally:
    if gateway is not None:
        gateway.close()
```

**Станет** (Шаги 3+5):
```python
# normalize.py
cache_roles = ctx.container.cache.roles()   # Singleton
pipeline_ctx = build_pipeline_context(
    cache_roles=cache_roles,
    ...
)
return usecase.run(...)
# gateway.close() → container.shutdown_resources() в run_with_report()
# sqlite3.Error → обрабатывается в run_with_report() или убирается
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **8 точек `gateway.close()` → 1**: teardown `SqliteCacheGateway` — в `shutdown_resources()`, не в каждом handler
- ✅ **`sqlite3.Error` catch**: при container-managed lifecycle ошибки SQLite пробрасываются наверх — обрабатываются в `run_with_report()`, не дублируются в 8 handlers
- ✅ **`owns_connection=False`**: корректное разделение ответственности — gateway не закрывает то, что не открывал
- ✅ **Testability**: тест `normalize` делает `container.cache.gateway.override(...)` — не поднимает реальный SQLite

**Недостатки (компромиссы)**:
- ⚠️ `gateway` как `Resource` требует явного `cache.gateway.init()` до первого использования — без этого `roles()` вернёт непроинициализированный gateway
  - Митигация: `_init_container_for_requirements()` всегда вызывает `cache.gateway.init()` для `requires_cache=True`

**Альтернативы, которые отклонили**:
- ❌ **`gateway` как `Singleton`**: `Singleton` не выражает наличие `close()` — teardown не гарантирован
- ❌ **Оставить `build_cache()` навсегда**: противоречит цели убрать ручной wiring; 8 точек `gateway.close()` остаются

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение | Статус |
|------|-----------|--------|
| `connector/delivery/cli/containers.py` | `CacheContainer`, `cache_gateway_resource`; `build_cache()` / `open_cache()` помечены deprecated | ✅ |
| `connector/infra/cache/cache_gateway.py` | `SqliteCacheGateway.from_engine(owns_connection=False)` уже поддерживается | ✅ подтверждено |

### Инварианты

1. **`cache_engine` / `identity_engine` не закрываются `gateway`**: `owns_connection=False`
2. **`roles` — Singleton**: создаётся один раз при первом обращении; не пересоздаётся
3. **`gateway.init()` → `roles()` work**: `roles` Singleton ссылается на gateway; оба инициализируются через `cache.gateway.init()`
4. **Один `CacheContainer` на invocation**: не переиспользуется между вызовами команды

### Нюансы реализации

- **Double `ensure_cache_ready`**: `SqliteContainer.cache_ready` вызывает `ensure_cache_ready()`, и `SqliteCacheGateway.from_engine()` вызывает его повторно внутри. Оба вызова идемпотентны (`CREATE TABLE IF NOT EXISTS`), поэтому безопасны.
- **`cache_specs` как `Dependency(instance_of=list)`**: cache_specs передаются извне (из `build_cache()` или будущего `AppContainer`), а не загружаются внутри CacheContainer — разделение ответственности: загрузка DSL ≠ сборка gateway.
- **`build_cache()` и `open_cache()` оставлены deprecated**: используются 10 command handlers; удаление отложено до Шага 6 (DELIVERY-DEC-007) после миграции handlers в Шаге 5.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ `test_cache_container_gateway_teardown(tmp_path)` — `gateway.close()` вызывается при `shutdown_resources()`; engines не закрываются gateway
- ✅ `test_cache_container_roles_singleton(tmp_path)` — два вызова `cache.roles()` возвращают **один** объект
- ✅ `test_cache_container_owns_connection_false(tmp_path)` — engines не закрываются при `gateway.close()`
- ✅ Тесты cache-команд проходят: `.venv/bin/python -m pytest tests/unit/cache/ tests/unit/delivery/ -x -q`

---

## ⚠️ Риски и ограничения

**Риски**:
- ~~⚠️ `SqliteCacheGateway.from_engine(owns_connection=False)` — если метод не существует или не поддерживает флаг → нужна доработка `cache_gateway.py`~~
  - ✅ **Подтверждено**: `from_engine(owns_connection=False)` поддерживается, `close()` с `owns_connection=False` только сбрасывает `_closed=True` без закрытия engines

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `build_cache()` | Deprecates | Заменяется `CacheContainer.gateway` + `CacheContainer.roles` |
| `open_cache()` | Deprecates | Заменяется `CacheContainer.gateway` |
| 8 команд с `build_cache()` | Рефактор в Шаге 5 | `gateway`, `roles` получают через `ctx.container.cache.*` |
| `sqlite3.Error` catch | Упрощается | Обрабатывается в `run_with_report()` — не в каждом handler |

---

## 🔗 Связанные документы

- [DELIVERY-PROBLEM-001](./DELIVERY-PROBLEM-001-manual-wiring-no-composition-root.md) — решаемая проблема
- [DELIVERY-DEC-001](./DELIVERY-DEC-001-di-container-hierarchy-and-migration-strategy.md) — общая стратегия
- [DELIVERY-DEC-002](./DELIVERY-DEC-002-sqlitecontainer-as-engine-lifecycle-owner.md) — Шаг 1: SqliteContainer (владеет engines)
- [DELIVERY-DEC-003](./DELIVERY-DEC-003-vault-container-single-vault-engine.md) — Шаг 2: VaultContainer
- [DELIVERY-DEC-005](./DELIVERY-DEC-005-target-container-runtime-lifecycle.md) — Шаг 4: TargetContainer
- `connector/infra/cache/cache_gateway.py` — `SqliteCacheGateway.from_engine()`

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-21 | Решение предложено и принято как Шаг 3 DI-миграции |
| 2026-02-21 | Реализовано: CacheContainer + cache_gateway_resource; build_cache/open_cache deprecated |
