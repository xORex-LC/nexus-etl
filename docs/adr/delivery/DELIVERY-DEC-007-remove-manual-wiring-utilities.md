# DELIVERY-DEC-007: Шаг 6 — Удаление utility wiring функций

> **Статус**: Принято / Реализовано
> **Дата принятия**: 2026-02-21
> **Решает проблему**: [DELIVERY-PROBLEM-001](./DELIVERY-PROBLEM-001-manual-wiring-no-composition-root.md)
> **Часть плана**: [DELIVERY-DEC-001](./DELIVERY-DEC-001-di-container-hierarchy-and-migration-strategy.md) — Шаг 6 из 6
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

После Шага 5 все 11 command handlers получают зависимости через `ctx.container.*`. Utility-функции `build_cache()`, `open_cache()`, `ensure_vault_startup_ready()`, `open_secret_store()`, `build_secret_provider()`, `build_secret_retention_hook()`, `build_target_runtime_with_info()` и `build_pipeline_context()` больше не вызываются из команд.

Шаг 6 — финальная очистка: удалить эти функции, устаревшие промежуточные классы (`_VaultReadProviderRuntime`, `_VaultRetentionRuntime`, `PipelineContext`) и оставить `containers.py` чистым файлом деклараций контейнеров.

**Trigger:** `grep -r "build_cache\|open_cache\|build_pipeline_context\|ensure_vault_startup_ready\|open_secret_store\|build_secret_provider\|build_secret_retention_hook\|build_target_runtime_with_info" connector/delivery/commands/` — пусто.

---

## 🎯 Решение

Удалить все utility wiring функции и промежуточные классы из `containers.py`. После удаления файл содержит только: декларации контейнеров (`SqliteContainer`, `VaultContainer`, `CacheContainer`, `TargetContainer`, `AppContainer`), Resource-генераторы (`cache_startup_resource`, `vault_startup_resource`, `identity_startup_resource`, `cache_gateway_resource`, `target_runtime_resource`) и вспомогательные build-функции для Resource-генераторов (`build_cache_db_config`, `build_vault_db_config` и подобные).

---

## 🏗️ Архитектурное решение

### Что удаляется

| Объект | Тип | Причина удаления |
|--------|-----|-----------------|
| `build_cache()` | Функция | Заменена `CacheContainer.gateway` + `CacheContainer.roles` |
| `open_cache()` | Функция | Заменена `CacheContainer.gateway` |
| `ensure_vault_startup_ready()` | Функция | Поглощена `vault_startup_resource` (vault_ready Resource) |
| `open_secret_store()` | Функция | Заменена `VaultContainer.read_service()` |
| `build_secret_provider()` | Функция | Заменена `VaultContainer.read_service()` |
| `build_secret_retention_hook()` | Функция | Заменена `VaultContainer.retention_service()` |
| `build_target_runtime_with_info()` | Re-export | Re-export из containers.py удалён; import из factory.py остаётся (используется target_runtime_resource) |
| `build_target_runtime()` | Re-export | Re-export удалён |
| `_VaultReadProviderRuntime` | Класс | Удалён (заменён VaultContainer.read_service Factory) |
| `_VaultRetentionRuntime` | Класс | Удалён (заменён VaultContainer.retention_service Factory) |
| `_open_vault_engine()` | Функция | Удалена (engine lifecycle у SqliteContainer) |
| `build_pipeline_context()` | Функция | **Остаётся** — ещё используется 5 командами; TRANSFORM-DEC-003 |
| `PipelineContext` | Dataclass | **Остаётся** — используется build_pipeline_context(); TRANSFORM-DEC-003 |

### containers.py после Шага 6

```
# containers.py — контейнеры, Resource-генераторы и утилиты (592 строки)

# --- Path helpers ---
def _cache_db_path(cache_dir) -> str: ...
def _vault_db_path(cache_dir, settings) -> str: ...
def _identity_db_path(cache_dir, settings) -> str: ...

# --- Engine factories ---
def _make_cache_engine(settings, cache_dir) -> SqliteEngine: ...
def _make_vault_engine(settings, cache_dir) -> SqliteEngine: ...
def _make_identity_engine(settings, cache_dir) -> SqliteEngine: ...

# --- Resource generators ---
def vault_startup_resource(engine) -> Iterator[None]: ...
def cache_startup_resource(engine, specs) -> Iterator[None]: ...
def identity_startup_resource(engine) -> Iterator[None]: ...
def cache_gateway_resource(cache_engine, identity_engine, specs) -> Iterator[SqliteCacheGateway]: ...
def target_runtime_resource(api_settings, transport) -> Iterator[TargetRuntimeBuildResult]: ...

# --- Sub-containers ---
class SqliteContainer(DeclarativeContainer): ...
class VaultContainer(DeclarativeContainer): ...
class CacheContainer(DeclarativeContainer): ...
class TargetContainer(DeclarativeContainer): ...

# --- Composition Root ---
class AppContainer(DeclarativeContainer): ...
def _init_container_for_requirements(container, req) -> None: ...

# --- Stateless utilities ---
def build_diagnostics_catalog(dataset, *, strict): ...
def build_dataset_spec(dataset, dataset_settings, *, secrets=None): ...

# --- Pipeline context (TRANSFORM-DEC-003 — будет вынесен) ---
class PipelineContext: ...
def build_pipeline_context(...) -> PipelineContext: ...
```

