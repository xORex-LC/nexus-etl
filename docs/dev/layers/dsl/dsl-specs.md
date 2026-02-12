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
- Загрузка YAML через `datasets/registry.yml` с валидацией и шаблонизацией
- Merge-priority слияние build options: `defaults → global.base → global.stages[stage] → dataset-specific`
- Раннее выявление ошибок конфигурации (parse-time через `@model_validator`)

**Расположение в кодовой базе**:
- `connector/domain/dsl/specs.py` — Pydantic-модели (40+ классов)
- `connector/domain/dsl/loader.py` — YAML-загрузка и routing
- `connector/domain/dsl/build_options.py` — Compile-policy dataclasses

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
dsl/
├── specs.py           # 870 строк: 40+ Pydantic-моделей для всех стадий
├── loader.py          # 528 строк: YAML загрузка, routing, шаблонизация
└── build_options.py   # 112 строк: compile-policy dataclasses (7 классов)
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [DSL Specs Class Diagram](../../../uml/dsl/dsl_specs_class.png) | Иерархия Spec/Block/Rule моделей |
| Activity | [Loading Flow](../../../uml/dsl/dsl_specs_activity_loading.png) | Процесс загрузки YAML → Spec |

**PlantUML исходники**: `docs/uml/dsl/*.puml`

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

**Где применяется**: Загрузка build options через `_load_stage_build_options()` (`loader.py` line 416)

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
[_read_yaml()]              [_load_registry()]
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
| `MappingSpec` | `MappingBlock` | `MappingRule`, `MetaRule` | mapping | `specs.py` line 103 |
| `NormalizeSpec` | `NormalizeBlock` | `NormalizeRule` | normalize | `specs.py` line 210 |
| `EnrichSpec` | `EnrichBlock` | `EnrichRule` | enrich | `specs.py` line 285 |
| `ValidationSpec` | `ValidationBlock` | `FieldCheck`, `ConditionalCheck` | validate | `specs.py` line 307 |
| `MatchSpec` | `MatchBlock` | `MatchRule` | match | `specs.py` line 409 |
| `ResolveSpec` | `ResolveBlock` | `ResolveLinkSpec`, `ResolveDiffSpec` и др. | resolve | `specs.py` line 582 |
| `SourceSpec` | `SourceConfig` | `SourceFieldSpec` | extract | `specs.py` line 141 |
| `SinkSpec` | `SinkBlock` | `SinkFieldSpec` | sink (target) | `specs.py` line 176 |

### Cache спецификации

| Spec | Назначение | Расположение |
|------|-----------|-------------|
| `CacheRegistrySpec` | Реестр cache-датасетов и политик | `specs.py` line 665 |
| `CacheDatasetSpec` | Спецификация одного cache-датасета | `specs.py` line 854 |
| `CacheSyncSpec` | Контракт sync target→cache | `specs.py` line 808 |
| `CachePolicySpec` | Глобальные cache политики | `specs.py` line 639 |

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
| `load_mapping_spec_for_dataset()` | `MappingSpec` | `loader.py` line 49 |
| `load_source_spec_for_dataset()` | `SourceSpec` | `loader.py` line 62 |
| `load_normalize_spec_for_dataset()` | `NormalizeSpec` | `loader.py` line 100 |
| `load_enrich_spec_for_dataset()` | `EnrichSpec` | `loader.py` line 113 |
| `load_validate_spec_for_dataset()` | `ValidationSpec` | `loader.py` line 127 |
| `load_match_spec_for_dataset()` | `MatchSpec` | `loader.py` line 140 |
| `load_resolve_spec_for_dataset()` | `ResolveSpec` | `loader.py` line 153 |
| `load_sink_spec_for_dataset()` | `SinkSpec` | `loader.py` line 166 |
| `load_cache_registry_spec()` | `CacheRegistrySpec` | `loader.py` line 179 |
| `load_cache_dataset_spec_for_dataset()` | `CacheDatasetSpec` | `loader.py` line 235 |

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

**Назначение**: Самая сложная rule-модель (16 полей). Описывает generate/lookup правило обогащения.

