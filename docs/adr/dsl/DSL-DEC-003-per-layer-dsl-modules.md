# DSL-DEC-003: Per-layer DSL модули и чистый DSL Core

> **Статус**: Принято
> **Дата принятия**: 2026-02-17
> **Решает проблему**: [DSL-PROBLEM-003](./DSL-PROBLEM-003-dsl-core-mixed-responsibilities.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

`connector/domain/dsl/` смешивает generic DSL инфраструктуру (engine, registry, base models, loader utils)
с transform-специфичными (~40 spec-моделей, 15+ loaders) и cache-специфичными артефактами.
`target_dsl/` уже реализован как чистый per-layer модуль (TARGET-DEC-004).
Нужно привести transform и cache к такому же паттерну.

Подробности: [DSL-PROBLEM-003](./DSL-PROBLEM-003-dsl-core-mixed-responsibilities.md).

---

## 🎯 Решение

Разделить `connector/domain/dsl/` на три уровня:

1. **DSL Core** (`connector/domain/dsl/`) — generic фундамент, 0 бизнес-логики.
2. **Per-layer DSL modules** (`transform_dsl/`, `cache_dsl/`, `target_dsl/`) — layer-специфичные specs, loaders, build options, компиляторы.
3. **YAML Specifications** (`datasets/`) — конкретные бизнес-конфигурации.

---

## 🏗️ Архитектурное решение

### Целевая структура

```
connector/domain/
├── dsl/                          ← A. DSL Core (generic фундамент)
│   ├── __init__.py               ← Public API: только generic экспорты
│   ├── issues.py                 ← DslSeverity, DslLoadError, DslIssue
│   ├── diagnostics.py            ← DslIssue → DiagnosticItem (мост к domain.models)
│   ├── specs/
│   │   ├── __init__.py
│   │   └── _base.py              ← DslBaseModel, OperationCall
│   ├── engine.py                 ← TransformationEngine
│   ├── registry.py               ← OperationRegistry, Operation
│   ├── ops.py                    ← ~25 core ops (trim, lower, uuid, coalesce, ...)
│   ├── helpers.py                ← apply_ops()
│   ├── build_options.py          ← BaseDslBuildOptions + build_options_from_mapping() ТОЛЬКО
│   └── loader/
│       ├── __init__.py           ← read_yaml, find_repo_root, load_registry, validate_spec,
│       │                            load_spec_from_path
│       └── _common.py            ← Реализация (только generic часть)
│
├── transform_dsl/                ← B. Transform DSL (layer-специфика)
│   ├── __init__.py               ← Public API: все transform specs + loaders + build options
│   ├── specs/
│   │   ├── __init__.py           ← Реэкспорт всех spec-моделей
│   │   ├── mapping.py            ← MappingSpec, MappingRule, MappingBlock, MetaRule, MappingSchema
│   │   ├── source.py             ← SourceSpec, SourceConfig, SourceFieldSpec
│   │   ├── sink.py               ← SinkSpec, SinkBlock, SinkFieldSpec
│   │   ├── normalize.py          ← NormalizeSpec, NormalizeBlock, NormalizeRule
│   │   ├── enrich.py             ← EnrichSpec, EnrichBlock, EnrichRule, ProviderRef, ExistsRef, ...
│   │   ├── validate.py           ← ValidationSpec, ValidationBlock, FieldCheck, ConditionalCheck
│   │   ├── match.py              ← MatchSpec, MatchBlock, MatchRule, FuzzySpec, SourceDedupSpec
│   │   └── resolve.py            ← ResolveSpec, ResolveBlock, ResolveDiffSpec, ResolveLinkSpec, ...
│   ├── loader.py                 ← load_mapping_spec_for_dataset(), load_enrich_spec_for_dataset(), ...
│   ├── build_options.py          ← MapDslBuildOptions, NormalizeDslBuildOptions, EnrichDslBuildOptions, ...
│   └── compilers/                ← DSL компиляторы (см. DSL-DEC-004)
│       ├── __init__.py
│       ├── mapping.py            ← MapperDsl → CompiledMapRules
│       ├── normalize.py          ← NormalizerDsl → CompiledNormalizeRules
│       ├── enrich.py             ← EnricherDsl → CompiledEnrichOps
│       ├── match.py              ← MatchDsl → CompiledMatchRules
│       └── resolve.py            ← ResolveDsl → CompiledResolveRules
│
├── cache_dsl/                    ← B. Cache DSL (layer-специфика)
│   ├── __init__.py               ← Public API
│   ├── specs.py                  ← CacheRegistrySpec, CacheDatasetSpec, CacheSyncSpec, CachePolicySpec, ...
│   ├── loader.py                 ← load_cache_registry_spec(), load_cache_dataset_spec_for_dataset(), ...
│   └── build_options.py          ← CacheDslBuildOptions
│
├── target_dsl/                   ← B. Target DSL (уже реализован ✓)
│   ├── __init__.py
│   └── loader.py
│
└── transform/                    ← Runtime execution (без *_dsl.py)
    ├── mapping/
    │   ├── mapper_core.py        ← MapperCore(CompiledMapRules)
    │   └── mapper_engine.py      ← MapperEngine
    ├── normalize/
    │   ├── normalizer_core.py    ← NormalizerCore(CompiledNormalizeRules)
    │   └── normalizer_engine.py  ← NormalizerEngine
    ├── enrich/
    │   ├── enricher_core.py      ← EnricherCore(CompiledEnrichOps)
    │   └── enricher_engine.py    ← EnricherEngine
    ...
```

### Граф зависимостей

```
                    dsl/ (core)
                   /    |     \
                  /     |      \
        transform_dsl  cache_dsl  target_dsl
              |           |            |
              ▼           ▼            ▼
        transform/*   cache_core   infra/target/providers/*
              \          |          /
               ▼         ▼        ▼
              datasets/employees/spec.py (orchestrator)
```

Стрелки идут только вниз. Единственное исключение — `target_dsl → infra.target.core.spec_models`
(для `TargetSpec`), которое допустимо, т.к. target spec models принадлежат infra-core.

### Разделение `_common.py`

| Функция | Куда | Обоснование |
|---------|------|------------|
| `_read_yaml()` → `read_yaml` | dsl-core | Generic YAML чтение |
| `_repo_root()` → `find_repo_root` | dsl-core | Generic поиск корня проекта |
| `_load_registry_or_raise()` → `load_registry` | dsl-core | Generic загрузка registry |
| `_validate_spec_or_raise()` → `validate_spec` | dsl-core | Generic Pydantic валидация |
| `_load_spec_from_path()` → `load_spec_from_path` | dsl-core | Generic загрузка по пути |
| `_read_yaml_or_raise()` | dsl-core | Generic обёртка |
| `_resolve_dataset_path()` | **transform_dsl/loader.py** | Знает о `registry.datasets.{name}.{stage}` |
| `_load_dataset_stage_spec()` | **transform_dsl/loader.py** | Композиция resolve + read + validate |

### Разделение `build_options.py`

| Класс | Куда |
|-------|------|
| `BaseDslBuildOptions` | dsl-core |
| `build_options_from_mapping()` | dsl-core |
| `MapDslBuildOptions` | transform_dsl |
| `NormalizeDslBuildOptions` | transform_dsl |
| `EnrichDslBuildOptions` | transform_dsl |
| `MatchDslBuildOptions` | transform_dsl |
| `ResolveDslBuildOptions` | transform_dsl |
| `CacheDslBuildOptions` | cache_dsl |

### Разбиение `specs/transform.py` (660+ строк → 8 файлов)

| Spec | Файл в `transform_dsl/specs/` |
|------|-------------------------------|
| MappingSpec, MappingRule, MetaRule, MappingSchema, MappingBlock | `mapping.py` |
| SourceSpec, SourceConfig, SourceFieldSpec | `source.py` |
| SinkSpec, SinkBlock, SinkFieldSpec | `sink.py` |
| NormalizeSpec, NormalizeBlock, NormalizeRule | `normalize.py` |
| EnrichSpec, EnrichBlock, EnrichRule, ProviderRef, ExistsRef, MatchKeySpec, SecretsSpec | `enrich.py` |
| ValidationSpec, ValidationBlock, FieldCheck, ConditionalCheck | `validate.py` |
| MatchSpec, MatchBlock, MatchRule, SourceDedupSpec, FuzzySpec | `match.py` |
| ResolveSpec, ResolveBlock, + ~10 вложенных моделей | `resolve.py` |

### Публичный API после миграции

**dsl-core (`connector/domain/dsl/`):**
```python
# Errors
DslLoadError, DslIssue, DslSeverity
# Base models
DslBaseModel, OperationCall
# Engine
TransformationEngine, EngineResult
# Registry
OperationRegistry, Operation, register_core_ops
# Build options
BaseDslBuildOptions, build_options_from_mapping
# Loader utils
read_yaml, find_repo_root, load_registry, validate_spec, load_spec_from_path
# Diagnostics bridge
append_dsl_issue, append_dsl_issues, translate_dsl_load_error
# Helpers
apply_ops
```

**transform_dsl (`connector/domain/transform_dsl/`):**
```python
# Specs (все transform Pydantic модели)
MappingSpec, MappingRule, ..., EnrichSpec, EnrichRule, ..., ResolveSpec, ...
# Loaders
load_mapping_spec_for_dataset, load_enrich_spec_for_dataset, ...
load_source_spec_for_dataset, load_sink_spec_for_dataset, ...
load_map_build_options_for_dataset, ...
# Build options
MapDslBuildOptions, NormalizeDslBuildOptions, EnrichDslBuildOptions, ...
# Compilers (см. DSL-DEC-004)
MapperDsl, NormalizerDsl, EnricherDsl, MatchDsl, ResolveDsl
```

**cache_dsl (`connector/domain/cache_dsl/`):**
```python
# Specs
CacheRegistrySpec, CacheDatasetSpec, CacheSyncSpec, CachePolicySpec, ...
# Loaders
load_cache_registry_spec, load_cache_dataset_spec_for_dataset, ...
# Build options
CacheDslBuildOptions
```

### Миграция импортов

**Transform compilers** (`connector/domain/transform/*/`):
```python
# Было:
from connector.domain.dsl import MappingSpec, SinkSpec, MapDslBuildOptions, TransformationEngine

# Станет:
from connector.domain.transform_dsl import MappingSpec, SinkSpec, MapDslBuildOptions
from connector.domain.dsl import TransformationEngine
```

**Cache core** (`connector/domain/cache_core/`):
```python
# Было:
from connector.domain.dsl import CacheRegistrySpec, CacheDatasetSpec, CacheDslBuildOptions

# Станет:
from connector.domain.cache_dsl import CacheRegistrySpec, CacheDatasetSpec, CacheDslBuildOptions
```

**Dataset orchestrator** (`connector/datasets/employees/spec.py`):
```python
# Было:
from connector.domain.dsl import load_mapping_spec_for_dataset, load_enrich_spec_for_dataset, ...

# Станет:
from connector.domain.transform_dsl import load_mapping_spec_for_dataset, load_enrich_spec_for_dataset, ...
```

### Компоненты

**Что переезжает:**
- `dsl/specs/transform.py` → `transform_dsl/specs/*.py` (разбиение на 8 файлов)
- `dsl/specs/cache.py` → `cache_dsl/specs.py`
- `dsl/loader/transform.py` → `transform_dsl/loader.py`
- `dsl/loader/cache.py` → `cache_dsl/loader.py`
- `_resolve_dataset_path()`, `_load_dataset_stage_spec()` из `_common.py` → `transform_dsl/loader.py`
- Per-stage build options из `build_options.py` → `transform_dsl/build_options.py` и `cache_dsl/build_options.py`
- `*_dsl.py` из `transform/*` → `transform_dsl/compilers/` (подробности в DSL-DEC-004)

**Что остаётся в dsl-core:**
- `issues.py`, `diagnostics.py`, `specs/_base.py`, `engine.py`, `registry.py`, `ops.py`, `helpers.py`
- `BaseDslBuildOptions`, `build_options_from_mapping()` в `build_options.py`
- Generic функции из `loader/_common.py`

**Что удаляется:**
- `dsl/specs/transform.py` (перемещён)
- `dsl/specs/cache.py` (перемещён)
- `dsl/loader/transform.py` (перемещён)
- `dsl/loader/cache.py` (перемещён)
- Transform-специфичные функции из `_common.py` (перемещены)
- Per-stage build options из `build_options.py` (перемещены)

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Единообразие: `transform_dsl/`, `cache_dsl/`, `target_dsl/` — одинаковый паттерн.
- ✅ DSL Core становится стабильным фундаментом: расширение на новые слои не требует его модификации.
- ✅ Чистый граф зависимостей: стрелки только вниз (core ← layer_dsl ← runtime).
- ✅ Разбиение `specs/transform.py` (660 строк → 8 файлов) улучшает навигацию и сопровождение.
- ✅ Публичный API каждого модуля отражает его зону ответственности.
- ✅ Закрывает ограничение из DSL-DEC-002: "фасад `dsl.__init__` остаётся широким".

**Недостатки (компромиссы)**:
- ⚠️ Массовое обновление импортов (~20+ файлов) — приемлемо, т.к. это разовая миграция.
- ⚠️ `transform_dsl/compilers/` зависит от dsl-core (`TransformationEngine`, `OperationRegistry`) — допустимо по графу зависимостей (стрелка вниз).
- ⚠️ `OperationCall` остаётся в dsl-core, хотя используется преимущественно в transform/cache specs — оправдано, т.к. это generic DSL-примитив (op chain applicable to any value).

**Альтернативы, которые отклонили**:
- ❌ **Подпапки внутри dsl/ (Вариант C из PROBLEM-003)**: Не решает root cause — dsl/ остаётся единым пакетом.
- ❌ **Slim-down только __init__.py**: Половинчатое решение — файлы в одном пакете, зависимости не разделены.
- ❌ **Specs рядом со stage (mapping/specs.py)**: Нарушает паттерн per-layer DSL, смешивает DSL-определение и runtime в одном пакете.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform_dsl/__init__.py` | Создан: public API |
| `connector/domain/transform_dsl/specs/*.py` | Создано 8 файлов + `__init__.py` |
| `connector/domain/transform_dsl/loader.py` | Создан: перенесён из `dsl/loader/transform.py` |
| `connector/domain/transform_dsl/build_options.py` | Создан: per-stage build options |
| `connector/domain/transform_dsl/compilers/*.py` | Создано 5 файлов (см. DSL-DEC-004) |
| `connector/domain/cache_dsl/__init__.py` | Создан: public API |
| `connector/domain/cache_dsl/specs.py` | Создан: перенесён из `dsl/specs/cache.py` |
| `connector/domain/cache_dsl/loader.py` | Создан: перенесён из `dsl/loader/cache.py` |
| `connector/domain/cache_dsl/build_options.py` | Создан: CacheDslBuildOptions |
| `connector/domain/dsl/__init__.py` | Сужен до generic-only экспортов |
| `connector/domain/dsl/build_options.py` | Оставлен: только BaseDslBuildOptions |
| `connector/domain/dsl/loader/_common.py` | Очищен: только generic функции |
| `connector/domain/dsl/specs/transform.py` | Удалён (перемещён) |
| `connector/domain/dsl/specs/cache.py` | Удалён (перемещён) |
| `connector/domain/dsl/loader/transform.py` | Удалён (перемещён) |
| `connector/domain/dsl/loader/cache.py` | Удалён (перемещён) |
| `connector/domain/transform/*/` | Удалены `*_dsl.py` (перемещены в compilers/) |
| ~20 файлов по проекту | Обновлены import paths |

### Инварианты

1. **dsl-core zero business logic**: `dsl/` не импортирует ни `transform_dsl`, ни `cache_dsl`, ни `target_dsl`.
2. **Per-layer DSL → dsl-core only**: Layer DSL модули импортируют только из `dsl/` (core), не друг из друга.
3. **Runtime → layer DSL**: Transform stages импортируют из `transform_dsl/`, не из `dsl/` напрямую для specs/loaders.
4. **specs/transform.py not found**: После миграции ни один файл не импортирует из `connector.domain.dsl.specs.transform`.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ `pytest tests/unit/` — все существующие тесты проходят после обновления импортов.
- ✅ Smoke: `from connector.domain.dsl import TransformationEngine` — импортирует без утаскивания transform specs.
- ✅ Smoke: `from connector.domain.transform_dsl import MappingSpec` — работает.
- ✅ Verify: `dsl/__init__` не содержит ни одного transform/cache-специфичного символа.

**Метрики успеха**:
- Количество символов в `dsl/__init__.__all__`: уменьшено с ~80 до ~20.
- Количество файлов в `dsl/`: уменьшено (удалены specs/transform.py, specs/cache.py, loader/transform.py, loader/cache.py).

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- `diagnostics.py` остаётся в dsl-core, хотя знает о `DiagnosticItem` из `domain.models` — приемлемо как generic bridge.
- `OperationCall` в dsl-core используется и в transform, и в cache specs — это дизайн, не ограничение.

**Риски**:
- ⚠️ Массовое обновление импортов может привести к пропущенным заменам → Митигация: `pytest` + `grep` для верификации.
- ⚠️ Сторонний код, зависящий от `connector.domain.dsl.MappingSpec`, сломается → Митигация: проект не имеет внешних потребителей; при необходимости — deprecation re-exports.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `connector/domain/transform/mapping/` | Прямое | Импорт specs из `transform_dsl`, удалить `mapper_dsl.py` |
| `connector/domain/transform/normalize/` | Прямое | Аналогично |
| `connector/domain/transform/enrich/` | Прямое | Аналогично |
| `connector/domain/transform/matcher/` | Прямое | Аналогично |
| `connector/domain/transform/resolver/` | Прямое | Аналогично |
| `connector/domain/cache_core/` | Прямое | Импорт specs из `cache_dsl` |
| `connector/infra/cache/` | Прямое | Импорт specs из `cache_dsl` |
| `connector/datasets/employees/spec.py` | Прямое | Импорт loaders из `transform_dsl` и `cache_dsl` |
| `connector/delivery/cli/runtime.py` | Минимальное | `DslLoadError`, `translate_dsl_load_error` — остаются в dsl-core |

---

## 🔗 Связанные документы

- [DSL-PROBLEM-003](./DSL-PROBLEM-003-dsl-core-mixed-responsibilities.md) — решаемая проблема
- [DSL-DEC-004](./DSL-DEC-004-standardized-compile-contract.md) — созависимое решение (compile-контракт)
- [DSL-DEC-002](./DSL-DEC-002-modular-dsl-core-and-contract-stabilization.md) — предыдущее решение
- [TARGET-DEC-004](../target/TARGET-DEC-004-target-dsl-declarative-provider.md) — эталонный per-layer DSL

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-17 | Решение предложено |
| 2026-02-17 | Решение принято после обсуждения |
