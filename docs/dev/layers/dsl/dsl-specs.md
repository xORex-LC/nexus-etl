# DSL Specs

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [📐 UML диаграммы](#-uml-диаграммы)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма зависимостей](#диаграмма-зависимостей)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [🎯 DSL](#-dsl)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🛠️ Как расширять](#️-как-расширять)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
  - [🚨 Failure Modes](#-failure-modes)
  - [⚠️ Инварианты системы](#️-инварианты-системы)
  - [⏱️ Performance заметки](#️-performance-заметки)
- [🔗 Связанные документы](#-связанные-документы)
- [📝 История изменений](#-история-изменений)

---

## 📋 Обзор

**Назначение**: Pydantic-модели для всех стадий ETL pipeline + YAML-загрузка с merge-priority build options

**Ключевая ответственность**:
- Определение структуры всех DSL-конфигураций как типизированных Pydantic-моделей
- Загрузка YAML через активный registry-файл (`dataset.registry_path` или default `datasets/registry.yml`) с валидацией и шаблонизацией
- Merge-priority слияние build options: `defaults → global.base → global.stages[stage] → dataset-specific`
- Раннее выявление ошибок конфигурации (parse-time через `@model_validator`)

**Расположение в кодовой базе**:
- `connector/domain/dsl/specs/_base.py`, `specs/transform.py`, `specs/cache.py` — Pydantic-модели по доменным зонам
- `connector/domain/dsl/loader/_common.py`, `loader/transform.py`, `loader/cache.py` — YAML-загрузка и routing
- `connector/domain/dsl/build_options.py` — Compile-policy dataclasses

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
dsl/
├── specs/
│   ├── _base.py       # DslBaseModel, OperationCall
│   ├── transform.py   # Spec/Block/Rule для transform-стадий
│   └── cache.py       # Cache registry/dataset/policy/sync specs
├── loader/
│   ├── _common.py     # Общие helpers: registry/path/yaml/validate
│   ├── transform.py   # Loaders для transform-стадий + build options
│   └── cache.py       # Loaders для cache + runtime build options
└── build_options.py   # 112 строк: compile-policy dataclasses (7 классов)
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [DSL Class Diagram](../../../uml/transform/dsl/dsl_class.png) | Иерархия Spec/Block/Rule моделей |
| Activity | [DSL Compile Flow](../../../uml/transform/dsl/dsl_core_activity_compile.png) | Процесс загрузки YAML → Typed Spec |

**PlantUML исходники**: `docs/uml/transform/dsl/*.puml`

> **Примечание**: UML диаграммы находятся в процессе обновления.

### 🎭 Применённые паттерны

#### Паттерн 1: Layered Spec Pattern

**Где применяется**: Все стадии pipeline используют единообразную трёхуровневую структуру

**Реализация в коде**:
- **Rule**: `MappingRule`, `NormalizeRule`, `EnrichRule`, `MatchRule` — правило одного поля
- **Block**: `MappingBlock`, `NormalizeBlock`, `EnrichBlock`, `MatchBlock` — набор правил
- **Spec**: `MappingSpec`, `NormalizeSpec`, `EnrichSpec`, `MatchSpec` — обёртка с `dataset: str`

**Пример**:
```python
# Общая структура: Spec → Block → Rules
class MappingSpec(BaseModel):
    dataset: str              # Всегда обязателен
    mapping: MappingBlock     # Содержит rules

class MappingBlock(BaseModel):
    rules: list[MappingRule]  # Список правил

class MappingRule(BaseModel):
    target: str               # Конкретное поле
    ops: list[OperationCall]  # Операции трансформации
```

**Зачем**: Единообразная структура упрощает навигацию, генерацию кода и валидацию; каждый Spec гарантирует наличие `dataset`

#### Паттерн 2: Merge-Priority Pattern

**Где применяется**: Загрузка build options через `_load_stage_build_options()` (`loader/transform.py`)

**Реализация в коде**:
- **Defaults**: Hardcoded в `@dataclass(frozen=True)` полях `BaseDslBuildOptions`
- **Global base**: `registry.yml → build_options.base`
- **Global stage**: `registry.yml → build_options.stages[stage]`
- **Dataset stage**: `registry.yml → datasets[dataset].build_options[stage]`

**Пример** (`registry.yml`):
```yaml
build_options:
  base:
    strict: false              # Global для всех стадий
  stages:
    mapping:
      require_targets_exist_in_sink_spec: true  # Global для mapping
datasets:
  employees:
    build_options:
      mapping:
        strict: true           # Override для employees.mapping
```

**Результат слияния** (для employees/mapping):
```python
MapDslBuildOptions(
    strict=True,                              # dataset override
    require_targets_exist_in_sink_spec=True,  # global stage
    fail_on_unknown_ops=True,                 # default
)
```

**Зачем**: Гибкая конфигурация с разумными defaults; возможность задать политику глобально и переопределить для конкретного датасета

#### Паттерн 3: Shorthand Expansion

**Где применяется**: `MappingRule`, `NormalizeRule`, `MetaRule` — авто-раскрытие `op` + `args` в `ops`

**Реализация в коде**:
- `MappingRule._validate_targets_sources()` line 44: `op` → `ops: [OperationCall(op=..., args=...)]`
- `NormalizeRule._normalize_ops()` line 198: аналогичная логика
- `MetaRule._normalize_ops()` line 71: аналогичная логика
- `EnrichRule._normalize_allow_if()` line 271: `allow_if: str` → `OperationCall`

**Пример**:
```yaml
# Shorthand (одна операция):
- target: email
  source: rawEmail
  op: lower

# Эквивалентная полная форма:
- target: email
  source: rawEmail
  ops:
    - op: lower
      args: {}
```

**Зачем**: Сокращает YAML для частого случая одной операции, сохраняя полную форму для цепочек

### Диаграмма зависимостей

```
[YAML files]                    [registry.yml]
     ↓                               ↓
[_read_yaml()]              [_load_registry_or_raise()]
     ↓                               ↓
     └──────────┐   ┌────────────────┘
                ↓   ↓
    [_load_dataset_stage_spec()]
                ↓
    [post_load hooks (templates)]
                ↓
    [_validate_spec_or_raise()]  →  [Pydantic model_validate()]
                ↓
    [Typed Spec: MappingSpec, NormalizeSpec, ...]
                                         ↓
                           [Layer-Specific DSL Compilers]

[registry.yml → build_options]
                ↓
    [_load_stage_build_options()]  →  [build_options_from_mapping()]
                ↓
    [Typed Options: MapDslBuildOptions, ...]
```

---

## 🔑 Ключевые абстракции

### Спецификации по стадиям

| Spec | Block | Rules | Стадия | Расположение |
|------|-------|-------|--------|-------------|
| `MappingSpec` | `MappingBlock` | `MappingRule`, `MetaRule` | mapping | `specs/transform.py` |
| `NormalizeSpec` | `NormalizeBlock` | `NormalizeRule` | normalize | `specs/transform.py` |
| `EnrichSpec` | `EnrichBlock` | `EnrichRule` | enrich | `specs/transform.py` |
| `ValidationSpec` | `ValidationBlock` | `FieldCheck`, `ConditionalCheck` | validate | `specs/transform.py` |
| `MatchSpec` | `MatchBlock` | `MatchRule` | match | `specs/transform.py` |
| `ResolveSpec` | `ResolveBlock` | `ResolveLinkSpec`, `ResolveDiffSpec` и др. | resolve | `specs/transform.py` |
| `SourceSpec` | `SourceConfig` | `SourceFieldSpec` | extract | `specs/transform.py` |
| `SinkSpec` | `SinkBlock` | `SinkFieldSpec` | sink (target) | `specs/transform.py` |

### Cache спецификации

| Spec | Назначение | Расположение |
|------|-----------|-------------|
| `CacheRegistrySpec` | Реестр cache-датасетов и политик | `specs/cache.py` |
| `CacheDatasetSpec` | Спецификация одного cache-датасета | `specs/cache.py` |
| `CacheSyncSpec` | Контракт sync target→cache | `specs/cache.py` |
| `CachePolicySpec` | Глобальные cache политики | `specs/cache.py` |

### Build Options

| Класс | Стадия | Специфичные флаги | Расположение |
|-------|--------|-------------------|-------------|
| `BaseDslBuildOptions` | Все | `strict`, `fail_on_unknown_ops` | `build_options.py` line 16 |
| `MapDslBuildOptions` | mapping | `require_targets_exist_in_sink_spec` | `build_options.py` line 29 |
| `NormalizeDslBuildOptions` | normalize | `validate_only_touched_fields` | `build_options.py` line 39 |
| `EnrichDslBuildOptions` | enrich | `require_match_key` | `build_options.py` line 49 |
| `MatchDslBuildOptions` | match | `require_primary_identity_rule` | `build_options.py` line 59 |
| `ResolveDslBuildOptions` | resolve | `allow_pending_links` | `build_options.py` line 69 |
| `CacheDslBuildOptions` | cache | `require_sync_dataset_match`, `fail_on_unknown_dependencies`, `fail_on_unknown_pk_fields`, `fail_on_unknown_index_fields`, `fail_on_duplicate_projection_targets`, `fail_on_unknown_projection_targets`, `forbid_is_deleted_and_soft_delete_together` | `build_options.py` line 79 |

### Функции загрузки

| Функция | Возвращает | Расположение |
|---------|-----------|-------------|
| `load_mapping_spec_for_dataset()` | `MappingSpec` | `loader/transform.py` |
| `load_source_spec_for_dataset()` | `SourceSpec` | `loader/transform.py` |
| `load_normalize_spec_for_dataset()` | `NormalizeSpec` | `loader/transform.py` |
| `load_enrich_spec_for_dataset()` | `EnrichSpec` | `loader/transform.py` |
| `load_validate_spec_for_dataset()` | `ValidationSpec` | `loader/transform.py` |
| `load_match_spec_for_dataset()` | `MatchSpec` | `loader/transform.py` |
| `load_resolve_spec_for_dataset()` | `ResolveSpec` | `loader/transform.py` |
| `load_sink_spec_for_dataset()` | `SinkSpec` | `loader/transform.py` |
| `load_cache_registry_spec()` | `CacheRegistrySpec` | `loader/cache.py` |
| `load_cache_dataset_spec_for_dataset()` | `CacheDatasetSpec` | `loader/cache.py` |

---

## 🗂️ Модели данных

### Dataclass: `OperationCall`

**Назначение**: Универсальный дескриптор вызова DSL-операции. Используется во всех стадиях pipeline.

**Структура**:
```python
class OperationCall(BaseModel):
    op: str                                  # Имя операции (напр. "trim", "lower")
    args: dict[str, Any] = Field(default_factory=dict)  # Аргументы операции
```

**Lifecycle**:
1. **Создание**: При парсинге YAML (`model_validate`) или через shorthand expansion (`op` → `ops`)
2. **Хранение**: Внутри `MappingRule.ops`, `NormalizeRule.ops`, `EnrichRule.ops`, `CacheProjectionRuleSpec.ops` и др.
3. **Потребление**: `TransformationEngine.apply()` — `registry.get(op_call.op)` + `func(value, **op_call.args)`

**Инварианты**:
- `op` — непустая строка, соответствует имени в `OperationRegistry`
- `args` — словарь, соответствует именованным параметрам функции операции

---

### Dataclass: `MappingRule`

**Назначение**: Правило маппинга одного (или нескольких) полей из source в target

**Структура**:
```python
class MappingRule(BaseModel):
    target: str | None = None                # Одно выходное поле
    targets: list[str] | None = None         # Несколько выходных полей (XOR с target)
    source: str | None = None                # Одно входное поле
    sources: list[str] | None = None         # Несколько входных полей (XOR с source)
    ops: list[OperationCall] = []            # Цепочка операций
    op: str | None = None                    # Shorthand: одна операция
    args: dict[str, Any] | None = None       # Shorthand: аргументы op
    required: bool = False                   # Обязательное поле?
    on_error: "error" | "warn" = "error"     # Severity при ошибке
```

**Валидация** (`@model_validator` line 44):
1. `target` или `targets` обязательно (хотя бы одно)
2. Если `op` задан и `ops` пуст → авто-раскрытие: `ops = [OperationCall(op=op, args=args or {})]`
3. Если нет `source`/`sources` → проверяет наличие `const` операции в `ops`

**YAML примеры**:
```yaml
# Простой маппинг одного поля
- target: email
  source: rawEmail
  op: lower

# Маппинг из нескольких source → один target (coalesce)
- target: phone
  sources: [mobilePhone, workPhone, homePhone]
  ops:
    - op: coalesce
    - op: trim

# Константное значение
- target: source_system
  op: const
  args: { value: "HR" }

# Один source → несколько targets (split_name)
- targets: [last_name, first_name, middle_name]
  source: full_name
  ops:
    - op: split_name
      args: { fields: [last_name, first_name, middle_name] }
```

---

### Dataclass: `EnrichRule`

**Назначение**: Самая сложная rule-модель. Описывает `generate`/`lookup` правило enrich, включая условную генерацию и stage-specific conflict policy.

**Структура**:
```python
class EnrichRule(BaseModel):
    name: str                                              # Уникальное имя правила
    target: str                                            # Целевое поле
    build: SourceOpsBlock | None = None                    # Базовый source/sources + ops pipeline
    when: EnrichConditionalBlock | None = None             # Условный predicate block
    then: EnrichConditionalBlock | None = None             # Append block для when=true
    provider: ProviderRef | None = None                    # Ссылка на runtime provider
    value_path: str | None = None                          # JSON path в ответе provider
    source: str | None = None                              # Одно входное поле
    sources: list[str] | None = None                       # Несколько входных полей
    ops: list[OperationCall] = []                          # Цепочка операций
    on_error: "error" | "warn" = "error"                   # Severity при ошибке
    merge: "recompute_always" | "fill_only_if_empty" | ... | None  # Политика merge
    exists: ExistsRef | None = None                        # Exists-проверка через provider
    allow_if: OperationCall | str | None = None            # Guard-условие (str → OperationCall)
    on_conflict: EnrichConflictPolicy | None = None        # enrich-specific conflict policy
    max_attempts: int | None = None                        # Макс. попыток provider call
    run_when_errors: "never" | "if_any" | "always" | None  # Запуск при ошибках
    missing_error_code: str | None = None                  # Код ошибки при missing
    conflict_error_code: str | None = None                 # Код ошибки при conflict
    error_field: str | None = None                         # Поле для привязки ошибки
```

**Валидация** (`@model_validator` и block validators):
- `allow_if` строка → авто-раскрытие в `OperationCall(op=allow_if, args={})`
- `then` нельзя задавать без `when`
- `lookup`-правила не могут объявлять `build/when/then/on_conflict`
- `retry_with_suffixes` требует непустой `suffixes`

### Dataclass: `SourceOpsBlock`

**Назначение**: Переиспользуемый shared DSL block для правил, которым нужен `source/sources + ops` контракт.

**Структура**:
```python
class SourceOpsBlock(BaseModel):
    source: str | None = None
    sources: list[str] | None = None
    ops: list[OperationCall] = []
```

**Инварианты**:
- должен быть задан ровно один из `source` или `sources`
- block сам по себе не содержит stage-runtime semantics; её задаёт layer compiler

---

### Dataclass: `BaseDslBuildOptions`

**Назначение**: Базовый класс compile-policy флагов для всех DSL стадий

**Структура**:
```python
@dataclass(frozen=True)
class BaseDslBuildOptions:
    strict: bool = False                    # Строгий режим компиляции
    fail_on_unknown_ops: bool = True        # Ошибка на неизвестную операцию
```

**Lifecycle**:
1. **Создание**: `build_options_from_mapping(cls, merged_dict, strict=...)` — создание с поддержкой strict/non-strict режима
2. **Хранение**: Передаётся в `LayerDsl.__init__(options=...)` каждого layer compiler
3. **Потребление**: Layer compiler проверяет флаги во время компиляции

**Инварианты**:
- `frozen=True` — опции не изменяются после создания
- `build_options_from_mapping()` в non-strict игнорирует неизвестные ключи, в strict поднимает `BUILD_OPTIONS_UNKNOWN_KEYS`
- Все поля имеют defaults — можно создать `cls()` без аргументов

---

### Cache Policy Specs

**Назначение**: Иерархия Pydantic-моделей для глобальных cache-политик

**Структура**:
```python
CachePolicySpec                         # Контейнер всех политик
├── CacheRefreshPolicySpec              # refresh: {with_deps_default}
├── DriftPolicySpec                     # drift: {mode, on_hash_mismatch, rebuild_scope}
├── ClearPolicySpec                     # clear: {cascade_default, preserve_service_tables, reset_meta_on_clear}
├── StatusPolicySpec                    # status: {enable_orphan_check, degraded_on_hash_mismatch}
└── RetentionPolicySpec                 # retention: {pending_retention_days, identity_retention_days, ...}
```

---

## 🎯 DSL

### Структура registry.yml

**Назначение**: Активный registry-файл связывает датасеты с YAML-файлами стадий.
По умолчанию loader использует `datasets/registry.yml`, но runtime может переключить
путь через `dataset.registry_path` / `ANKEY_DATASET__REGISTRY_PATH`.

```yaml
# active registry file

datasets:
  employees:
    dataset: employees
    source: employees/source_2/source.yaml         # → SourceSpec
    mapping: employees/source_2/mapping.yaml       # → MappingSpec
    normalize: employees.normalize.yaml            # → NormalizeSpec
    enrich: employees.enrich.yaml                  # → EnrichSpec
    validate: employees.validate.yaml              # → ValidationSpec
    match: employees.match.yaml                    # → MatchSpec
    resolve: employees.resolve.yaml                # → ResolveSpec
    sink: employees.sink.yaml                      # → SinkSpec
    build_options:                                 # Per-dataset overrides
      mapping:
        strict: true

build_options:                                     # Global build options
  base:
    strict: false
  stages:
    mapping:
      require_targets_exist_in_sink_spec: true
    cache:
      fail_on_unknown_dependencies: true

cache:                                             # Cache registry
  version: 1
  policy:
    refresh: { with_deps_default: true }
    drift: { mode: strict, on_hash_mismatch: fail }
    clear: { cascade_default: false }
  datasets:
    employees:
      cache_spec: employees/employees.cache.yaml
      depends_on: []
```

### Routing: dataset → stage → YAML file → Spec

```
load_mapping_spec_for_dataset("employees")
    ↓
_load_dataset_stage_spec(dataset="employees", stage="mapping")
    ↓
_load_registry_or_raise()  →  active registry file
    ↓
_resolve_dataset_path()  →  "datasets/employees/source_2/mapping.yaml"
    ↓
_read_yaml()  →  raw dict
    ↓
[post_load hook: None для mapping]
    ↓
_validate_spec_or_raise()  →  MappingSpec.model_validate(raw)
    ↓
MappingSpec(dataset="employees", mapping=MappingBlock(...))
```

---

## 📊 Ключевые методы и алгоритмы

### Обзор сложных методов

| Метод | Строк | Сложность | Назначение |
|-------|-------|-----------|------------|
| `_load_dataset_stage_spec()` | 28 | O(1) | Центральный загрузочный pipeline |
| `_load_stage_build_options()` | 25 | O(1) | 4-уровневое слияние build options |
| `load_cache_build_options_for_runtime()` | 38 | O(d) | 5-уровневое слияние с CLI overrides |
| `_expand_enrich_templates()` | 38 | O(r) | Раскрытие шаблонов enrich |
| `_extract_cache_registry_payload()` | 14 | O(1) | Dual-format extraction cache registry |

---

### Метод: `_load_dataset_stage_spec()`

**Расположение**: `connector/domain/dsl/loader/_common.py`

**Сигнатура**:
```python
def _load_dataset_stage_spec(
    *, dataset: str, stage: str, spec_cls: type[TSpec], code: str,
    post_load=None,
) -> TSpec:
```

**Назначение**: Центральный метод загрузки DSL-спецификации для конкретного датасета и стадии. Все public `load_*_spec_for_dataset()` функции делегируют сюда.

---

**Алгоритм** (pseudocode с номерами строк):

```
1. Load registry (line 463)
   registry = _load_registry_or_raise()
   → Читает активный registry file (`dataset.registry_path` или default `datasets/registry.yml`)
   → Если файл не найден или невалиден → DslLoadError("DSL_REGISTRY_INVALID")

2. Resolve path (line 464)
   stage_path = _resolve_dataset_path(registry, dataset, stage)
   → datasets[dataset][stage] → "employees/source_2/mapping.yaml"
   → Если dataset не найден → DslLoadError("DSL_REGISTRY_INVALID")
   → Если stage не найден → DslLoadError("DSL_REGISTRY_INVALID")

3. Read YAML (line 465)
   raw = _read_yaml_or_raise(stage_path)
   → yaml.safe_load() → dict
   → Если ошибка чтения → DslLoadError(code=code)

4. Post-load hook (lines 466-476)
   IF post_load is not None:
       raw = post_load(raw)
       → Для enrich: _expand_enrich_templates()
       → Если DslLoadError — пробрасывает
       → Если другое исключение → DslLoadError(code=code)

5. Validate (lines 477-482)
   spec = spec_cls.model_validate(raw)
   → Pydantic валидация + @model_validator hooks
   → Если невалидно → DslLoadError(code=code, details={dataset, stage, path})

RETURN spec
```

**ASCII Flow**:

```
dataset + stage
      ↓
[registry.yml] → path
      ↓
[YAML file] → raw dict
      ↓
[post_load?] → processed dict
      ↓
[Pydantic] → Typed Spec
```

---

### Метод: `_load_stage_build_options()`

**Расположение**: `connector/domain/dsl/loader/transform.py`

**Сигнатура**:
```python
def _load_stage_build_options(
    dataset: str, stage: str, options_cls: type[BaseDslBuildOptions],
) -> BaseDslBuildOptions:
```

**Назначение**: 4-уровневое слияние compile-policy build options.

---

**Алгоритм** (pseudocode с номерами строк):

```
1. Load sources (lines 426-434)
   registry = _load_registry_or_raise()
   global_base     = registry["build_options"]["base"]        # Уровень 2
   global_stage    = registry["build_options"]["stages"][stage]  # Уровень 3
   dataset_stage   = registry["datasets"][dataset]["build_options"][stage]  # Уровень 4

2. Merge with priority (lines 436-439)
   merged = {}
   merged.update(global_base)        # Уровень 2 перезаписывает defaults
   merged.update(global_stage)       # Уровень 3 перезаписывает уровень 2
   merged.update(dataset_stage)      # Уровень 4 перезаписывает уровень 3

3. Build dataclass (line 440)
   strict_mode = bool(merged.get("strict", False))
   RETURN build_options_from_mapping(options_cls, merged, strict=strict_mode)
   → В strict=False фильтрует неизвестные ключи
   → В strict=True поднимает DslLoadError("BUILD_OPTIONS_UNKNOWN_KEYS")
   → Создаёт dataclass с defaults для пропущенных полей
```

**Визуализация приоритетов**:

```
Priority (low → high):

┌─────────────────────────────────┐
│ 1. Defaults (dataclass fields)  │  strict=False, fail_on_unknown_ops=True, ...
├─────────────────────────────────┤
│ 2. global.base                  │  build_options.base: {strict: false}
├─────────────────────────────────┤
│ 3. global.stages[stage]         │  build_options.stages.mapping: {require_targets...}
├─────────────────────────────────┤
│ 4. dataset.build_options[stage] │  datasets.employees.build_options.mapping: {strict: true}
└─────────────────────────────────┘
```

---

### Метод: `load_cache_build_options_for_runtime()`

**Расположение**: `connector/domain/dsl/loader/cache.py`

**Сигнатура**:
```python
def load_cache_build_options_for_runtime(
    *, dataset_overrides: dict | None = None, cli_overrides: dict | None = None,
) -> CacheDslBuildOptions:
```

**Назначение**: 5-уровневое слияние для cache runtime (расширенная версия с CLI overrides).

---

**Алгоритм** (pseudocode с номерами строк):

```
1. Load global options (lines 297-303)
   global_base  = registry["build_options"]["base"]
   global_stage = registry["build_options"]["stages"]["cache"]
   merged = {}
   merged.update(global_base)
   merged.update(global_stage)

2. Collect dataset overrides (lines 304-316)
   IF dataset_overrides is None:
       → Автоматически собирает из cache.datasets[*].build_options.cache
       → Если найдено >1 override: DslLoadError("CACHE_DSL_BUILD_OPTIONS_AMBIGUOUS")
   FOR EACH dataset (sorted):
       merged.update(dataset_overrides[dataset])

3. Apply CLI overrides (lines 317-318)
   IF cli_overrides:
       merged.update(cli_overrides)

4. Build (line 319)
   strict_mode = bool(merged.get("strict", False))
   RETURN build_options_from_mapping(CacheDslBuildOptions, merged, strict=strict_mode)
```

**Визуализация 5 уровней**:

```
Priority (low → high):

1. Defaults  →  2. global.base  →  3. global.stages.cache
      →  4. dataset overrides  →  5. CLI overrides
```

---

### Метод: `_expand_enrich_templates()`

**Расположение**: `connector/domain/dsl/loader/transform.py`

**Сигнатура**:
```python
def _expand_enrich_templates(raw: dict[str, Any]) -> dict[str, Any]:
```

**Назначение**: Раскрытие lookup-templates/presets в enrich-правила. Позволяет описать шаблон один раз и переиспользовать.

---

**Алгоритм** (pseudocode с номерами строк):

```
1. Extract templates (lines 337-340)
   templates = enrich["lookup_templates"] или enrich["lookup_presets"]
   IF list → преобразовать в dict по name

2. Expand rules (lines 342-362)
   FOR EACH rule IN enrich["lookup"]:
       template_name = rule.pop("template") или rule.pop("preset")
       IF template_name:
           template = templates[template_name]
           IF not found → DslLoadError("ENRICH_DSL_TEMPLATE_INVALID")
           merged = {**template, **rule}  # rule перезаписывает template
       ELSE:
           → оставить rule как есть

3. Cleanup (lines 364-368)
   enrich["lookup"] = expanded
   Удалить lookup_templates / lookup_presets из raw
   RETURN raw
```

---

## 🛠️ Как расширять

### Добавить новую стадию pipeline

1. **Создать Rule/Block/Spec модели** в `connector/domain/dsl/specs/transform.py` (или `specs/cache.py` для cache):
   ```python
   class MyStageRule(BaseModel):
       field: str
       ops: list[OperationCall] = Field(default_factory=list)

   class MyStageBlock(BaseModel):
       rules: list[MyStageRule]

   class MyStageSpec(BaseModel):
       dataset: str
       my_stage: MyStageBlock
   ```

2. **Создать BuildOptions** в `connector/domain/dsl/build_options.py`:
   ```python
   @dataclass(frozen=True)
   class MyStageeDslBuildOptions(BaseDslBuildOptions):
       my_custom_flag: bool = False
   ```

3. **Добавить loader-функции** в `connector/domain/dsl/loader/transform.py` (или `loader/cache.py`):
   ```python
   def load_my_stage_spec_for_dataset(dataset: str) -> MyStageSpec:
       return _load_dataset_stage_spec(
           dataset=dataset,
           stage="my_stage",
           spec_cls=MyStageSpec,
           code="MY_STAGE_DSL_SPEC_INVALID",
       )

   def load_my_stage_build_options_for_dataset(dataset: str) -> MyStageDslBuildOptions:
       return _load_stage_build_options(dataset, "my_stage", MyStageDslBuildOptions)
   ```

4. **Обновить `registry.yml`**: Добавить path к YAML файлу стадии в datasets и (опционально) build_options в stages

5. **Экспортировать** в `connector/domain/dsl/__init__.py`

### Добавить поле в существующий Spec

1. Добавить поле в соответствующий `*Rule` / `*Block` / `*Spec` класс в `specs/transform.py` или `specs/cache.py`
2. Если нужна cross-field валидация → добавить `@model_validator`
3. Если поле влияет на compile → обновить layer-specific DSL compiler

### Добавить новый build option флаг

1. Добавить поле в соответствующий `*DslBuildOptions` dataclass в `build_options.py`
2. Указать `default` значение (обязательно — для backward compatibility)
3. Использовать в layer-specific DSL compiler: `if self.options.my_flag: ...`

---

## 🔄 Взаимодействие с другими слоями

| Слой | Что использует из DSL Specs | Через что |
|------|-----------------------------|-----------|
| **Mapping** | `MappingSpec`, `MapDslBuildOptions` | `load_mapping_spec_for_dataset()`, `load_map_build_options_for_dataset()` |
| **Normalize** | `NormalizeSpec`, `NormalizeDslBuildOptions` | `load_normalize_spec_for_dataset()`, `load_normalize_build_options_for_dataset()` |
| **Enrich** | `EnrichSpec`, `EnrichDslBuildOptions` | `load_enrich_spec_for_dataset()`, `load_enrich_build_options_for_dataset()` |
| **Validate** | `ValidationSpec` | `load_validate_spec_for_dataset()` |
| **Match** | `MatchSpec`, `MatchDslBuildOptions` | `load_match_spec_for_dataset()`, `load_match_build_options_for_dataset()` |
| **Resolve** | `ResolveSpec`, `SinkSpec`, `ResolveDslBuildOptions` | `load_resolve_spec_for_dataset()`, `load_resolve_build_options_for_dataset()` |
| **Cache** | `CacheRegistrySpec`, `CacheDatasetSpec`, `CacheDslBuildOptions` | `load_cache_registry_spec()`, `load_cache_dataset_spec_for_dataset()`, `load_cache_build_options_for_runtime()` |
| **DatasetSpec** | Все `load_*` функции | Protocol `DatasetSpec` в `connector/datasets/spec.py` |

---

## 🔌 Контракты и границы

### Контракт загрузчика

```python
# Каждая load_*_spec_for_dataset() гарантирует:
# 1. Возвращает типизированный Spec или поднимает DslLoadError
# 2. YAML валиден (yaml.safe_load без ошибок)
# 3. Spec прошёл Pydantic валидацию + @model_validator hooks
# 4. post_load hooks применены (для enrich — шаблоны раскрыты)
```

### Контракт build_options_from_mapping

```python
# build_options_from_mapping(cls, data, strict=False) гарантирует:
# 1. Возвращает экземпляр cls для валидного набора ключей
# 2. В strict=False неизвестные ключи игнорируются (forward-compatibility)
# 3. В strict=True неизвестные ключи → DslLoadError("BUILD_OPTIONS_UNKNOWN_KEYS")
# 4. Пропущенные ключи заполняются defaults из dataclass
# 5. data=None → cls() с defaults
```

### Коды ошибок загрузки

| Код | Условие | Расположение |
|-----|---------|-------------|
| `DSL_REGISTRY_INVALID` | registry.yml не найден, невалиден или dataset/stage отсутствует | `loader/_common.py`, `loader/transform.py` |
| `MAP_DSL_SPEC_INVALID` | MappingSpec невалиден | `loader/transform.py` |
| `SOURCE_DSL_SPEC_INVALID` | SourceSpec невалиден | `loader/transform.py` |
| `SOURCE_DSL_LOCATION_INVALID` | location и location_ref пусты | `loader/transform.py` |
| `NORMALIZE_DSL_SPEC_INVALID` | NormalizeSpec невалиден | `loader/transform.py` |
| `ENRICH_DSL_SPEC_INVALID` | EnrichSpec невалиден | `loader/transform.py` |
| `ENRICH_DSL_TEMPLATE_INVALID` | Неизвестный lookup template | `loader/transform.py` |
| `VALIDATE_DSL_SPEC_INVALID` | ValidationSpec невалиден | `loader/transform.py` |
| `MATCH_DSL_SPEC_INVALID` | MatchSpec невалиден | `loader/transform.py` |
| `RESOLVE_DSL_SPEC_INVALID` | ResolveSpec невалиден | `loader/transform.py` |
| `SINK_DSL_SPEC_INVALID` | SinkSpec невалиден | `loader/transform.py` |
| `CACHE_DSL_REGISTRY_INVALID` | Cache registry невалиден | `loader/cache.py` |
| `CACHE_DSL_SPEC_INVALID` | CacheDatasetSpec невалиден или mismatch dataset | `loader/cache.py` |
| `CACHE_DSL_DEP_MISSING` | Dataset отсутствует в cache registry | `loader/cache.py` |
| `CACHE_DSL_BUILD_OPTIONS_AMBIGUOUS` | Авто-выбор dataset overrides невозможен (>1 dataset) | `loader/cache.py` |
| `BUILD_OPTIONS_UNKNOWN_KEYS` | strict-mode build options содержит неизвестные ключи | `build_options.py` |

### Границы слоёв

**Разрешенные зависимости**:
- ✅ `loader/transform.py` и `loader/cache.py` → `specs/*` (import Spec classes)
- ✅ `loader/*` → `build_options.py` (import BuildOptions classes)
- ✅ `loader/*` → `issues.py` (import DslLoadError)
- ✅ `loader/_common.py` → `yaml` (YAML parsing)

**Запрещенные зависимости**:
- ❌ `specs/*` → `loader/*`/`engine.py` — specs остаются чистыми data models
- ❌ `loader/*` → `engine.py` — загрузчик не выполняет операции
- ❌ `loader/*` → `connector/infra/*` — загрузчик не обращается к инфраструктуре
- ❌ `build_options.py` → что-либо кроме `dataclasses` — чистые value objects

---

## 💡 Типичные сценарии

### Сценарий 1: Загрузка mapping spec

**Задача**: Загрузить mapping DSL для датасета "employees"

**Решение**:
```python
from connector.domain.dsl import load_mapping_spec_for_dataset

spec = load_mapping_spec_for_dataset("employees")
# spec.dataset == "employees"
# spec.mapping.rules == [MappingRule(...), ...]
# spec.mapping.meta == [MetaRule(...), ...]
```

**Что происходит под капотом**:
1. Читает active registry file (`dataset.registry_path` или default `datasets/registry.yml`)
2. Находит `datasets.employees.mapping` → `"employees/source_2/mapping.yaml"`
3. Читает YAML файл
4. Валидирует через `MappingSpec.model_validate(raw)`

### Сценарий 2: Слияние build options с override

**Задача**: Получить compile-policy для mapping стадии employees, где глобально strict=false, но для employees strict=true

**Решение**:
```python
from connector.domain.dsl import load_map_build_options_for_dataset

options = load_map_build_options_for_dataset("employees")
# options.strict == True  (dataset override перезаписывает global)
# options.fail_on_unknown_ops == True  (default)
```

### Сценарий 3: Загрузка enrich spec с шаблонами

**Задача**: Использовать lookup_template для переиспользования правил

**YAML** (`employees.enrich.yaml`):
```yaml
dataset: employees
enrich:
  lookup_templates:
    - name: cache_lookup
      provider: { name: cache }
      on_error: warn
      merge: fill_only_if_empty

  lookup:
    - template: cache_lookup    # ← ссылка на шаблон
      name: resolve_org
      target: organization_name
      value_path: name
```

**Результат после _expand_enrich_templates()**:
```python
EnrichRule(
    name="resolve_org",
    target="organization_name",
    provider=ProviderRef(name="cache"),
    on_error="warn",
    merge="fill_only_if_empty",
    value_path="name",
)
```

---

## 📌 Важные детали

### Особенности реализации

- **`model_config = {"populate_by_name": True}`**: Используется в `MappingBlock`, `ValidationSpec`, `CacheDatasetSpec` для поддержки alias-полей (`schema_` вместо `schema`, `validate_` вместо `validate`) — обход зарезервированных слов Python
- **`_repo_root()`**: Ищет корень проекта подъёмом по `parents` до `datasets/registry.yml` (fallback на `parents[4]` в `loader/_common.py`). Привязан к расположению `loader/_common.py`
- **Dual-format cache registry**: `_extract_cache_registry_payload()` поддерживает как `{cache: {version, datasets}}` (встроен в registry.yml), так и `{version, datasets}` (отдельный файл)

### 🚨 Failure Modes

| Исключение | Условие возникновения | Поведение системы | Как обработать |
|------------|----------------------|-------------------|---------------|
| `DslLoadError("DSL_REGISTRY_INVALID")` | registry.yml не найден или невалиден | Fail-fast, загрузка невозможна | Проверить наличие и формат `datasets/registry.yml` |
| `DslLoadError("*_DSL_SPEC_INVALID")` | YAML файл стадии не найден или невалиден | Fail-fast, spec не загружен | Проверить путь в registry.yml и содержимое YAML файла |
| `DslLoadError("ENRICH_DSL_TEMPLATE_INVALID")` | Ссылка на несуществующий template | Fail-fast при загрузке enrich | Проверить имя template в lookup_templates |
| `DslLoadError("CACHE_DSL_DEP_MISSING")` | Dataset не найден в cache registry | Fail-fast при загрузке cache dataset | Добавить dataset в cache.datasets |
| `Pydantic ValidationError` | Данные не соответствуют схеме модели | Оборачивается в DslLoadError | Проверить структуру YAML: обязательные поля, типы, ranges |

### ⚠️ Инварианты системы

1. **Инвариант: Каждый Spec содержит `dataset: str`**
   - **Что**: Все `*Spec` классы имеют обязательное поле `dataset`
   - **Почему важно**: Позволяет однозначно привязать spec к датасету; используется в diagnostics
   - **Где проверяется**: Pydantic валидация при `model_validate()`

2. **Инвариант: specs/* не имеет внешних зависимостей**
   - **Что**: `specs/_base.py`, `specs/transform.py`, `specs/cache.py` импортируют только базовые DSL-модели и `pydantic` — без зависимостей на engine/infra
   - **Почему важно**: Specs — чистые data models, переиспользуемые везде без circular imports
   - **Где проверяется**: Архитектурные тесты (`tests/architecture/`)

3. **Инвариант: Build options поддерживает strict/non-strict режим**
   - **Что**: `build_options_from_mapping()` игнорирует unknown keys в non-strict и бросает `BUILD_OPTIONS_UNKNOWN_KEYS` в strict
   - **Почему важно**: Можно выбрать между forward-compatibility и fail-fast контролем конфигурации
   - **Где проверяется**: `build_options.py` (`strict` ветка и фильтрация `key in allowed`)

4. **Инвариант: @model_validator нормализует shorthand**
   - **Что**: `op` + `args` автоматически раскрываются в `ops` при parse-time
   - **Почему важно**: После парсинга код может безопасно работать только с `ops`
   - **Где проверяется**: `MappingRule` line 48, `NormalizeRule` line 200, `MetaRule` line 73

### ⏱️ Performance заметки

**Стоимость загрузки**:

| Операция | Сложность | Примечание |
|----------|-----------|------------|
| `_read_yaml()` | O(n) | n = размер YAML файла |
| Pydantic `model_validate()` | O(f) | f = количество полей в модели |
| `_expand_enrich_templates()` | O(r×t) | r = rules, t = templates |
| `_load_stage_build_options()` | O(1) | 3 dict.update() |

**Важно**: Все загрузки происходят один раз при старте pipeline. Runtime-стоимость — 0.

### Частые ошибки

- ❌ **Использовать `schema` вместо `schema_` в Python коде**: `MappingBlock.schema_` (alias `schema`), `CacheDatasetSpec.schema_` (alias `schema`) — в YAML пишется `schema:`, в Python — `spec.schema_`
- ✅ **Делай так**: В YAML — `schema:`, в Python — `spec.schema_`

- ❌ **Забыть `source`/`sources` в MappingRule без `const`**: Валидатор бросит ошибку
- ✅ **Делай так**: Либо указать `source`/`sources`, либо добавить `op: const` с `args: { value: ... }`

- ❌ **Одновременно `target` и `targets`**: Допускается, но `target` игнорируется при наличии `targets`
- ✅ **Делай так**: Используй либо `target`, либо `targets` — не оба

---

## 🔗 Связанные документы

- [DSL Engine](./dsl-engine.md) — Движок операций, реестр, 45 core operations
- [DSL Diagnostics](./dsl-diagnostics.md) — Модель ошибок, диагностика, карта интеграции
- [Cache DSL](../cache/cache-dsl.md) — Как cache слой использует specs и loader
- [Resolve DSL](../resolver/resolve-dsl.md) — Как resolve слой использует specs и loader

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-12 | Создан документ | xORex-LC |
| 2026-05-05 | Уточнена загрузка через active registry path и обновлены примеры stage-path под `employees/source_2` | xORex-LC |
| 2026-05-06 | Обновлён enrich rule contract: добавлены `build/when/then/on_conflict` и задокументирован shared `SourceOpsBlock` | xORex-LC |