**Структура**:
```python
class EnrichRule(BaseModel):
    name: str                                              # Уникальное имя правила
    target: str                                            # Целевое поле
    provider: ProviderRef | None = None                    # Ссылка на runtime provider
    value_path: str | None = None                          # JSON path в ответе provider
    source: str | None = None                              # Одно входное поле
    sources: list[str] | None = None                       # Несколько входных полей
    ops: list[OperationCall] = []                          # Цепочка операций
    on_error: "error" | "warn" = "error"                   # Severity при ошибке
    merge: "recompute_always" | "fill_only_if_empty" | ... | None  # Политика merge
    exists: ExistsRef | None = None                        # Exists-проверка через provider
    allow_if: OperationCall | str | None = None            # Guard-условие (str → OperationCall)
    max_attempts: int | None = None                        # Макс. попыток provider call
    run_when_errors: "never" | "if_any" | "always" | None  # Запуск при ошибках
    missing_error_code: str | None = None                  # Код ошибки при missing
    conflict_error_code: str | None = None                 # Код ошибки при conflict
    error_field: str | None = None                         # Поле для привязки ошибки
```

**Валидация** (`@model_validator` line 271):
- `allow_if` строка → авто-раскрытие в `OperationCall(op=allow_if, args={})`

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
1. **Создание**: `build_options_from_mapping(cls, merged_dict)` — безопасное создание из словаря
2. **Хранение**: Передаётся в `LayerDsl.__init__(options=...)` каждого layer compiler
3. **Потребление**: Layer compiler проверяет флаги во время компиляции

**Инварианты**:
- `frozen=True` — опции не изменяются после создания
- `build_options_from_mapping()` игнорирует неизвестные ключи (`allowed = {f.name for f in fields(cls)}`)
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

**Назначение**: Центральный файл, связывающий датасеты с YAML-файлами стадий

```yaml
# datasets/registry.yml

datasets:
  employees:
    dataset: employees
    source: employees/employees.source.yaml       # → SourceSpec
    mapping: employees/employees.mapping.yaml      # → MappingSpec
    normalize: employees/employees.normalize.yaml  # → NormalizeSpec
    enrich: employees/employees.enrich.yaml        # → EnrichSpec
    validate: employees/employees.validate.yaml    # → ValidationSpec
    match: employees/employees.match.yaml          # → MatchSpec
    resolve: employees/employees.resolve.yaml      # → ResolveSpec
    sink: employees/employees.sink.yaml            # → SinkSpec
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
_load_registry()  →  registry.yml
    ↓
_resolve_registry_path()  →  "datasets/employees/employees.mapping.yaml"
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

**Расположение**: `connector/domain/dsl/loader.py` line 455

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
   → Читает datasets/registry.yml
   → Если файл не найден или невалиден → DslLoadError("DSL_REGISTRY_INVALID")

2. Resolve path (line 464)
   stage_path = _resolve_registry_path(registry, dataset, stage)
   → datasets[dataset][stage] → "employees/employees.mapping.yaml"
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

**Расположение**: `connector/domain/dsl/loader.py` line 416

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
   RETURN build_options_from_mapping(options_cls, merged)
   → Фильтрует неизвестные ключи
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

**Расположение**: `connector/domain/dsl/loader.py` line 282

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
   FOR EACH dataset (sorted):
       merged.update(dataset_overrides[dataset])

3. Apply CLI overrides (lines 317-318)
   IF cli_overrides:
       merged.update(cli_overrides)

4. Build (line 319)
   RETURN build_options_from_mapping(CacheDslBuildOptions, merged)
```

**Визуализация 5 уровней**:

```
Priority (low → high):

1. Defaults  →  2. global.base  →  3. global.stages.cache
      →  4. dataset overrides  →  5. CLI overrides
```

---

### Метод: `_expand_enrich_templates()`

**Расположение**: `connector/domain/dsl/loader.py` line 331

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

1. **Создать Rule/Block/Spec модели** в `connector/domain/dsl/specs.py`:
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

3. **Добавить loader-функции** в `connector/domain/dsl/loader.py`:
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

