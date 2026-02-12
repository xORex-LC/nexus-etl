# DSL Diagnostics

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [📐 UML диаграммы](#-uml-диаграммы)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма зависимостей](#диаграмма-зависимостей)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
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

**Назначение**: DSL error model, diagnostic bridge, public API и карта интеграционных границ между DSL-core и layer-specific DSL compilers

**Ключевая ответственность**:
- Определение DSL-локальных типов ошибок (`DslSeverity`, `DslLoadError`, `DslIssue`)
- Перевод DSL-ошибок в доменную диагностическую модель (`DiagnosticItem`)
- Экспорт public API через `__init__.py` (46 символов)
- Документирование интеграционных границ DSL Core → Layer Compilers

**Расположение в кодовой базе**:
- `connector/domain/dsl/issues.py` — DSL error types
- `connector/domain/dsl/diagnostics.py` — Bridge functions
- `connector/domain/dsl/__init__.py` — Public API facade

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
dsl/
├── issues.py       # 64 строки: DslSeverity, DslLoadError, DslIssue
├── diagnostics.py  # 107 строк: Bridge DslIssue/DslLoadError → DiagnosticItem
└── __init__.py     # 101 строка: Public API (46 exports)
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [DSL Error Model](../../../uml/dsl/dsl_diagnostics_class.png) | Иерархия DslIssue → DiagnosticItem |
| Sequence | [Error Flow](../../../uml/dsl/dsl_diagnostics_sequence.png) | Поток ошибок от engine к отчёту |

**PlantUML исходники**: `docs/uml/dsl/*.puml`

> **Примечание**: UML диаграммы находятся в процессе обновления.

### 🎭 Применённые паттерны

#### Паттерн 1: Two-Level Error Model

**Где применяется**: Два типа ошибок для разных фаз DSL pipeline

**Реализация в коде**:
- **Runtime-level**: `DslIssue` — ошибки применения операций (field-level, в EngineResult)
- **Spec-level**: `DslLoadError` — ошибки загрузки/валидации/компиляции (structural, exception)

**Пример**:
```python
# DslIssue — runtime, per-field
DslIssue(
    code="DSL_OP_FAILED",
    message="Empty int value",
    field="employee_id",          # Привязка к полю
    severity=DslSeverity.ERROR,
)

# DslLoadError — spec-level, structural
raise DslLoadError(
    code="MAP_DSL_SPEC_INVALID",
    message="Invalid DSL spec: ...",
    details={"dataset": "employees", "stage": "mapping"},
)
```

**Зачем**: Разделение runtime-ошибок (recoverable, per-record) и structural-ошибок (fatal, per-spec). Runtime ошибки собираются в списки, structural — поднимают exception.

#### Паттерн 2: Adapter Pattern

**Где применяется**: `diagnostics.py` адаптирует DSL-локальные типы → доменные `DiagnosticItem`

**Реализация в коде**:
- **Adapter**: `append_dsl_issue()` в `diagnostics.py` line 17
- **Source**: `DslIssue` (из `issues.py`)
- **Target**: `DiagnosticItem` (из `connector.domain.models`)

**Пример**:
```python
# DSL-ошибка
issue = DslIssue(code="DSL_OP_FAILED", message="...", severity=DslSeverity.ERROR)

# → DiagnosticItem через bridge
append_dsl_issue(
    errors=errors_list,
    warnings=warnings_list,
    stage=DiagnosticStage.MAPPING,
    issue=issue,
    catalog=catalog,
    record_ref=row_ref,
)
```

**Зачем**: DSL-core не зависит от доменной диагностики; перевод происходит на границе между DSL и domain

#### Паттерн 3: Facade Pattern

**Где применяется**: `__init__.py` курирует публичный API

**Реализация в коде**: 46 экспортов из 6 внутренних модулей (`engine`, `issues`, `loader`, `build_options`, `registry`, `specs`)

**Зачем**: Потребители импортируют `from connector.domain.dsl import ...` — один entry point вместо 6 модулей

### Диаграмма зависимостей

```
                  ┌─────────────────────────┐
                  │   connector.domain.dsl   │
                  │     (__init__.py)         │
                  │   Public API (46 exports) │
                  └───────┬─────────────────┘
                          │ re-exports
        ┌─────────────────┼─────────────────────┐
        ↓                 ↓                     ↓
  [engine.py]       [loader.py]          [build_options.py]
  [registry.py]     [specs.py]           [issues.py]
        │                                       │
        └─────────────┐  ┌─────────────────────┘
                      ↓  ↓
               [diagnostics.py]
                      │
                      ↓
        [connector.domain.models]     (DiagnosticItem, DiagnosticStage, RowRef)
        [connector.domain.diagnostics] (ErrorCatalog, build_error, error, warning)
```

**Ключевое наблюдение**: `diagnostics.py` — единственный файл в `dsl/`, который импортирует из `connector.domain.diagnostics` и `connector.domain.models`. Это **single bridge point** между DSL и доменной диагностикой.

---

## 🔑 Ключевые абстракции

### Error Types

| Тип | Роль | Когда используется | Расположение |
|-----|------|-------------------|-------------|
| `DslSeverity` | Enum: `ERROR` / `WARNING` | Маркировка severity в `DslIssue` | `issues.py` line 13 |
| `DslLoadError` | Exception (ValueError) | Ошибки загрузки/валидации/компиляции DSL | `issues.py` line 23 |
| `DslIssue` | Frozen dataclass | Ошибки runtime (применение операций) | `issues.py` line 45 |

### Bridge Functions

| Функция | Роль | Расположение |
|---------|------|-------------|
| `append_dsl_issue()` | Перевод одного `DslIssue` → `DiagnosticItem` | `diagnostics.py` line 17 |
| `append_dsl_issues()` | Batch-перевод `Iterable[DslIssue]` → `DiagnosticItem` | `diagnostics.py` line 61 |
| `translate_dsl_load_error()` | Перевод `DslLoadError` → `DiagnosticItem` | `diagnostics.py` line 87 |

---

## 🗂️ Модели данных

### Dataclass: `DslIssue`

**Назначение**: Диагностическая запись DSL-движка для runtime-ошибок (per-record, per-field)

**Структура**:
```python
@dataclass(frozen=True)
class DslIssue:
    code: str                              # Код ошибки (напр. "DSL_OP_FAILED")
    message: str                           # Текст ошибки
    field: str | None = None               # Целевое поле (если применимо)
    details: dict[str, Any] | None = None  # Дополнительный контекст
    severity: DslSeverity = DslSeverity.ERROR  # Severity по умолчанию ERROR
```

**Lifecycle**:
1. **Создание**: `TransformationEngine.apply()` (`engine.py` lines 63-81) — при неизвестной операции (`DSL_OP_UNKNOWN`) или exception (`DSL_OP_FAILED`)
2. **Хранение**: В `EngineResult.issues` (tuple)
3. **Распаковка**: `apply_ops()` (`helpers.py` line 25) → `(value, list[DslIssue])`
4. **Перевод**: `append_dsl_issue()` (`diagnostics.py` line 17) → `DiagnosticItem` в errors/warnings списке

**Инварианты**:
- `frozen=True` — не изменяется после создания
- `code` — непустая строка; по конвенции: `DSL_OP_*` для engine, `*_DSL_*` для layer compilers
- `severity` по умолчанию `ERROR`; может быть переопределён `on_error="warn"` в bridge

---

### Exception: `DslLoadError`

**Назначение**: Structural ошибка загрузки/валидации/компиляции DSL конфигурации

**Структура**:
```python
class DslLoadError(ValueError):
    code: str                              # Доменный код ошибки (напр. "MAP_DSL_SPEC_INVALID")
    details: dict[str, Any]                # Контекст (dataset, stage, path)
```

**Lifecycle**:
1. **Создание**: `loader.py` при ошибке YAML/Pydantic, или layer-specific `*_dsl.py` при ошибке компиляции
2. **Проброс**: Через call stack до orchestration layer (usecase/command)
3. **Перевод**: `translate_dsl_load_error()` (`diagnostics.py` line 87) → `DiagnosticItem`
4. **Отчёт**: `DiagnosticItem` включается в `CommandResult` для пользователя

**Инварианты**:
- Всегда содержит `code` (для маппинга в ErrorCatalog)
- `details` содержит контекст для отладки (dataset, stage, path)
- Наследует от `ValueError` — совместим с существующим error handling

---

## 📊 Ключевые методы и алгоритмы

### Обзор методов

| Метод | Строк | Назначение |
|-------|-------|------------|
| `append_dsl_issue()` | 32 | Перевод DslIssue → DiagnosticItem с severity logic |
| `append_dsl_issues()` | 14 | Batch-перевод через цикл |
| `translate_dsl_load_error()` | 10 | Перевод DslLoadError → DiagnosticItem |

---

### Метод: `append_dsl_issue()`

**Расположение**: `connector/domain/dsl/diagnostics.py` line 17

**Сигнатура**:
```python
def append_dsl_issue(
    *, errors: list[DiagnosticItem], warnings: list[DiagnosticItem],
    stage: DiagnosticStage, issue: DslIssue, catalog: ErrorCatalog,
    record_ref: RowRef | None, on_error: str | None = None,
) -> None:
```

**Назначение**: Перевести одну `DslIssue` в `DiagnosticItem`, добавив в соответствующий список (errors или warnings).

---

**Алгоритм** (pseudocode с номерами строк):

```
1. Determine severity (lines 31-33)
   as_warning = (issue.severity == DslSeverity.WARNING)
   IF on_error == "warn":
       as_warning = True              ← override: ERROR → WARNING

2. Route to correct list (lines 34-58)
   IF as_warning:
       warnings.append(diag_warning(
           stage, code, field, message, details, record_ref, catalog
       ))
   ELSE:
       errors.append(diag_error(
           stage, code, field, message, details, record_ref, catalog
       ))
```

**Severity resolution**:

```
DslIssue.severity    on_error    →  Результат
───────────────────────────────────────────────
ERROR                None        →  errors (ERROR)
ERROR                "error"     →  errors (ERROR)
ERROR                "warn"      →  warnings (WARNING)   ← override!
WARNING              None        →  warnings (WARNING)
WARNING              "warn"      →  warnings (WARNING)
```

**Связь с YAML**: Параметр `on_error` приходит из `MappingRule.on_error`, `NormalizeRule.on_error`, `EnrichRule.on_error` и др. — конфигурируется пользователем в YAML.

---

### Метод: `translate_dsl_load_error()`

**Расположение**: `connector/domain/dsl/diagnostics.py` line 87

**Сигнатура**:
```python
def translate_dsl_load_error(
    *, catalog: ErrorCatalog, stage: DiagnosticStage,
    error: DslLoadError, record_ref: RowRef | None = None,
) -> DiagnosticItem:
```

**Назначение**: Перевести structural `DslLoadError` в `DiagnosticItem` через `build_error()`.

**Алгоритм**: Прямая делегация в `build_error()` (`connector.domain.diagnostics.catalog`):

```
RETURN build_error(
    catalog=catalog,
    stage=stage,
    code=error.code,          # Код ошибки из DslLoadError
    field=None,               # Structural ошибка — не привязана к полю
    message=str(error),       # Текст ошибки
    record_ref=record_ref,
    details=error.details,    # Контекст (dataset, stage, path)
)
```

---

## 🛠️ Как расширять

### Добавить новый error code

**Конвенция именования кодов**:

| Паттерн | Где используется | Пример |
|---------|-----------------|--------|
| `DSL_OP_*` | Engine runtime | `DSL_OP_UNKNOWN`, `DSL_OP_FAILED` |
| `DSL_REGISTRY_*` | Loader (registry.yml) | `DSL_REGISTRY_INVALID` |
| `{STAGE}_DSL_SPEC_INVALID` | Loader (stage spec) | `MAP_DSL_SPEC_INVALID`, `RESOLVE_DSL_SPEC_INVALID` |
| `{STAGE}_DSL_*` | Layer-specific compiler | `ENRICH_DSL_TEMPLATE_INVALID` |
| `CACHE_DSL_*` | Cache DSL compiler | `CACHE_DSL_REGISTRY_INVALID`, `CACHE_DSL_DEP_MISSING` |

**Шаги**:
1. Выбрать код по конвенции выше
2. Использовать в `DslLoadError(code="MY_CODE", ...)` или `DslIssue(code="MY_CODE", ...)`
3. (Опционально) Зарегистрировать в `ErrorCatalog` для человекочитаемого сообщения

### Интегрировать DSL-ошибки в новом layer

```python
from connector.domain.dsl.diagnostics import append_dsl_issues, translate_dsl_load_error
from connector.domain.dsl.issues import DslLoadError

# В layer engine:
try:
    rules = my_dsl.compile(spec)
except DslLoadError as exc:
    diagnostic = translate_dsl_load_error(
        catalog=self.catalog,
        stage=DiagnosticStage.MY_STAGE,
        error=exc,
    )
    return CommandResult(errors=[diagnostic])

# При runtime-ошибках операций:
result = engine.apply(value, ops)
if result.issues:
    append_dsl_issues(
        errors=errors,
        warnings=warnings,
        issues=result.issues,
        stage=DiagnosticStage.MY_STAGE,
        catalog=catalog,
        record_ref=row_ref,
        on_error=rule.on_error,     # ← из YAML конфигурации
    )
```

---

## 🔄 Взаимодействие с другими слоями

### Карта интеграции: DSL Core → Layer Compilers

Это ключевая секция, описывающая **границы и стыки**, где логика переходит от DSL-core к специфичным для слоёв DSL-механизмам.

```
┌──────────────────────────────────────────────────────────────┐
│                        DSL Core                               │
│                                                               │
│  specs.py     → Pydantic-модели для всех стадий              │
│  loader.py    → YAML загрузка + merge-priority build options  │
│  engine.py    → TransformationEngine (apply ops to values)    │
│  registry.py  → OperationRegistry (25 core ops)               │
│  build_options.py → BaseDslBuildOptions + 6 subclasses        │
│  issues.py    → DslIssue, DslLoadError                        │
│  diagnostics.py → DslIssue → DiagnosticItem bridge            │
└─────────────────────────┬────────────────────────────────────┘
                          │ предоставляет
                          ↓
┌──────────────────────────────────────────────────────────────┐
│              Layer-Specific DSL Compilers                      │
│                                                               │
│  MapperDsl.compile(MappingSpec)       → MapperCore            │
│  NormalizerDsl.compile(NormalizeSpec) → NormalizerCore         │
│  EnricherDsl.compile(EnrichSpec)      → EnricherSpec          │
│  MatchDsl.compile(MatchSpec)          → MatchingRules          │
│  ResolveDsl.compile(ResolveSpec)      → CompiledResolveRules   │
│  CacheDsl.compile_runtime(...)        → CacheDslRuntime        │
└─────────────────────────┬────────────────────────────────────┘
                          │ производит
                          ↓
┌──────────────────────────────────────────────────────────────┐
│                  Compiled Runtime Rules                        │
│                                                               │
│  Stage Engines используют rules для runtime обработки         │
│  (MapperEngine, NormalizerEngine, EnricherEngine,             │
│   MatchEngine, ResolveEngine)                                 │
└──────────────────────────────────────────────────────────────┘
```

### Таблица Layer Compilers

| Compiler | Расположение | Потребляет из DSL Core | Производит |
|----------|-------------|----------------------|------------|
| `MapperDsl` | `connector/domain/transform/mapping/mapper_dsl.py` | `MappingSpec`, `TransformationEngine`, `OperationRegistry`, `MapDslBuildOptions`, `DslLoadError` | `MapperCore` |
| `NormalizerDsl` | `connector/domain/transform/normalize/normalizer_dsl.py` | `NormalizeSpec`, `TransformationEngine`, `OperationRegistry`, `NormalizeDslBuildOptions`, `DslLoadError` | `NormalizerCore` |
| `EnricherDsl` | `connector/domain/transform/enrich/enricher_dsl.py` | `EnrichSpec`, `TransformationEngine`, `OperationRegistry`, `EnrichDslBuildOptions`, `DslLoadError`, `apply_ops()` | `EnricherSpec` |
| `MatchDsl` | `connector/domain/transform/matcher/match_dsl.py` | `MatchSpec`, `MatchDslBuildOptions`, `DslLoadError` | `MatchingRules` |
| `ResolveDsl` | `connector/domain/transform/resolver/resolve_dsl.py` | `ResolveSpec`, `SinkSpec`, `ResolveDslBuildOptions`, `DslLoadError` | `CompiledResolveRules` |
| `CacheDsl` | `connector/domain/cache_core/cache_dsl.py` | `CacheRegistrySpec`, `CacheDatasetSpec`, `CacheDslBuildOptions`, `DslLoadError` | `CacheDslRuntime` |

### Uniform Compiler Pattern

Все layer compilers следуют единообразной структуре:

```python
class LayerDsl:
    def __init__(
        self,
        registry: OperationRegistry | None = None,  # Для Map/Normalize/Enrich
        engine: TransformationEngine | None = None,  # Для Map/Normalize/Enrich
        options: LayerDslBuildOptions | None = None,  # Всегда
    ):
        self.options = options or LayerDslBuildOptions()
        # Engine создаётся по умолчанию если не передан
        if engine is None and registry is not None:
            engine = TransformationEngine(registry)

    def compile(self, spec: LayerSpec, ...) -> CompiledRules:
        try:
            # 1. Валидация spec по build options
            # 2. Компиляция rules/policies
            # 3. Возврат compiled bundle
            return CompiledRules(...)
        except DslLoadError:
            raise  # Пробрасывает как есть
        except Exception as exc:
            raise DslLoadError(
                code="LAYER_DSL_COMPILE_INVALID", ...
            ) from exc
```

**Что общее**:
- Все принимают `options` через конструктор
- Все поднимают `DslLoadError` при ошибках компиляции
- Все возвращают immutable compiled bundle

**Что различается**:
- Map/Normalize/Enrich используют `TransformationEngine` (операции)
- Match/Resolve **не** используют engine (компилируют rules, а не ops)
- Cache компилирует целый runtime bundle с hashes и dependency graph

### DatasetSpec Protocol — точка оркестрации

`DatasetSpec` protocol (`connector/datasets/spec.py`) связывает DSL Core с layer compilers:

```python
class DatasetSpec(Protocol):
    def build_map_spec(self) -> MappingSpec:        # → loader
        ...
    def build_map_stage(self, ...) -> MapStage:     # → loader + compiler
        ...
```

**Реализация** (`connector/datasets/employees/spec.py`):

```python
class EmployeesSpec:
    def build_map_stage(self, *, catalog: ErrorCatalog) -> MapStage:
        # 1. Загрузить spec через DSL Core loader
        spec = load_mapping_spec_for_dataset(self.dataset_name)
        options = load_map_build_options_for_dataset(self.dataset_name)
        # 2. Создать layer compiler с DSL Core engine
        mapper = MapperEngine(spec, catalog=catalog, options=options)
        # 3. Вернуть stage
        return MapStage(mapper, catalog)
```

### Полный pipeline: YAML → Load → Compile → Execute

```
YAML файлы (datasets/registry.yml + datasets/*.yaml)
         ↓
   ┌─────────────────────────────────────────────┐
   │ DSL Core: loader.py                          │
   │ load_*_spec_for_dataset() → Typed Spec       │
   │ load_*_build_options_for_dataset() → Options  │
   └──────────────────┬──────────────────────────┘
                      ↓
   ┌─────────────────────────────────────────────┐
   │ Layer Compiler: *_dsl.py                     │
   │ LayerDsl(engine, options).compile(spec)      │
   │ → Compiled Rules / Runtime Bundle            │
   └──────────────────┬──────────────────────────┘
                      ↓
   ┌─────────────────────────────────────────────┐
   │ Stage Engine: *_engine.py                    │
   │ Engine wraps compiler + core                 │
   │ .process(TransformResult) → TransformResult  │
   └──────────────────┬──────────────────────────┘
                      ↓
   ┌─────────────────────────────────────────────┐
   │ Stage Pipeline                               │
   │ Extract → Map → Normalize → Enrich →         │
   │ Validate → Match → Resolve → Plan → Apply    │
   └─────────────────────────────────────────────┘
```

---

## 🔌 Контракты и границы

### Public API (`__init__.py`)

Все 46 экспортов, сгруппированные по категориям:

**Engine & Runtime** (4):
```
TransformationEngine, EngineResult, OperationRegistry, register_core_ops
```

**Error Types** (3):
```
DslIssue, DslSeverity, DslLoadError
```

**Spec Loaders** (11):
```
load_mapping_spec, load_mapping_spec_for_dataset,
load_source_spec_for_dataset, load_normalize_spec_for_dataset,
load_enrich_spec_for_dataset, load_validate_spec_for_dataset,
load_match_spec_for_dataset, load_resolve_spec_for_dataset,
load_sink_spec_for_dataset, load_cache_registry_spec,
load_cache_registry_spec_for_runtime
```

**Cache Loaders** (2):
```
load_cache_dataset_spec, load_cache_dataset_spec_for_dataset
```

**Build Options Loaders** (6):
```
load_map_build_options_for_dataset, load_normalize_build_options_for_dataset,
load_enrich_build_options_for_dataset, load_match_build_options_for_dataset,
load_resolve_build_options_for_dataset, load_cache_build_options_for_runtime
```

**Build Options Classes** (7):
```
BaseDslBuildOptions, MapDslBuildOptions, NormalizeDslBuildOptions,
EnrichDslBuildOptions, MatchDslBuildOptions, ResolveDslBuildOptions,
CacheDslBuildOptions
```

**Spec Models** (13):
```
MappingSpec, MappingRule, OperationCall, ProviderRef, ExistsRef,
NormalizeSpec, EnrichSpec, ValidationSpec, MatchSpec, ResolveSpec,
CacheRegistrySpec, CacheDatasetSpec
```

> **Примечание**: `diagnostics.py` функции (`append_dsl_issue`, `translate_dsl_load_error`) **не экспортируются** через `__init__.py`. Они импортируются напрямую: `from connector.domain.dsl.diagnostics import ...`

### Таксономия error codes

| Префикс | Источник | Фаза |
|---------|---------|------|
| `DSL_OP_*` | `engine.py` | Runtime (apply) |
| `DSL_REGISTRY_*` | `loader.py` | Load (registry.yml) |
| `MAP_DSL_*` | `loader.py` + `mapper_dsl.py` | Load/Compile (mapping) |
| `NORMALIZE_DSL_*` | `loader.py` + `normalizer_dsl.py` | Load/Compile (normalize) |
| `ENRICH_DSL_*` | `loader.py` + `enricher_dsl.py` | Load/Compile (enrich) |
| `VALIDATE_DSL_*` | `loader.py` | Load (validate) |
| `MATCH_DSL_*` | `loader.py` + `match_dsl.py` | Load/Compile (match) |
| `RESOLVE_DSL_*` | `loader.py` + `resolve_dsl.py` | Load/Compile (resolve) |
| `SINK_DSL_*` | `loader.py` | Load (sink) |
| `SOURCE_DSL_*` | `loader.py` | Load (source) |
| `CACHE_DSL_*` | `loader.py` + `cache_dsl.py` | Load/Compile (cache) |

### Границы слоёв

**Разрешенные зависимости**:
- ✅ `diagnostics.py` → `connector.domain.models` (DiagnosticItem, DiagnosticStage, RowRef)
- ✅ `diagnostics.py` → `connector.domain.diagnostics` (ErrorCatalog, build_error, error, warning)
- ✅ `diagnostics.py` → `issues.py` (DslIssue, DslLoadError, DslSeverity)
- ✅ `__init__.py` → все внутренние модули `dsl/` (re-export)

**Запрещенные зависимости**:
- ❌ `issues.py` → `connector.domain.*` — issues не зависит от доменной диагностики
- ❌ `issues.py` → `diagnostics.py` — обратная зависимость запрещена
- ❌ `diagnostics.py` → `connector/infra/*` — bridge чисто доменный

**Ключевое наблюдение**: `diagnostics.py` — **единственный** файл в `dsl/`, который импортирует из `connector.domain.diagnostics` и `connector.domain.models`. Все остальные файлы DSL Core полностью автономны.

---

## 💡 Типичные сценарии

### Сценарий 1: Обработка DslLoadError при загрузке spec

**Задача**: Загрузить spec и обработать ошибку загрузки

**Решение**:
```python
from connector.domain.dsl import load_mapping_spec_for_dataset
from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.diagnostics import translate_dsl_load_error

try:
    spec = load_mapping_spec_for_dataset("employees")
except DslLoadError as exc:
    # exc.code == "MAP_DSL_SPEC_INVALID"
    # exc.details == {"dataset": "employees", "stage": "mapping", "path": "..."}
    diagnostic = translate_dsl_load_error(
        catalog=catalog,
        stage=DiagnosticStage.MAPPING,
        error=exc,
    )
    return CommandResult(errors=[diagnostic])
```

### Сценарий 2: Сбор runtime DslIssue при применении операций

**Задача**: Применить операции к записи и собрать диагностику

**Решение**:
```python
from connector.domain.dsl.engine import TransformationEngine
from connector.domain.dsl.diagnostics import append_dsl_issues

engine = TransformationEngine.with_core_ops()
result = engine.apply(record["email"], [
    OperationCall(op="trim"),
    OperationCall(op="lower"),
])

if result.issues:
    append_dsl_issues(
        errors=errors,
        warnings=warnings,
        issues=result.issues,
        stage=DiagnosticStage.MAPPING,
        catalog=catalog,
        record_ref=row_ref,
        on_error="warn",  # override: ошибки → предупреждения
    )
else:
    processed["email"] = result.value
```

### Сценарий 3: Полный pipeline загрузки в layer engine

**Задача**: Как layer engine использует DSL Core от начала до конца

**Решение** (на примере MapperEngine):
```python
class MapperEngine:
    def __init__(self, spec: MappingSpec, catalog: ErrorCatalog, ...):
        # 1. DSL Core: создать engine с базовыми операциями
        registry = OperationRegistry()
        register_core_ops(registry)
        engine = TransformationEngine(registry)

        # 2. Layer Compiler: скомпилировать spec в core
        dsl = MapperDsl(registry=registry, engine=engine, options=options)
        self.core = dsl.compile(spec, sink_spec=sink_spec)
        #   ↑ DslLoadError если spec невалиден

    def map(self, record: SourceRecord) -> TransformResult:
        # 3. Runtime: применить операции через engine
        result = self.core.apply(record)
        #   ↑ DslIssue собирается внутри core → TransformResult.errors/warnings
        return result
```

---

## 📌 Важные детали

### Особенности реализации

- **`diagnostics.py` не в `__init__.py`**: Bridge-функции не экспортируются через public API, т.к. используются только layer-specific кодом, а не внешними потребителями
- **`on_error` override**: Позволяет пользователю в YAML понижать severity с ERROR до WARNING. Это design decision: конфигурация важнее default severity

### 🚨 Failure Modes

| Исключение | Условие возникновения | Поведение системы | Как обработать |
|------------|----------------------|-------------------|---------------|
| `DslLoadError` | YAML/Pydantic ошибка при загрузке spec | Exception propagation | `translate_dsl_load_error()` → DiagnosticItem |
| `DslIssue(DSL_OP_UNKNOWN)` | Неизвестное имя операции в engine.apply() | Fail-fast, value = промежуточный | Проверить имя op в YAML |
| `DslIssue(DSL_OP_FAILED)` | Операция подняла exception | Fail-fast, value = промежуточный | Проверить входные данные и args |
| `KeyError` в `registry.require()` | Прямой lookup несуществующей операции | Поднимает KeyError | Использовать `registry.get()` |

### ⚠️ Инварианты системы

1. **Инвариант: DslLoadError всегда содержит `code`**
   - **Что**: Каждый `DslLoadError` имеет доменный error code
   - **Почему важно**: Error code используется для маппинга в `ErrorCatalog` и автоматической генерации human-readable сообщений
   - **Где проверяется**: Конструктор `DslLoadError.__init__()` — `code` обязательный keyword-аргумент

2. **Инвариант: DslIssue immutable**
   - **Что**: `@dataclass(frozen=True)` — DslIssue не изменяется
   - **Почему важно**: Безопасная передача между layers, возможность хранения в tuple
   - **Где проверяется**: `issues.py` line 45

3. **Инвариант: diagnostics.py — единственный bridge point**
   - **Что**: Только `diagnostics.py` импортирует из `connector.domain.diagnostics`
   - **Почему важно**: Изоляция DSL-core от доменной диагностики; при изменении DiagnosticItem меняется только один файл
   - **Где проверяется**: Можно добавить архитектурный тест

4. **Инвариант: on_error сохраняет семантику**
   - **Что**: `on_error="warn"` понижает severity, но `on_error="error"` не повышает WARNING
   - **Почему важно**: Пользователь может смягчить ошибки, но не может усилить предупреждения
   - **Где проверяется**: `diagnostics.py` lines 31-33 — `as_warning` logik

### ⏱️ Performance заметки

**Стоимость bridge-операций**:

| Операция | Сложность | Примечание |
|----------|-----------|------------|
| `append_dsl_issue()` | O(1) | Один вызов `diag_error()`/`diag_warning()` |
| `append_dsl_issues()` | O(n) | n = количество issues (обычно 0-1) |
| `translate_dsl_load_error()` | O(1) | Один вызов `build_error()` |

**Важно**: Bridge-операции тривиальны по стоимости. Основная стоимость — в `engine.apply()` и `model_validate()`.

### Частые ошибки

- ❌ **Ловить `DslLoadError` и терять `code`**: `except Exception as exc: raise RuntimeError(str(exc))` — теряет error code
- ✅ **Делай так**: `except DslLoadError: raise` или `translate_dsl_load_error(error=exc)`

- ❌ **Импортировать `diagnostics.py` из `specs.py` или `engine.py`**: Нарушает направление зависимостей
- ✅ **Делай так**: Импортировать `diagnostics.py` только из layer-specific кода

---

## 🔗 Связанные документы

- [DSL Engine](./dsl-engine.md) — Движок операций, реестр, DslIssue production
- [DSL Specs](./dsl-specs.md) — Pydantic-модели, YAML-загрузка, DslLoadError production
- [Cache DSL](../cache/cache-dsl.md) — Cache layer compiler, использует DslLoadError
- [Resolve DSL](../resolver/resolve-dsl.md) — Resolve layer compiler, использует DslLoadError
- [Cache Core](../cache/cache-core.md) — Логика cache, потребляет CacheDslRuntime
- [Resolve Core](../resolver/resolve-core.md) — Алгоритмы resolve, потребляет CompiledResolveRules

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-12 | Создан документ | dev |
