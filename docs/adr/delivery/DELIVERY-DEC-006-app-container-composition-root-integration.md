# DELIVERY-DEC-006: Шаг 5 — AppContainer как единый Composition Root

> **Статус**: Реализовано
> **Дата принятия**: 2026-02-21
> **Решает проблему**: [DELIVERY-PROBLEM-001](./DELIVERY-PROBLEM-001-manual-wiring-no-composition-root.md)
> **Часть плана**: [DELIVERY-DEC-001](./DELIVERY-DEC-001-di-container-hierarchy-and-migration-strategy.md) — Шаг 5 из 6
> **Участники решения**: @xorex

---

## 📋 Контекст

К Шагу 5 все sub-containers готовы и протестированы: `SqliteContainer`, `VaultContainer`, `CacheContainer`, `TargetContainer`. Сейчас команды всё ещё используют utility-функции или инициализируют sub-containers напрямую.

Шаг 5 — создать `AppContainer` как единственный Composition Root (CR), интегрировать его в `run_with_report()`, добавить `container` в `CommandContext` и постепенно мигрировать command handlers от `build_cache()` / `build_target_runtime_with_info()` к `ctx.container.*`.

---

## 🎯 Решение

`AppContainer` монтирует все sub-containers и предоставляет единую точку входа. `run_with_report()` создаёт `AppContainer`, определяет `Requirements` для команды, вызывает `_init_container_for_requirements()`, передаёт контейнер в `CommandContext`, в `finally` вызывает `container.shutdown_resources()`. Command handlers получают зависимости через `ctx.container.*`.

Миграция команд — поэтапная, начиная с простейших (`normalize`, `mapping`), заканчивая самым сложным (`import-apply`).

---

## 🏗️ Архитектурное решение

### AppContainer

```python
class AppContainer(containers.DeclarativeContainer):
    app_settings = providers.Dependency(instance_of=AppSettings)

    # Вспомогательные провайдеры для слайсов AppSettings
    _sqlite_cfg   = providers.Singleton(SqliteSettings)
    _cache_dir    = providers.Callable(lambda s: s.paths.cache_dir, s=app_settings)
    _api_settings = providers.Callable(lambda s: s.api, s=app_settings)
    _cache_dsl    = providers.Singleton(load_cache_dsl_runtime)
    _cache_specs  = providers.Callable(lambda b: b.cache_specs, b=_cache_dsl)

    sqlite = providers.Container(SqliteContainer,
        settings=_sqlite_cfg,
        cache_dir=_cache_dir,
        cache_specs=_cache_specs)

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

### CommandContext расширяется

```python
@dataclass
class CommandContext:
    run_id: str
    app_settings: AppSettings | None
    catalog: ErrorCatalog | None
    logger: ...
    container: AppContainer | None = None    # ← новое поле
```

### run_with_report() — точка создания CR

```python
def run_with_report(command_name: str, req: Requirements, handler_fn, ...) -> CommandResult:
    app_settings = load_app_settings()
    container = AppContainer()
    container.app_settings.override(app_settings)

    try:
        _init_container_for_requirements(container, req)
        ctx = CommandContext(
            run_id=...,
            app_settings=app_settings,
            catalog=None,
            logger=...,
            container=container,
        )
        result = handler_fn(ctx, ...)
        return result
    finally:
        container.shutdown_resources()
```

### _init_container_for_requirements()

```python
# requirements.py — расширяется новым флагом
@dataclass(frozen=True)
class Requirements:
    requires_source: bool = False
    requires_api: bool = False
    requires_cache: bool = False
    requires_secrets: bool = False       # валидация vault_mode (существующий)
    requires_dataset: bool = False
    requires_vault_init: bool = False    # ← НОВЫЙ: инициализация vault engine

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