1. Добавить поле в соответствующий `*Rule` / `*Block` / `*Spec` класс в `specs.py`
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
# build_options_from_mapping(cls, data) гарантирует:
# 1. Возвращает экземпляр cls (никогда не бросает ошибку)
# 2. Неизвестные ключи игнорируются (forward-compatibility)
# 3. Пропущенные ключи заполняются defaults из dataclass
# 4. data=None → cls() с defaults
```

### Коды ошибок загрузки

| Код | Условие | Расположение |
|-----|---------|-------------|
| `DSL_REGISTRY_INVALID` | registry.yml не найден, невалиден или dataset/stage отсутствует | `loader.py` lines 378, 448 |
| `MAP_DSL_SPEC_INVALID` | MappingSpec невалиден | `loader.py` line 58 |
| `SOURCE_DSL_SPEC_INVALID` | SourceSpec невалиден | `loader.py` line 71 |
| `SOURCE_DSL_LOCATION_INVALID` | location и location_ref пусты | `loader.py` line 93 |
| `NORMALIZE_DSL_SPEC_INVALID` | NormalizeSpec невалиден | `loader.py` line 109 |
| `ENRICH_DSL_SPEC_INVALID` | EnrichSpec невалиден | `loader.py` line 122 |
| `ENRICH_DSL_TEMPLATE_INVALID` | Неизвестный lookup template | `loader.py` line 352 |
| `VALIDATE_DSL_SPEC_INVALID` | ValidationSpec невалиден | `loader.py` line 136 |
| `MATCH_DSL_SPEC_INVALID` | MatchSpec невалиден | `loader.py` line 149 |
| `RESOLVE_DSL_SPEC_INVALID` | ResolveSpec невалиден | `loader.py` line 162 |
| `SINK_DSL_SPEC_INVALID` | SinkSpec невалиден | `loader.py` line 175 |
| `CACHE_DSL_REGISTRY_INVALID` | Cache registry невалиден | `loader.py` line 188, 410 |
| `CACHE_DSL_SPEC_INVALID` | CacheDatasetSpec невалиден | `loader.py` line 228, 252 |
| `CACHE_DSL_DEP_MISSING` | Dataset отсутствует в cache registry | `loader.py` line 243 |

### Границы слоёв

**Разрешенные зависимости**:
- ✅ `loader.py` → `specs.py` (import Spec classes)
- ✅ `loader.py` → `build_options.py` (import BuildOptions classes)
- ✅ `loader.py` → `issues.py` (import DslLoadError)
- ✅ `loader.py` → `yaml` (stdlib YAML parsing)

**Запрещенные зависимости**:
- ❌ `specs.py` → что-либо кроме `pydantic` — specs чистые data models
- ❌ `loader.py` → `engine.py` — загрузчик не выполняет операции
- ❌ `loader.py` → `connector/infra/*` — загрузчик не обращается к инфраструктуре
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
1. Читает `datasets/registry.yml`
2. Находит `datasets.employees.mapping` → `"employees/employees.mapping.yaml"`
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
- **`_repo_root()`**: Вычисляет корень проекта через `Path(__file__).resolve().parents[3]` (`<repo>/connector/domain/dsl/loader.py`). Привязан к расположению `loader.py`
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

2. **Инвариант: specs.py не имеет внешних зависимостей**
   - **Что**: `specs.py` импортирует только `pydantic` — ни один домен/инфра модуль
   - **Почему важно**: Specs — чистые data models, переиспользуемые везде без circular imports
   - **Где проверяется**: Архитектурные тесты (`tests/architecture/`)

3. **Инвариант: Build options forward-compatible**
   - **Что**: `build_options_from_mapping()` игнорирует неизвестные ключи
   - **Почему важно**: Добавление нового флага не ломает существующие конфигурации
   - **Где проверяется**: `build_options.py` line 110: `key in allowed`

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

- [DSL Engine](./dsl-engine.md) — Движок операций, реестр, 25 core operations
- [DSL Diagnostics](./dsl-diagnostics.md) — Модель ошибок, диагностика, карта интеграции
- [Cache DSL](../cache/cache-dsl.md) — Как cache слой использует specs и loader
- [Resolve DSL](../resolver/resolve-dsl.md) — Как resolve слой использует specs и loader

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-12 | Создан документ | dev |