### Проверка готовности к удалению

```bash
# Убедиться что ни одна команда не использует legacy-функции
grep -r "build_cache\|open_cache\|build_pipeline_context" connector/delivery/commands/
grep -r "ensure_vault_startup_ready\|open_secret_store\|build_secret_provider" connector/delivery/commands/
grep -r "build_secret_retention_hook\|build_target_runtime_with_info" connector/delivery/commands/

# Убедиться что PipelineContext не используется
grep -r "PipelineContext\|pipeline_ctx\." connector/delivery/commands/

# Финальный прогон тестов
.venv/bin/python -m pytest tests/unit/ -x -q
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **`containers.py` — чистый файл деклараций**: только контейнеры и Resource-генераторы; нет императивного wiring-кода
- ✅ **Нет мёртвого кода**: удалённые функции не могут случайно использоваться в новом коде
- ✅ **Явный граф зависимостей**: весь object graph описан в `AppContainer` + sub-containers; нет скрытых зависимостей в функциях

**Недостатки (компромиссы)**:
- ⚠️ Если какой-то внешний код (тесты, скрипты) импортировал удалённые функции напрямую — получит `ImportError`
  - Митигация: `grep -r "from connector.delivery.cli.containers import" .` перед удалением; обновить все импорты

**Альтернативы, которые отклонили**:
- ❌ **Оставить deprecated функции с предупреждениями**: мёртвый код усложняет понимание; deprecation warning в CLI не виден разработчику
- ❌ **Удалять постепенно по одной**: можно, но после Шага 5 все команды мигрированы — нет смысла откладывать

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/delivery/cli/containers.py` | Удалить все utility функции и промежуточные классы; оставить только контейнеры и Resource-генераторы |
| `connector/delivery/commands/*.py` | Убедиться что нет импортов удалённых функций |
| `tests/unit/delivery/` | Удалить тесты удалённых функций; добавить тесты контейнеров если пропущены |

### Инварианты

1. **После удаления**: `grep -r "build_cache\|PipelineContext\|open_secret_store" connector/delivery/` → пусто
2. **Все тесты зелёные**: `.venv/bin/python -m pytest tests/unit/ -x -q` → 0 failures
3. **`containers.py` без `def build_*`**: только `class *Container`, `def *_resource`, `class Requirements`

---

## 🧪 Валидация решения

**Проверки перед удалением**:
```bash
# Убедиться что все команды мигрированы
grep -r "build_cache\|open_cache" connector/delivery/commands/

# Убедиться что PipelineContext не используется
grep -r "PipelineContext" connector/delivery/

# Запустить все тесты
.venv/bin/python -m pytest tests/unit/ -v
```

**После удаления**:
- ✅ Все 11 команд выполняются (`connector normalize --help`, `connector import-apply --help`)
- ✅ `tests/unit/` — все тесты зелёные
- ✅ `containers.py` содержит только `class *Container` и `def *_resource` определения

---

## ⚠️ Риски и ограничения

**Риски**:
- ⚠️ `build_pipeline_context()` удаляется только после реализации `PipelineContainer` (TRANSFORM-DEC-003) — или после того как все команды вручную мигрируют на прямое получение stages
  - **Митигация**: Если TRANSFORM-DEC-003 не реализован к Шагу 6 — `build_pipeline_context()` и `PipelineContext` остаются до отдельного transform-рефактора; Шаг 6 удаляет только остальные функции
- ⚠️ Тесты, напрямую тестирующие `build_cache()` — нужно удалить или преобразовать в тесты `CacheContainer`
  - **Митигация**: Аудит `tests/unit/delivery/` перед удалением

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `containers.py` | Финальная очистка | Удалить utility функции; оставить только контейнеры |
| `tests/unit/delivery/` | Обновление | Убрать тесты удалённых функций; тесты контейнеров остаются |
| Документация | Обновление | Любые ссылки на `build_cache()` и др. в README/docs → обновить |

---

## 🔗 Связанные документы

- [DELIVERY-PROBLEM-001](./DELIVERY-PROBLEM-001-manual-wiring-no-composition-root.md) — решаемая проблема
- [DELIVERY-DEC-001](./DELIVERY-DEC-001-di-container-hierarchy-and-migration-strategy.md) — общая стратегия
- [DELIVERY-DEC-006](./DELIVERY-DEC-006-app-container-composition-root-integration.md) — Шаг 5: AppContainer CR (trigger для Шага 6)
- [TRANSFORM-DEC-003](../transform/TRANSFORM-DEC-003-pipeline-container-lazy-stage-assembly.md) — PipelineContainer (зависимость для удаления `build_pipeline_context()`)
- `connector/delivery/cli/containers.py` — целевой файл очистки

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-21 | Решение предложено и принято как финальный Шаг 6 DI-миграции |
| 2026-02-21 | Реализовано: удалены build_cache, open_cache, ensure_vault_startup_ready, _open_vault_engine, open_secret_store, _VaultReadProviderRuntime, _VaultRetentionRuntime, build_secret_provider, build_secret_retention_hook, re-export build_target_runtime. PipelineContext + build_pipeline_context остаются (TRANSFORM-DEC-003). Integration/e2e тесты обновлены |