`requires_vault_init` — **зарезервирован, но не используется статически**. Vault-команды (enrich, import-plan, import-apply) **не** устанавливают `requires_vault_init=True` при регистрации, потому что vault init — **условная** операция: зависит от `vault_rollout_policy` и `vault_mode`. Handler сам вызывает `ctx.container.sqlite.vault_ready.init()` внутри `if rollout_decision.vault_enabled:` блока, обрабатывая `_STARTUP_ERRORS` локально.

### Профили команд

| Команда | `requires_cache` | `requires_vault_init` | `requires_api` |
|---------|:---:|:---:|:---:|
| `normalize` | ✅ | | |
| `mapping` | ✅ | | |
| `match` | ✅ | | |
| `resolve` | ✅ | | |
| `cache-clear` | ✅ | | |
| `cache-status` | ✅ | | |
| `enrich` | ✅ | | |
| `import-plan` | ✅ | | |
| `import-apply` | ✅ | | ✅ |
| `cache-refresh` | ✅ | | ✅ |
| `check-api` | | | ✅ |

> **Примечание**: `enrich`, `import-plan`, `import-apply` инициализируют vault **условно** в handler через `ctx.container.sqlite.vault_ready.init()` — не через Requirements.

### Порядок миграции команд (от простого к сложному)

1. `normalize` — только cache, один use-case
2. `mapping` — только cache
3. `match`, `resolve` — только cache, planning-стадии
4. `cache-clear`, `cache-status` — только cache
5. `enrich` — cache + vault write
6. `import-plan` — cache + vault write
7. `cache-refresh` — cache + target
8. `check-api` — только target
9. `import-apply` — cache + vault read/retention + target (самый сложный)

### Использование в command handler: примеры

```python
# normalize.py — после миграции (requires_cache=True)
def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
    cache_roles = ctx.container.cache.roles()
    # ... build_pipeline_context, usecase.run() — без изменений ...
    # Никакого try/finally, никакого gateway.close()

# import-apply.py — после миграции (requires_cache=True, requires_api=True)
def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
    cache_roles = ctx.container.cache.roles()
    target_result = ctx.container.target.runtime()    # TargetRuntimeBuildResult
    runtime = target_result.runtime
    # vault init — условный, зависит от rollout policy
    if rollout_decision.vault_enabled:
        ctx.container.sqlite.vault_ready.init()       # VaultStartupGuard внутри
        read_svc      = ctx.container.vault.read_service(default_run_id=run_id)
        retention_svc = ctx.container.vault.retention_service()
    else:
        read_svc      = NullSecretProvider()
        retention_svc = None
    # ... use-case ...
    # Никакого try/finally — container.shutdown_resources() в run_with_report() finally
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **Единый CR**: один `AppContainer()` на invocation; создаётся только в `run_with_report()`
- ✅ **Declarative lifecycle**: `shutdown_resources()` закрывает все ресурсы в правильном порядке; нет ручных `close()`
- ✅ **Условная инициализация**: `check-api` не открывает SQLite; `normalize` не знает о vault
- ✅ **Постепенная миграция**: команды мигрируют по одной; остальные продолжают работать через utility-функции до своего шага

**Недостатки (компромиссы)**:
- ⚠️ `CommandContext.container` — необязательный (`| None`) на переходный период; команды без миграции видят `None`
  - Митигация: После завершения Шага 6 поле станет обязательным
- ⚠️ `build_pipeline_context()` остаётся до TRANSFORM-DEC-003 — это отдельный шаг трансформ-слоя

**Альтернативы, которые отклонили**:
- ❌ **CR в каждом command handler**: нарушает принцип единого CR; каждый handler управляет lifecycle самостоятельно
- ❌ **Глобальный контейнер (модуль-уровень)**: singleton-состояние между тестами; нарушает изоляцию

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/delivery/cli/containers.py` | Добавить `AppContainer`, `_init_container_for_requirements()` |
| `connector/delivery/cli/requirements.py` | Добавить `requires_vault_init: bool = False` |
| `connector/delivery/cli/runtime.py` | `run_with_report()` создаёт `AppContainer`; `container.shutdown_resources()` в `finally` |
| `connector/delivery/cli/context.py` | `CommandContext.container: AppContainer \| None = None` |
| `connector/delivery/commands/normalize.py` | Первым мигрирует; убираются `try/finally`, `build_cache()` |
| `connector/delivery/commands/import_apply.py` | Последним мигрирует; 3 уровня `try/finally` → ноль |

