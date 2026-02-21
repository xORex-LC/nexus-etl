# DELIVERY-DEC-003: Шаг 2 — VaultContainer и устранение 3× открытия vault engine

> **Статус**: ✅ Реализовано (VaultContainer создан; legacy wiring помечен deprecated)
> **Дата принятия**: 2026-02-21
> **Решает проблему**: [DELIVERY-PROBLEM-001](./DELIVERY-PROBLEM-001-manual-wiring-no-composition-root.md)
> **Часть плана**: [DELIVERY-DEC-001](./DELIVERY-DEC-001-di-container-hierarchy-and-migration-strategy.md) — Шаг 2 из 6
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

В `import-apply` vault engine открывается **трижды** на один вызов команды:

1. `ensure_vault_startup_ready()` — открывает `SqliteEngine`, проверяет vault, закрывает
2. `_VaultReadProviderRuntime.__init__()` — открывает свой `SqliteEngine` для `SecretVaultReadService`
3. `_VaultRetentionRuntime.__init__()` — открывает свой `SqliteEngine` для `VaultRetentionService`

Каждый из трёх объектов управляет lifecycle своего движка независимо. Teardown — через `getattr(obj, 'close', None)()` в нескольких уровнях `try/finally`.

После Шага 1 (DELIVERY-DEC-002) `SqliteContainer` управляет `vault_engine` как `Singleton`. Шаг 2 — использовать этот факт: `VaultContainer` монтируется поверх и предоставляет все vault-сервисы через shared `vault_engine`.

---

## 🎯 Решение

Создать `VaultContainer` с:
- `Singleton` providers для stateless объектов (cipher, key_provider, locator, repository)
- `Factory` providers для сервисов с per-invocation state (read_service, write_service, retention_service)
- `vault_ready` Resource в `SqliteContainer` поглощает `VaultStartupGuard` — startup-проверка происходит при `vault_ready.init()`

Удалить `_VaultReadProviderRuntime` и `_VaultRetentionRuntime` — их единственная роль (владение vault engine) переходит к `SqliteContainer.vault_engine` Singleton.

---

## 🏗️ Архитектурное решение

### VaultContainer

```python
class VaultContainer(containers.DeclarativeContainer):
    # Внешняя зависимость — приходит от SqliteContainer через AppContainer
    vault_engine = providers.Dependency(instance_of=SqliteEngine)

    # Stateless объекты — Singleton
    cipher       = providers.Singleton(FernetEnvelopeCipher)
    key_provider = providers.Singleton(EnvVaultKeyProvider)
    locator      = providers.Singleton(SecretLocatorService)
    repository   = providers.Singleton(
        SqliteVaultRepository,
        engine=vault_engine,
    )

    # Per-invocation сервисы — Factory
    read_service = providers.Factory(
        SecretVaultReadService,
        repository=repository,
        cipher=cipher,
        key_provider=key_provider,
        locator=locator,
    )
    write_service = providers.Factory(
        SecretVaultWriteService,
        repository=repository,
        cipher=cipher,
        key_provider=key_provider,
        locator=locator,
    )
    retention_service = providers.Factory(
        VaultRetentionService,
        repository=repository,
    )
```

### Изменение SqliteContainer: vault_ready поглощает VaultStartupGuard

```python
# До:
def vault_startup_resource(engine, ...) -> Iterator[None]:
    ensure_vault_schema(engine)
    yield
    engine.close()

# После (Шаг 2):
def vault_startup_resource(engine, ...) -> Iterator[None]:
    ensure_vault_schema(engine)
    guard = VaultStartupGuard(engine)
    guard.ensure_ready()    # ← startup-проверка интегрирована
    yield
    engine.close()
```

`ensure_vault_startup_ready()` как standalone функция — deprecates; её логика перенесена в Resource-генератор.

### Что удаляется

