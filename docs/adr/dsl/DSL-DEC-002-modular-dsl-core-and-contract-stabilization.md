# DSL-DEC-002: Модульная декомпозиция DSL Core и стабилизация compile/runtime контрактов

> **Статус**: Принято / Реализовано
> **Дата принятия**: 2026-02-13
> **Решает проблему**: [DSL-PROBLEM-002](./DSL-PROBLEM-002-dsl-core-coupling-and-contract-drift-under-scale.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

По результатам архитектурного аудита основной риск DSL Core сместился в архитектурную плоскость: связность, масштабируемость и предсказуемость контрактов между transform/cache путями.  
Проблема зафиксирована в [DSL-PROBLEM-002](./DSL-PROBLEM-002-dsl-core-coupling-and-contract-drift-under-scale.md).

---

## 🎯 Решение

Внедрить модульную структуру DSL Core и единый контракт поведения для загрузки, merge build options, runtime error-handling и hot-path ops:
- разделить монолитные `specs`/`loader` на доменные подмодули;
- сделать merge build options явным и fail-fast в неоднозначных случаях;
- формализовать strict-режим для unknown build options keys;
- выровнять `on_error` vocabulary и runtime поведение cache sync;
- снизить стоимость hot-path операций через кеширование;
- зафиксировать защиту от случайной перерегистрации операций.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `connector/domain/dsl/specs/_base.py`
  - `DslBaseModel` (`extra="forbid"`)
  - `OperationCall`
- `connector/domain/dsl/specs/transform.py`
  - transform-спецификации (`MappingSpec`, `NormalizeSpec`, `EnrichSpec`, `MatchSpec`, `ResolveSpec`, `ValidationSpec`, `SourceSpec`, `SinkSpec`)
- `connector/domain/dsl/specs/cache.py`
  - cache-спецификации (`CacheRegistrySpec`, `CacheDatasetSpec`, `CacheSyncSpec` и связанные policy/rule модели)
- `connector/domain/dsl/loader/_common.py`
  - общий loading pipeline (`_load_registry_or_raise`, `_load_dataset_stage_spec`, `_validate_spec_or_raise`)
- `connector/domain/dsl/loader/transform.py`
  - transform stage loaders + stage build options loaders
- `connector/domain/dsl/loader/cache.py`
  - cache loaders + runtime cache build options merge

**Изменения в существующих компонентах**:
- `connector/domain/dsl/build_options.py`:
  - `build_options_from_mapping(..., strict: bool = False)` с `BUILD_OPTIONS_UNKNOWN_KEYS`.
- `connector/domain/dsl/loader/cache.py`:
  - `CACHE_DSL_BUILD_OPTIONS_AMBIGUOUS` при неявно неоднозначных dataset overrides.
- `connector/domain/dsl/loader/_common.py`:
  - устойчивый `_repo_root()` через поиск `datasets/registry.yml` в `parents`.
- `connector/domain/dsl/registry.py`:
  - duplicate-protection в `OperationRegistry.register(..., allow_override=False)`.
- `connector/domain/dsl/ops.py`:
  - LRU-кэш `op_extract_patterns` и `op_map_dict(casefold=True)`.
- `connector/infra/cache/sync/dsl_adapter.py`:
  - явная runtime-семантика `on_error`: `error` / `warn` / `skip` / `set_null`.

### Интерфейсы

```python
class DslBaseModel(BaseModel):
    model_config = {"extra": "forbid"}

def build_options_from_mapping(
    cls: type[TBuildOptions],
    data: dict[str, Any] | None,
    *,
    strict: bool = False,
) -> TBuildOptions: ...

def load_cache_build_options_for_runtime(
    *,
    dataset_overrides: dict[str, dict[str, Any]] | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> CacheDslBuildOptions: ...

class OperationRegistry:
    def register(self, name: str, func: OperationFunc, *, allow_override: bool = False) -> None: ...
```

### Поток данных

```
datasets/registry.yml + stage YAML
        ↓
loader/_common.py (resolve/read/validate)
        ↓
loader/transform.py | loader/cache.py
        ↓
build_options_from_mapping(strict=merged.strict)
        ↓
typed Spec + typed BuildOptions
        ↓
stage DSL compile/runtime
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Уменьшает связность: transform/cache зоны изолированы на уровне модулей.
- ✅ Делает merge build options детерминированным и fail-fast в ambiguous runtime-сценариях.
- ✅ Ускоряет hot-path DSL ops за счёт LRU-кэша повторяющихся вычислений.
- ✅ Повышает предсказуемость runtime обработки ошибок (`on_error`).
- ✅ Улучшает поддерживаемость: изменения локализуются по подмодулям.

**Недостатки (компромиссы)**:
- ⚠️ Рефакторинг увеличивает количество модулей и import paths (но это контролируемая плата за модульность).
- ⚠️ Строгие контракты поднимают больше ошибок на этапе загрузки (но это целевое fail-fast поведение).

**Альтернативы, которые отклонили**:
- ❌ **Оставить монолит и чинить локально**: не убирает root cause связности.
- ❌ **Документировать без рефакторинга**: не снижает технический риск в runtime.
- ❌ **Декомпозировать только models или только loaders**: оставляет частичный дрейф контрактов.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/dsl/specs/_base.py` | Вынесена базовая DSL модель и `OperationCall` |
| `connector/domain/dsl/specs/transform.py` | Вынесены transform спецификации |
| `connector/domain/dsl/specs/cache.py` | Вынесены cache спецификации |
| `connector/domain/dsl/loader/_common.py` | Общий fail-fast pipeline загрузки |
| `connector/domain/dsl/loader/transform.py` | Загрузчики transform + merge stage options |
| `connector/domain/dsl/loader/cache.py` | Загрузчики cache + ambiguous runtime options guard |
| `connector/domain/dsl/build_options.py` | strict-mode unknown key validation |
| `connector/domain/dsl/ops.py` | LRU-кэш для regex/mapping hot-path |
| `connector/infra/cache/sync/dsl_adapter.py` | Явная runtime семантика `on_error` |
| `tests/integration/transform/test_dsl_build_options.py` | Проверки strict/merge/ambiguous behavior |
| `tests/unit/transform/test_dsl_ops.py` | Проверка hot-path casefold mapping |
| `tests/unit/cache/test_dsl_sync_adapter.py` | Проверки `skip`/`set_null`/`warn`/`error` |

### Ключевые методы

- `connector/domain/dsl/loader/_common.py`: `_repo_root()`, `_load_dataset_stage_spec()`.
- `connector/domain/dsl/loader/transform.py`: `_load_stage_build_options()`.
- `connector/domain/dsl/loader/cache.py`: `load_cache_build_options_for_runtime()`.
- `connector/domain/dsl/build_options.py`: `build_options_from_mapping()`.
- `connector/domain/dsl/ops.py`: `_compile_patterns()`, `_normalize_mapping_safe()`.
- `connector/infra/cache/sync/dsl_adapter.py`: `_eval_value_expr()`.

### Инварианты

1. **Spec-level strictness**: все DSL spec модели наследуются от `DslBaseModel(extra="forbid")`.
2. **Strict build options policy**: при `strict=True` unknown keys запрещены (`BUILD_OPTIONS_UNKNOWN_KEYS`).
3. **Ambiguity guard**: cache runtime build options без явного контекста dataset не сливаются «молча» при конфликте (`CACHE_DSL_BUILD_OPTIONS_AMBIGUOUS`).
4. **Registry safety**: повторная регистрация операции запрещена без `allow_override=True`.
5. **Runtime error contract**: cache DSL `on_error` обрабатывается явно по каждому режиму.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ `test_stage_build_options_strict_mode_fails_on_unknown_keys()` (`tests/integration/transform/test_dsl_build_options.py`)
- ✅ `test_cache_build_options_fails_when_registry_overrides_are_ambiguous()` (`tests/integration/transform/test_dsl_build_options.py`)
- ✅ `test_op_map_dict_casefold_handles_unhashable_mapping_values()` (`tests/unit/transform/test_dsl_ops.py`)
- ✅ `test_map_target_to_cache_skips_field_on_skip_policy()` (`tests/unit/cache/test_dsl_sync_adapter.py`)
- ✅ `test_map_target_to_cache_sets_null_on_warn_policy()` (`tests/unit/cache/test_dsl_sync_adapter.py`)

**Проверка в production**:
1. Запустить compile/load stages с реальными `registry.yml` и dataset YAML.
2. Проверить, что ambiguous cache runtime overrides детектируются до выполнения.
3. Проверить логи cache sync для корректной ветки `warn`/`skip`/`set_null`.

**Метрики успеха**:
- Количество runtime ошибок из-за неоднозначного cache options merge: должно быть `0` (ошибка переносится в load/compile).
- Время выполнения hot-path ops на повторяющихся паттернах: не должно деградировать линейно от повторной компиляции regex.

---

## 📐 Диаграммы

**UML диаграммы** (если созданы):
- [DSL Architecture](../../uml/transform/dsl/dsl_architecture.png)
- [DSL Class](../../uml/transform/dsl/dsl_class.png)
- [DSL Options Merge Activity](../../uml/transform/dsl/dsl_core_options_merge_activity.png)

**Примеры использования**:

```python
# strict-mode для unknown build_options keys
options = build_options_from_mapping(MapDslBuildOptions, {"strict": True, "unknown": 1}, strict=True)
# -> DslLoadError(code="BUILD_OPTIONS_UNKNOWN_KEYS")
```

```python
# cache runtime options: ambiguous dataset overrides требуют явного контекста
load_cache_build_options_for_runtime()
# -> DslLoadError(code="CACHE_DSL_BUILD_OPTIONS_AMBIGUOUS") при >1 dataset override
```

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Публичный фасад `connector.domain.dsl.__init__` остаётся широким и требует дальнейшей рационализации API.
- Часть legacy YAML может требовать миграции под более строгие контракты.

**Риски**:
- ⚠️ Риск: усиление strict-поведения увеличит число compile ошибок на старых конфигурациях → Митигация: поэтапная миграция и CI gate на compile/load.
- ⚠️ Риск: разные команды могут по-разному трактовать `on_error` semantics в новых адаптерах → Митигация: единая документация слоя и обязательные unit-тесты на policy ветки.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| Transform stage DSL (mapping/normalize/enrich/match/resolve) | Прямое | Использовать обновлённые `loader/transform.py` и `specs/transform.py` |
| Cache DSL + cache sync adapter | Прямое | Следовать `on_error` контракту и guard'ам cache runtime options |
| Dataset registry wiring | Прямое | Явно задавать корректный контекст для cache build options |
| Dev documentation/UML | Прямое | Поддерживать соответствие split-архитектуре |

---

## 📚 Документация

**Обновлена документация**:
- ✅ [dsl-specs.md](../../dev/layers/dsl/dsl-specs.md) — обновлена структура `specs/*` и `loader/*`
- ✅ [dsl-engine.md](../../dev/layers/dsl/dsl-engine.md) — актуализированы зависимости и perf-notes
- ✅ [dsl-diagnostics.md](../../dev/layers/dsl/dsl-diagnostics.md) — актуализирована карта источников ошибок
- ✅ [Transform DSL UML README](../../uml/transform/dsl/README.md) — зафиксирована split-архитектура

---

## 🔗 Связанные документы

- [DSL-PROBLEM-002](./DSL-PROBLEM-002-dsl-core-coupling-and-contract-drift-under-scale.md) - решаемая проблема
- [DSL-PROBLEM-001](./DSL-PROBLEM-001-dsl-core-fail-late-and-weak-compile-contract.md) - предыдущая закрытая проблема
- [DSL-DEC-001](./DSL-DEC-001-strict-compile-validation-and-diagnostics-hardening.md) - базовое fail-fast решение
- [DSL layer docs](../../dev/layers/dsl/dsl-specs.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-13 | Решение предложено |
| 2026-02-13 | Решение принято после обсуждения |
| 2026-02-13 | Реализовано в DSL refactor (split specs/loader, options/ops/runtime contracts) |
| 2026-02-13 | Документация и UML синхронизированы |
