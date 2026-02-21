# DELIVERY-DEC-005: Шаг 4 — TargetContainer: lifecycle DefaultTargetRuntime

> **Статус**: ✅ Реализовано
> **Дата принятия**: 2026-02-21
> **Решает проблему**: [DELIVERY-PROBLEM-001](./DELIVERY-PROBLEM-001-manual-wiring-no-composition-root.md)
> **Часть плана**: [DELIVERY-DEC-001](./DELIVERY-DEC-001-di-container-hierarchy-and-migration-strategy.md) — Шаг 4 из 6
> **Участники решения**: @xorex

---

## 📋 Контекст

Три команды используют `DefaultTargetRuntime`: `import-apply`, `cache-refresh`, `check-api`. Каждая вызывает `build_target_runtime_with_info()`, которая создаёт цепочку: `httpx.AsyncClient` → `BaseHttpDriver` → `TargetGateway` → `DefaultTargetRuntime`. Lifecycle управляется через `try/finally runtime.close()` в каждом handler.

В `import-apply` это третий уровень вложенных `try/finally`, наряду с cache и vault. `TargetKernel` (компилирует операции из DSL при создании) пересоздаётся при каждом вызове, хотя его результат immutable.

Шаг 4 — создать `TargetContainer`, который управляет lifecycle `DefaultTargetRuntime` через `Resource` provider.

---

## 🎯 Решение

`TargetContainer` оборачивает `build_target_runtime_with_info()` целиком как единый `Resource` provider. Отдельный Singleton для `TargetKernel` не выносится — kernel создаётся внутри provider chain и не требует явного управления на уровне контейнера. `build_target_runtime_with_info()` deprecates как standalone функция в `containers.py`. Команды получают `runtime` через `ctx.container.target.runtime()`.

---

## 🏗️ Архитектурное решение

### TargetContainer

```python
class TargetContainer(containers.DeclarativeContainer):
    # Внешние зависимости
    api_settings = providers.Dependency(instance_of=ApiSettings)
    transport    = providers.Dependency()   # None по умолчанию; override в тестах

    # Единый Resource: build_target_runtime_with_info() целиком
    runtime = providers.Resource(
        target_runtime_resource,
        api_settings=api_settings,
        transport=transport,
    )
```

### Resource-генератор для runtime

```python
def target_runtime_resource(
    api_settings: ApiSettings,
    transport,
) -> Iterator[TargetRuntimeBuildResult]:
    result = build_target_runtime_with_info(
        api_settings,
        transport=transport,
    )
    yield result    # result.runtime, result.target_type, result.effective_mode
    result.runtime.close()   # закрывает gateway → driver → httpx.Client
```

Resource оборачивает `build_target_runtime_with_info()` целиком — `TargetKernel` создаётся внутри provider chain и не выносится как отдельный Singleton. Это сохраняет внутреннюю структуру target-слоя без изменений.

### Почему `runtime` — `Resource`

`TargetRuntime` (внутри `TargetRuntimeBuildResult.runtime`) имеет `close()`, который корректно закрывает `TargetGateway`, затем `BaseHttpDriver`, затем `httpx.Client`. Resource-генератор декларативно выражает этот lifecycle и гарантирует вызов `close()` при `shutdown_resources()`.

### Параметр `transport`

`transport=None` → `httpx.AsyncClient` создаётся с реальным HTTP-транспортом. В тестах: `container.target.transport.override(MockTransport(...))` — без реальных HTTP-запросов.

### Было / Станет: import-apply handler (target часть)

**Было**:
```python
# import_apply.py
try:
    gateway, cache_roles, _cache_specs = build_cache(app_settings.paths)
    try:
        runtime, target_info = build_target_runtime_with_info(
            app_settings=app_settings,
        )
        try:
            # ... логика с vault и use-case ...
        finally:
            runtime.close()
    finally:
        gateway.close()
except sqlite3.Error as exc:
    return sqlite_cache_error_result(...)
```