| Объект | Причина удаления |
|--------|-----------------|
| `_VaultReadProviderRuntime` | Открывал vault engine #2; теперь `VaultContainer.vault_engine` — Singleton из SqliteContainer |
| `_VaultRetentionRuntime` | Открывал vault engine #3; теперь `VaultContainer.vault_engine` — тот же Singleton |
| `ensure_vault_startup_ready()` (standalone) | Поглощена `vault_ready` Resource |

### Как команды используют VaultContainer (через AppContainer, Шаг 5)

`vault_ready.init()` вызывается в `_init_container_for_requirements()` автоматически для команд с `requires_vault_init=True` — handlers не вызывают `init()` вручную.

```python
# enrich.py — после миграции (Шаг 5)
# vault_ready.init() уже выполнен в _init_container_for_requirements()
if rollout_decision.vault_enabled:
    write_svc = ctx.container.vault.write_service()
else:
    write_svc = NullSecretProvider()

# import_apply.py — после миграции (Шаг 5)
# vault_ready.init() уже выполнен в _init_container_for_requirements()
if rollout_decision.vault_enabled:
    read_svc      = ctx.container.vault.read_service(default_run_id=run_id)
    retention_svc = ctx.container.vault.retention_service()
else:
    read_svc      = NullSecretProvider()
    retention_svc = None
# vault engine открывается ОДИН раз через SqliteContainer.vault_engine Singleton
```

### Было / Станет: vault lifecycle в `import-apply`

**Было** (3 engine open, 3 engine close):
```
ensure_vault_startup_ready() → open engine #1 → check → close engine #1
_VaultReadProviderRuntime()  → open engine #2  (живёт до secrets_provider.close())
_VaultRetentionRuntime()     → open engine #3  (живёт до secret_retention.close())
```

**Станет** (1 engine open, 1 engine close):
```
_init_container_for_requirements()  → vault_ready.init() → open engine #1 → VaultStartupGuard.ensure_ready()
container.vault.read_service(...)   → Factory; использует vault engine #1 (Singleton)
container.vault.retention_service() → Factory; использует vault engine #1 (тот же)
...
container.shutdown_resources()      → engine #1 закрывается один раз
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **Vault engine 1× вместо 3×**: `vault_engine` — `Singleton` в `SqliteContainer`; все три vault-объекта используют один движок
- ✅ **Единый teardown**: `container.shutdown_resources()` закрывает engine корректно и в правильном порядке; не нужны `getattr(obj, 'close', None)()`
- ✅ **Startup-проверка интегрирована**: `vault_ready.init()` = schema + guard + yield; не отдельный вызов
- ✅ **Factory для сервисов**: `read_service` принимает `default_run_id` → Factory корректно выражает "новый экземпляр при каждом вызове"

**Недостатки (компромиссы)**:
- ⚠️ `vault_ready.init()` нужно явно вызывать для команд с vault; забытый вызов → runtime error при первом использовании vault-сервиса
  - Митигация: integration-тест каждой vault-команды; `Dependency(instance_of=SqliteEngine)` даёт понятный error

**Альтернативы, которые отклонили**:
- ❌ **Singleton для read_service**: `SecretVaultReadService` принимает `default_run_id` (per-invocation); Singleton нарушит изоляцию между вызовами
- ❌ **Сохранить `_VaultReadProviderRuntime`**: открывает собственный engine, конфликтует с Singleton vault_engine в SqliteContainer

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/delivery/cli/containers.py` | Добавлен `VaultContainer`; `vault_startup_resource` уже содержит VaultStartupGuard; legacy wiring помечен deprecated |

### Нюансы реализации

**`vault_startup_resource()` уже содержит VaultStartupGuard**: Обнаружено при реализации — guard уже был интегрирован в Resource-генератор ранее. Никаких изменений в `vault_startup_resource()` не потребовалось.

**retention_service включает locator**: ADR изначально показывал `retention_service = Factory(VaultRetentionService, repository=repository)`. При реализации обнаружено, что `VaultRetentionService` также требует `locator=SecretLocatorService()`. Исправлено: `retention_service = Factory(VaultRetentionService, repository=repository, locator=locator)`.