### Инварианты

1. **`AppContainer()` создаётся только в `run_with_report()`**: ни один command handler не создаёт CR самостоятельно
2. **`shutdown_resources()` вызывается в `finally`**: даже при исключении в handler
3. **`_init_container_for_requirements()` вызывается до `handler_fn()`**: ресурсы готовы при входе в handler
4. **Один `AppContainer` на invocation**: не переиспользуется между вызовами (CLI-процесс один раз)
5. **`ctx.container` не `None` после Шага 5**: команды могут безопасно обращаться к `ctx.container`

---

## 🧪 Валидация решения

**Тесты**:
- ✅ `test_normalize_handler_uses_container(tmp_path)` — handler получает зависимости через `ctx.container.cache.roles()`
- ✅ `test_run_with_report_shutdown_on_exception()` — `shutdown_resources()` вызывается даже при exception в handler
- ✅ `test_check_api_does_not_open_sqlite()` — при `requires_api=True, requires_cache=False` SQLite-engines не создаются
- ✅ `test_import_apply_single_vault_engine(tmp_path)` — vault engine открывается ровно один раз
- ✅ `.venv/bin/python -m pytest tests/unit/ -x -q` — все тесты проходят после каждой мигрированной команды

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- `build_pipeline_context()` и `PipelineContext` остаются до TRANSFORM-DEC-003 — отдельный шаг трансформ-рефактора
- `CommandContext.container: AppContainer | None` — переходное состояние до Шага 6

**Риски**:
- ⚠️ Немигрированная команда обращается к `ctx.container` → `AttributeError` или `None`
  - **Митигация**: Добавить guard в `context.py`: property `container` бросает `RuntimeError` если `None`; снимается после полной миграции
- ⚠️ `shutdown_resources()` при частичной инициализации (ресурс не был `init()`-нут)
  - **Митигация**: Библиотека `dependency-injector` корректно обрабатывает shutdown неинициализированных Resource providers — они пропускаются

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `runtime.py` | Центральное изменение | CR создаётся здесь; `_init_container_for_requirements()` здесь |
| `context.py` | Добавляется поле | `container: AppContainer \| None = None` |
| 11 command handlers | Постепенный рефактор | Убираются `try/finally`; зависимости через `ctx.container.*` |
| `import_apply.py` | Наибольшее упрощение | 3 уровня `try/finally` → ноль |
| `normalize.py` | Минимальное изменение | Первым; служит образцом |

---

## 🔗 Связанные документы

- [DELIVERY-PROBLEM-001](./DELIVERY-PROBLEM-001-manual-wiring-no-composition-root.md) — решаемая проблема
- [DELIVERY-DEC-001](./DELIVERY-DEC-001-di-container-hierarchy-and-migration-strategy.md) — общая стратегия
- [DELIVERY-DEC-005](./DELIVERY-DEC-005-target-container-runtime-lifecycle.md) — Шаг 4: TargetContainer
- [DELIVERY-DEC-007](./DELIVERY-DEC-007-remove-manual-wiring-utilities.md) — Шаг 6: удаление utility functions
- [TRANSFORM-DEC-003](../transform/TRANSFORM-DEC-003-pipeline-container-lazy-stage-assembly.md) — PipelineContainer (смежный шаг, отдельный план)
- `connector/delivery/cli/runtime.py` — `run_with_report()`
- `connector/delivery/cli/context.py` — `CommandContext`

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-21 | Решение предложено и принято как Шаг 5 DI-миграции |
| 2026-02-21 | Реализовано: AppContainer + run_with_report() + миграция всех 11 command handlers. Отклонение от плана: vault init условный в handlers (не через requires_vault_init=True), т.к. зависит от vault rollout policy |