**Станет** (Шаги 4+5):
```python
# import_apply.py
runtime     = ctx.container.target.runtime()
cache_roles = ctx.container.cache.roles()
# ... vault из ctx.container.vault.* ...
# ... логика use-case ...
# runtime.close() → container.shutdown_resources() в run_with_report()
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **`try/finally runtime.close()` исчезает** из 3 command handlers: lifecycle — container-managed
- ✅ **Не ломает internal target-layer**: `TargetKernel` создаётся внутри provider chain как и раньше; `factory.py` не рефакторится
- ✅ **Testability**: `container.target.transport.override(MockTransport(...))` — тест без HTTP; `container.target.runtime.override(...)` — полный mock runtime
- ✅ **Унифицированный teardown**: `runtime.close()` гарантированно вызывается в правильном порядке через `shutdown_resources()`

**Недостатки (компромиссы)**:
- ⚠️ `target.runtime.init()` нужно вызывать явно для команд с `requires_api=True`; без этого `runtime()` бросит при разрешении
  - Митигация: `_init_container_for_requirements()` всегда вызывает `target.runtime.init()` для `requires_api=True`

**Альтернативы, которые отклонили**:
- ❌ **`runtime` как `Singleton`**: `TargetRuntime` имеет `close()` — Singleton не гарантирует корректный teardown
- ❌ **Отдельный `kernel` Singleton**: `TargetKernel` создаётся внутри provider chain (`build_default_target_provider_registry` → `provider.build_core_runtime`); выносить его в контейнер значит рефакторить `factory.py` и нарушать инкапсуляцию target-слоя — не оправдано

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение | Статус |
|------|-----------|--------|
| `connector/delivery/cli/containers.py` | `TargetContainer`, `target_runtime_resource`; re-export `build_target_runtime`/`build_target_runtime_with_info` помечены deprecated | ✅ |
| `connector/infra/target/core/factory.py` | Используется внутри `target_runtime_resource`; без изменений | ✅ подтверждено |
| `connector/delivery/commands/import_apply.py` | Убрать `try/finally runtime.close()` | Шаг 5 |
| `connector/delivery/commands/cache_refresh.py` | Аналогично | Шаг 5 |
| `connector/delivery/commands/check_api.py` | Аналогично | Шаг 5 |

### Инварианты

1. **`runtime.close()` вызывается**: через `shutdown_resources()` при любом исходе команды
2. **`TargetKernel` не выносится**: создаётся внутри provider chain; `factory.py` не меняется
3. **`transport=None` в production**: реальный HTTP; `transport=MockTransport(...)` в тестах
4. **`target.runtime.init()` только при `requires_api=True`**: `check-api` не открывает SQLite; `import-apply` инициализирует и cache, и vault, и target

### Нюансы реализации

- **`transport` как `Dependency()` без `instance_of`**: transport может быть `None` (production HTTP) или mock-объект (тесты) — строгая типизация не применима.
- **Re-export `build_target_runtime`/`build_target_runtime_with_info` оставлены**: используются command handlers напрямую; удаление отложено до Шага 6 (DELIVERY-DEC-007).
- **`TargetRuntimeBuildResult` импортирован**: resource возвращает полный `TargetRuntimeBuildResult` (runtime + target_type + requested_mode + effective_mode), чтобы handlers имели доступ к метаданным сборки.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ `test_target_container_runtime_lifecycle(tmp_path)` — `runtime.close()` вызывается при `shutdown_resources()`
- ✅ `test_target_container_returns_build_result()` — `container.target.runtime()` возвращает `TargetRuntimeBuildResult` с `runtime`, `target_type`, `effective_mode`
- ✅ `test_target_container_mock_transport()` — override `transport` позволяет тест без HTTP
- ✅ `.venv/bin/python -m pytest tests/unit/delivery/ -x -q`

---

## ⚠️ Риски и ограничения

**Риски**:
- ~~⚠️ `build_target_runtime()` может иметь сложную сигнатуру несовместимую с `providers.Resource` параметрами~~
  - ✅ **Подтверждено**: `target_runtime_resource` принимает `api_settings` и `transport`, передаёт в `build_target_runtime_with_info()` — сигнатура совместима
- ~~⚠️ `target_info` (возвращается `build_target_runtime_with_info()`) используется в некоторых командах — нужно сохранить доступ~~
  - ✅ **Решено**: Resource возвращает целый `TargetRuntimeBuildResult` — handlers получают `result.runtime`, `result.target_type` и т.д. через один вызов `container.target.runtime()`

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `build_target_runtime_with_info()` | Deprecates | Заменяется `TargetContainer.runtime` |
| `import_apply.py` | Убирается вложенный `try/finally` | `runtime` из `ctx.container.target.runtime()` |
| `cache_refresh.py` | Убирается `try/finally runtime.close()` | Аналогично |
| `check_api.py` | Убирается `try/finally runtime.close()` | Аналогично |

---

## 🔗 Связанные документы

- [DELIVERY-PROBLEM-001](./DELIVERY-PROBLEM-001-manual-wiring-no-composition-root.md) — решаемая проблема
- [DELIVERY-DEC-001](./DELIVERY-DEC-001-di-container-hierarchy-and-migration-strategy.md) — общая стратегия
- [DELIVERY-DEC-004](./DELIVERY-DEC-004-cache-container-gateway-roles.md) — Шаг 3: CacheContainer
- [DELIVERY-DEC-006](./DELIVERY-DEC-006-app-container-composition-root-integration.md) — Шаг 5: AppContainer CR
- `connector/infra/target/core/factory.py` — `build_target_runtime()`

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-21 | Решение предложено и принято как Шаг 4 DI-миграции |
| 2026-02-21 | Обновлено: убран TargetKernel Singleton; TargetContainer оборачивает build_target_runtime_with_info() целиком как один Resource |
| 2026-02-21 | Реализовано: TargetContainer + target_runtime_resource; re-exports deprecated |