**Legacy wiring НЕ удалён**: `_VaultReadProviderRuntime`, `_VaultRetentionRuntime`, `ensure_vault_startup_ready()`, `_open_vault_engine()` помечены deprecated, но оставлены — их используют `build_secret_provider()`, `build_secret_retention_hook()` и command handlers (enrich, import_plan, import_apply). Удаление невозможно без миграции handlers (Шаг 5) и потребовало бы ломающих изменений. Фактическое удаление перенесено в Шаг 6 (DELIVERY-DEC-007).

### Инварианты

1. **VaultContainer готов к использованию**: все providers (Singleton + Factory) корректно определены
2. **Vault Factory не кешируется**: каждый вызов `vault.read_service()` возвращает новый экземпляр
3. **Legacy wiring функционален**: `build_secret_provider()` и `build_secret_retention_hook()` работают без изменений (transitional)

---

## 🧪 Валидация решения

**Тесты**:
- ✅ `test_vault_container_single_engine(tmp_path)` — один `vault_engine` Singleton shared между `read_service`, `write_service`, `retention_service`
- ✅ `test_vault_ready_includes_startup_guard(tmp_path)` — `vault_ready.init()` вызывает `VaultStartupGuard.ensure_ready()`
- ✅ `test_vault_container_read_service_factory(tmp_path)` — два вызова `vault.read_service()` возвращают **разные** экземпляры
- ✅ Vault-специфичные тесты проходят: `.venv/bin/python -m pytest tests/unit/secrets/ -x -q`

---

## ⚠️ Риски и ограничения

**Риски**:
- ⚠️ Команды, использующие vault условно (`vault_enabled`), не вызывают `vault_ready.init()` по другой ветке → vault_engine остаётся нетронутым (штатное поведение)
  - **Митигация**: Тест для обоих путей (vault_enabled=True / False)
- ⚠️ `VaultRetentionService.close()` — если у него есть собственный cleanup — больше не вызывается через `_VaultRetentionRuntime`
  - **Митигация**: Проверить, есть ли у `VaultRetentionService` метод `close()`; если да — добавить в `vault_startup_resource` или через `Resource` provider

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Статус |
|-----------|---------|--------|
| `VaultContainer` | Создан | ✅ Реализован с Singleton + Factory providers |
| `ensure_vault_startup_ready()` | Помечен deprecated | Удаление в Шаге 6 |
| `_VaultReadProviderRuntime` | Помечен deprecated | Удаление в Шаге 6 |
| `_VaultRetentionRuntime` | Помечен deprecated | Удаление в Шаге 6 |
| `_open_vault_engine()` | Помечен deprecated | Удаление в Шаге 6 |
| `build_secret_provider()` | Без изменений | Будет заменён `VaultContainer.read_service()` в Шаге 5 |
| `build_secret_retention_hook()` | Без изменений | Будет заменён `VaultContainer.retention_service()` в Шаге 5 |

---

## 🔗 Связанные документы

- [DELIVERY-PROBLEM-001](./DELIVERY-PROBLEM-001-manual-wiring-no-composition-root.md) — решаемая проблема
- [DELIVERY-DEC-001](./DELIVERY-DEC-001-di-container-hierarchy-and-migration-strategy.md) — общая стратегия миграции
- [DELIVERY-DEC-002](./DELIVERY-DEC-002-sqlitecontainer-as-engine-lifecycle-owner.md) — Шаг 1: SqliteContainer
- [DELIVERY-DEC-004](./DELIVERY-DEC-004-cache-container-gateway-roles.md) — Шаг 3: CacheContainer
- `connector/delivery/cli/containers.py` — `SqliteContainer`, `_VaultReadProviderRuntime`, `_VaultRetentionRuntime`
- `connector/domain/secrets/` — `SecretVaultReadService`, `VaultRetentionService`

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-21 | Решение предложено и принято как Шаг 2 DI-миграции |
| 2026-02-21 | Реализовано: VaultContainer создан; legacy wiring помечен deprecated (удаление в Шаге 6); retention_service получил locator; 391 unit test pass |
