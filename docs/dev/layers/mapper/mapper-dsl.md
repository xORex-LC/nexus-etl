# Mapper DSL — спецификации источника, правил маппинга и выходной схемы

> **Mapper DSL** — декларативный слой, определяющий откуда читать данные (`SourceSpec`),
> как трансформировать поля (`MappingSpec`), и какой формат ожидать на выходе (`SinkSpec`).
> Все три спецификации хранятся в YAML и компилируются в `CompiledMapRules` при инициализации.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [🛠️ HOW-TO](#️-how-to)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
- [🧪 Тестовое покрытие](#-тестовое-покрытие)
- [❓ FAQ](#-faq)
- [🔗 Связанные документы](#-связанные-документы)
- [📝 История изменений](#-история-изменений)

---

## 📋 Обзор

Mapper DSL строится на трёх взаимосвязанных YAML-спецификациях:

| Спецификация | Файл (пример) | Вопрос |
|---|---|---|
| `SourceSpec` | `employees.source.yaml` | Откуда читать данные? |
| `MappingSpec` | `employees.mapping.yaml` | Как трансформировать поля? |
| `SinkSpec` | `employees.sink.yaml` | Какая схема на выходе? |

Рабочий цикл DSL-слоя:

```
registry.yml  →  load_*_spec_for_dataset()  →  SourceSpec / MappingSpec / SinkSpec
                                                         ↓
                                             MapperDsl.compile(spec, sink_spec)
                                                         ↓
                                             CompiledMapRules (frozen dataclass)
                                                         ↓
                                             MapperCore.map_record() — применяет правила
```

DSL-слой **не знает** о конкретных реализациях источников (CSV, DB) — это область
`connector/infra/sources/`. DSL знает только о декларативной конфигурации.

**Файловая структура:**

```
connector/domain/transform_dsl/
├── specs/
│   ├── source.py          # SourceSpec, SourceConfig, SourceFieldSpec
│   ├── mapping.py         # MappingSpec, MappingRule, MetaRule, MappingSchema, MappingBlock
│   └── sink.py            # SinkSpec, SinkBlock, SinkFieldSpec
├── compilers/
│   └── mapping.py         # MapperDsl, CompiledMapRules
├── build_options.py       # MapDslBuildOptions (и опции остальных стадий)
└── loader.py              # load_mapping_spec_for_dataset, load_source_spec_for_dataset, ...

datasets/
├── employees.source.yaml  # Конфигурация CSV-источника
├── employees.mapping.yaml # Правила маппинга полей
└── employees.sink.yaml    # Выходная схема (ожидаемые поля)
```

---

## 🏗️ Архитектура слоя

### Поток загрузки спецификаций

```
datasets/registry.yml
  └── datasets:
        employees:
          source:  employees.source.yaml   ←─ load_source_spec_for_dataset("employees")
          mapping: employees.mapping.yaml  ←─ load_mapping_spec_for_dataset("employees")
          sink:    employees.sink.yaml     ←─ load_sink_spec_for_dataset("employees")
          build_options:
            mapping:
              fail_on_unknown_ops: true    ←─ load_map_build_options_for_dataset("employees")
```

### Поток компиляции

```
MappingSpec  ──┐
SinkSpec     ──┤──► MapperDsl.compile()  ──► CompiledMapRules
MapDslBuildOptions ─┘
```

`MapperDsl.compile()` выполняет две проверки при создании:
1. **Все targets существуют в SinkSpec** (если `require_targets_exist_in_sink_spec=true`)
2. **Все ops известны в TransformationEngine** (если `fail_on_unknown_ops=true`)

### Три спецификации: роли

| Спецификация | Кто использует | Назначение |
|---|---|---|
| `SourceSpec` | `CsvRecordSource` (infra) | Путь к файлу, формат, кодировка, поля источника |
| `MappingSpec` | `MapperCore` | Правила трансформации source → row |
| `SinkSpec` | `MapperDsl` (compile), `MapperCore` (validate) | Валидация что результат соответствует схеме |

---

## 🔑 Ключевые абстракции

### SourceSpec — декларация источника

**Файл:** `connector/domain/transform_dsl/specs/source.py`

```python
class SourceConfig(DslBaseModel):
    type: Literal["file", "db", "api"]   # "db" и "api" — объявлены, не реализованы
    format: str | None = None            # "csv"
    location: str | None = None          # Прямой путь к файлу
    location_ref: str | None = None      # Имя env-переменной (приоритет над location)
    options: dict[str, Any] = {}         # delimiter, encoding, has_header_default
    fields: list[SourceFieldSpec] = []   # Описание полей входного источника

class SourceSpec(DslBaseModel):
    dataset: str
    source: SourceConfig

class SourceFieldSpec(DslBaseModel):
    name: str
    type: Literal["string", "int", "float", "bool", "object", "list"] | None = None
    required: bool = False
    nullable: bool = True
    aliases: list[str] = []
```

**Разрешение пути источника** (`resolve_source_location(spec)` в `loader.py`):

```
1. Если задан location_ref → os.getenv(location_ref)
   → если значение непустое → использовать как путь
2. Иначе → spec.source.location
   → если непустое → использовать как путь
3. Ни то, ни другое → DslLoadError("source location is not configured")
```

`location_ref` позволяет хранить путь в env-переменной (`EMPLOYEES_SOURCE_PATH`)
вместо хардкода в YAML — необходимо для разных окружений (dev/prod).

### MappingSpec — правила трансформации

**Файл:** `connector/domain/transform_dsl/specs/mapping.py`

```python
class MappingSpec(DslBaseModel):
    dataset: str
    source_columns: list[str] = []   # Для позиционного fallback col_N → имя колонки
    mapping: MappingBlock

class MappingBlock(DslBaseModel):
    rules: list[MappingRule]
    schema_: MappingSchema | None = Field(default=None, alias="schema")
    meta: list[MetaRule] = []
```

### MappingRule — атомарное правило маппинга

**Ключевая абстракция DSL.** Каждое правило описывает: откуда взять данные,
как их трансформировать и куда записать.

| Поле | Тип | Назначение |
|------|-----|------------|
| `target` | `str \| None` | Одно выходное поле |
| `targets` | `list[str] \| None` | Несколько выходных полей |
| `source` | `str \| None` | Одно входное поле из источника |
| `sources` | `list[str] \| None` | Несколько входных полей |
| `op` | `str \| None` | Единственная операция (sugar для `ops: [{op: ..., args: ...}]`) |
| `args` | `dict \| None` | Аргументы для `op` |
| `ops` | `list[OperationCall]` | Цепочка операций (применяются последовательно) |
| `required` | `bool` | `True` → ошибка если результат пуст/None |
| `on_error` | `"error" \| "warn"` | Поведение при ошибке операции (дефолт: `"error"`) |

**Инварианты (Pydantic model_validator):**
- `target` или `targets` — обязателен хотя бы один
- `op` + `args` → автоматически конвертируется в `ops=[OperationCall(op=op, args=args)]`
- `source` или `sources` обязательны, **кроме** случая когда есть `op: const`

### MetaRule — правило для result.meta

Та же структура что и `MappingRule`, но `target` — dotted path в результирующем `meta`:

```yaml
meta:
  - target: row.source_type   # → result.meta["row"]["source_type"]
    op: const
    args: { value: "csv" }
```

- Применяются **только при отсутствии errors** в основных правилах
- `on_error` по умолчанию `"warn"` (ошибка в meta не блокирует результат)
- Могут читать из уже заполненных `row.*` полей через `read_value()`

### MappingSchema — post-validation схема

```python
class MappingSchema(DslBaseModel):
    required: list[str] = []   # Поля обязательны в финальном row
    allow_extra: bool = True   # Разрешить дополнительные поля
```

Проверяется **после** применения всех `MappingRule`. Если поле из `required`
отсутствует или пустое — `REQUIRED_FIELD_MISSING` ошибка.

### SinkSpec — схема ожидаемого выхода

**Файл:** `connector/domain/transform_dsl/specs/sink.py`

```python
class SinkSpec(DslBaseModel):
    dataset: str
    sink: SinkBlock

class SinkBlock(DslBaseModel):
    fields: list[SinkFieldSpec]         # Бизнес-поля
    system_fields: list[SinkFieldSpec]  # Системные поля (generated, не из mapper)

class SinkFieldSpec(DslBaseModel):
    name: str
    type: Literal["string", "int", "float", "bool", "object", "list"] | None = None
    required: bool = False
    nullable: bool = True
    target: str | None = None     # Имя поля во внешней системе (напр., "lastName")
    generated: bool = False       # True → поле генерируется, не из mapper (напр., target_id)
```

`SinkSpec` используется в двух местах:
1. **`MapperDsl.compile()`** — проверяет, что все `targets` из `MappingRule` существуют в `sink.fields`
2. **`MapperCore._validate_sink()`** — после маппинга проверяет типы полей (только warnings)

`system_fields` (например, `target_id` с `generated: true`) не маппируются — они
добавляются позже в resolve-стадии. `MapperDsl` включает их в множество допустимых target-имён.

---

## 🗂️ Модели данных

### OperationCall

**Файл:** `connector/domain/dsl/specs/_base.py`

```python
class OperationCall(DslBaseModel):
    op: str              # Имя операции из TransformationEngine registry
    args: dict = {}      # Аргументы, передаются в ops-функцию как **kwargs
```

Атомарный вызов операции. В `MappingRule.ops` — список таких вызовов,
применяемых последовательно (output предыдущей → input следующей).

### CompiledMapRules

**Файл:** `connector/domain/transform_dsl/compilers/mapping.py`

```python
@dataclass(frozen=True)
class CompiledMapRules:
    rules: tuple[MappingRule, ...]         # Иммутабельный кортеж правил
    meta: tuple[MetaRule, ...]             # Правила для meta-секции
    schema_: MappingSchema | None          # Post-validation схема
    source_columns: tuple[str, ...] | None # Для позиционного fallback col_N
    options: MapDslBuildOptions            # Compile-policy
```

**Frozen dataclass** — создаётся один раз в `MapperDsl.compile()`, не мутируется.
`MapperCore` держит ссылку на `CompiledMapRules` через весь lifecycle runtime.

### MapDslBuildOptions

**Файл:** `connector/domain/transform_dsl/build_options.py`

```python
@dataclass(frozen=True)
class MapDslBuildOptions(BaseDslBuildOptions):
    require_targets_exist_in_sink_spec: bool = False
    # Из BaseDslBuildOptions:
    # fail_on_unknown_ops: bool = False
    # strict: bool = False
```

| Опция | Дефолт | Эффект при `True` |
|-------|--------|-------------------|
| `fail_on_unknown_ops` | `False` | `DslLoadError` если op не зарегистрирован в `TransformationEngine` |
| `require_targets_exist_in_sink_spec` | `False` | `DslLoadError` если target не объявлен в `SinkSpec` |
| `strict` | `False` | Включает оба выше одновременно |

---

## 📊 Ключевые методы и алгоритмы

### `MapperDsl.compile(spec, *, sink_spec)`

**Файл:** `connector/domain/transform_dsl/compilers/mapping.py`

```
Вход: MappingSpec, SinkSpec | None
Выход: CompiledMapRules

1. Если options.require_targets_exist_in_sink_spec И sink_spec is None:
   → DslLoadError("sink_spec is required when require_targets_exist_in_sink_spec=true")

2. Если options.require_targets_exist_in_sink_spec И sink_spec задан:
   → _validate_targets_in_sink(spec, sink_spec):
       sink_fields = {f.name for f in sink_spec.sink.fields}
                   | {f.name for f in sink_spec.sink.system_fields}
       Для каждого rule → targets = rule.targets or [rule.target]:
         Для каждого target:
           Если target не в sink_fields → DslLoadError("target does not exist in sink spec")

3. Если options.fail_on_unknown_ops:
   → _validate_ops_known(spec):
       Для каждого rule в rules + meta → для каждого op_call:
         Если engine.registry.get(op_call.op) is None →
           DslLoadError(f"Unknown operation '{op_call.op}'")

4. return CompiledMapRules(
       rules=tuple(spec.mapping.rules),
       meta=tuple(spec.mapping.meta),
       schema_=spec.mapping.schema_,
       source_columns=tuple(spec.source_columns) if spec.source_columns else None,
       options=self.options,
   )
```

При любой ошибке — `DslLoadError` с кодом `MAP_DSL_COMPILE_INVALID` или `DSL_OP_UNKNOWN`.
Это fail-fast при старте приложения, не в runtime.

### `load_mapping_spec_for_dataset(dataset)`

**Файл:** `connector/domain/transform_dsl/loader.py`

```
1. _load_registry_or_raise()
   → читает datasets/registry.yml
2. _resolve_dataset_path(registry, dataset, stage="mapping")
   → registry["datasets"][dataset]["mapping"] → путь к файлу
   → DslLoadError если dataset или stage не найдены
3. _read_yaml_or_raise(stage_path, code="MAP_DSL_SPEC_INVALID", ...)
   → читает YAML → dict
4. _validate_spec_or_raise(raw, MappingSpec, ...)
   → MappingSpec.model_validate(raw)
   → DslLoadError при Pydantic ValidationError
```

Аналогично работают `load_source_spec_for_dataset` и `load_sink_spec_for_dataset`.

### `load_map_build_options_for_dataset(dataset)` — merge-приоритет

```
Источники build options (каждый уровень перезаписывает предыдущий):

1. Defaults из MapDslBuildOptions (все поля = False)
2. registry.yml → build_options.base (глобальные базовые)
3. registry.yml → build_options.stages.mapping (глобальные для стадии)
4. registry.yml → datasets[dataset].build_options.mapping (специфичные для датасета)
```

Пример `registry.yml`:

```yaml
build_options:
  base:
    strict: false
  stages:
    mapping:
      fail_on_unknown_ops: true      # для всех датасетов
datasets:
  employees:
    mapping: employees.mapping.yaml
    sink: employees.sink.yaml
    source: employees.source.yaml
    build_options:
      mapping:
        require_targets_exist_in_sink_spec: true  # только для employees
```

### `resolve_source_location(spec)`

```python
def resolve_source_location(spec: SourceSpec) -> str:
    ref = spec.source.location_ref
    if ref:
        ref_value = os.getenv(ref)
        if ref_value and ref_value.strip():
            return ref_value.strip()
    location = spec.source.location
    if location and location.strip():
        return location.strip()
    raise DslLoadError(
        code="SOURCE_DSL_LOCATION_INVALID",
        message="source location is not configured (location_ref/location)",
        details={"dataset": spec.dataset},
    )
```

---

## 🔄 Взаимодействие с другими слоями

### Загрузчики DSL

`MapperEngine.from_dataset()` вызывает все четыре загрузчика:

```python
spec = load_mapping_spec_for_dataset(dataset)       # MappingSpec
sink_spec = load_sink_spec_for_dataset(dataset)     # SinkSpec
dsl_options = load_map_build_options_for_dataset(dataset)  # MapDslBuildOptions
# SourceSpec загружается отдельно в delivery при создании CsvRecordSource:
source_spec = load_source_spec_for_dataset(dataset)  # SourceSpec
```

### registry.yml — центральный реестр

```yaml
datasets:
  employees:
    source:  employees.source.yaml
    mapping: employees.mapping.yaml
    sink:    employees.sink.yaml
    # Опционально:
    normalize: employees.normalize.yaml
    enrich:    employees.enrich.yaml
    match:     employees.match.yaml
    resolve:   employees.resolve.yaml
```

Все loader-функции ищут путь к файлу через `datasets[dataset][stage]`.

### SinkSpec → MapperCore

`validate_sink_row(row, sink_spec, check_types=False)` вызывается в `MapperCore._validate_sink()`:
- Проверяет что required поля присутствуют
- При `check_types=False` — не проверяет типы (они валидируются в normalize-стадии)
- Несовпадение → warning, не error (row не обнуляется)

---

## 🔌 Контракты и границы

**DSL-пакет** (`connector/domain/transform_dsl/`) содержит только:
- Pydantic-модели (specs)
- Компилятор (`MapperDsl`)
- Loader-функции
- Build options

**Запрещённые импорты в DSL-слое:**
- `connector/infra/` — никакой инфраструктуры (CSV, httpx и т.д.)
- `connector/delivery/` — никакой доставки
- `connector/domain/transform/mapping/` — нет обратной зависимости (core → dsl, не наоборот)

**MapperEngine использует DSL:**
```python
# connector/domain/transform/mapping/mapper_engine.py
from connector.domain.transform_dsl import (
    load_map_build_options_for_dataset,
    load_mapping_spec_for_dataset,
    load_sink_spec_for_dataset,
)
from connector.domain.transform_dsl.compilers.mapping import MapperDsl
```

---

## 🛠️ HOW-TO

### Добавить новое поле маппинга

1. **SourceSpec:** если поле новое в источнике — добавить в `employees.source.yaml`:
   ```yaml
   fields:
     - name: department_code
       type: string
   ```
   Если нет заголовка CSV — добавить в `source_columns` в `employees.mapping.yaml`.

2. **MappingRule:** добавить правило в `employees.mapping.yaml`:
   ```yaml
   mapping:
     rules:
       - target: department
         source: department_code
         op: copy
   ```

3. **SinkSpec:** добавить поле в `employees.sink.yaml`:
   ```yaml
   sink:
     fields:
       - name: department
         type: string
         required: false
         target: department
   ```

4. (Опционально) добавить в `mapping.schema.required` если поле обязательно:
   ```yaml
   mapping:
     schema:
       required: [..., department]
   ```

### Добавить новую операцию

1. Реализовать функцию в `connector/domain/dsl/ops.py`:
   ```python
   def normalize_phone(value: Any, *, country_code: str = "+7") -> str | None:
       """Нормализовать номер телефона."""
       if not value:
           return None
       cleaned = re.sub(r"[^\d+]", "", str(value))
       if cleaned.startswith("8") and len(cleaned) == 11:
           cleaned = country_code + cleaned[1:]
       return cleaned
   ```

2. Зарегистрировать в `TransformationEngine.with_core_ops()`:
   ```python
   registry.register("normalize_phone", normalize_phone)
   ```

3. Использовать в YAML:
   ```yaml
   - target: phone
     source: phone_raw
     op: normalize_phone
     args:
       country_code: "+7"
   ```

### Изменить compile-policy для датасета

В `datasets/registry.yml`:
```yaml
datasets:
  employees:
    build_options:
      mapping:
        require_targets_exist_in_sink_spec: true
        fail_on_unknown_ops: true
```

---

## 💡 Типичные сценарии

### Полный пример: employees.mapping.yaml

```yaml
dataset: employees
# Список колонок в порядке позиций в CSV (для headerless-режима)
source_columns:
  - raw_id         # col_0
  - full_name      # col_1
  - login          # col_2
  - email_or_phone # col_3
  - contacts       # col_4
  - org            # col_5
  - manager        # col_6
  - flags          # col_7
  - employment     # col_8
  - extra          # col_9

mapping:
  rules:
    # 1. Прямое копирование: один источник → одно поле
    - target: personnel_number
      source: raw_id
      op: copy

    # 2. Один источник → несколько полей (split_name возвращает dict)
    - targets: [last_name, first_name, middle_name]
      source: full_name
      op: split_name
      args:
        fields: [last_name, first_name, middle_name]
        separator: " "
        allow_comma_format: true    # "Иванов, Иван" → работает

    # 3. Несколько источников → несколько полей (extract_patterns)
    - targets: [email, phone]
      sources: [email_or_phone, contacts]
      op: extract_patterns
      args:
        split_pattern: "[;|,]"
        patterns:
          email: "[^\\s,;|]+@[^\\s,;|]+"
          phone: "[+\\d][\\d\\s()\\-]{5,}"
        keyed_prefixes:
          email: "email="
          phone: "phone="

    # 4. Цепочка операций (ops): output одной → input следующей
    - target: manager_id
      source: manager
      ops:
        - op: regex_extract
          args:
            pattern: "(?:manager_id|manager)\\s*[:=]\\s*([^;]+)"
            group: 1
        - op: regex_extract
          args:
            pattern: "\\d+"
            group: 0

    # 5. Цепочка с map_dict (нормализация булевых значений)
    - target: is_logon_disable
      source: flags
      ops:
        - op: regex_extract
          args:
            pattern: "disabled\\s*[:=]\\s*([^;]+)"
            group: 1
        - op: map_dict
          args:
            casefold: true
            mapping:
              "true": "true"
              "1": "true"
              "yes": "true"
              "false": "false"
              "0": "false"
              "no": "false"

    # 6. parse_kv_pairs: "key=val;key2=val2" → несколько полей
    - targets: [password, organization_id, usr_org_tab_num]
      source: extra
      op: parse_kv_pairs
      args:
        sep: ";"
        kv_sep: "="
        keys:
          password: password
          organization_id: org_id
          usr_org_tab_num: tab

    # 7. Константа без источника
    - target: avatar_id
      op: const
      args:
        value: null

  # Post-validation: эти поля обязаны присутствовать после маппинга
  schema:
    required:
      - email
      - last_name
      - first_name
      - personnel_number
    allow_extra: true

  # Meta-правила: заполняются только если нет ошибок
  meta:
    - target: row.source_type
      op: const
      args: { value: "csv" }
```

### Пример: employees.source.yaml

```yaml
dataset: employees
source:
  type: file
  format: csv
  location_ref: EMPLOYEES_SOURCE_PATH   # путь из env
  options:
    delimiter: ","
    encoding: "utf-8-sig"               # снимает BOM автоматически
    has_header_default: false           # CSV без заголовка
  fields:
    - name: raw_id
      type: string
      required: true
      nullable: false
    - name: full_name
      type: string
      required: true
      nullable: false
    - name: login
      type: string
      required: true
    - name: email_or_phone
      type: string      # nullable по умолчанию
    - name: contacts
      type: string
    - name: manager
      type: string
    - name: flags
      type: string
    - name: employment
      type: string
    - name: extra
      type: string
```

### Пример: employees.sink.yaml

```yaml
dataset: employees
sink:
  fields:
    - name: email
      type: string
      required: true
      target: mail                  # ← имя поля в Ankey REST API
    - name: last_name
      type: string
      required: true
      target: lastName
    - name: first_name
      type: string
      required: true
      target: firstName
    - name: middle_name
      type: string
      required: true
      target: middleName
    - name: is_logon_disable
      type: bool
      required: true
      target: isLogonDisabled
    - name: manager_id
      type: int
      required: true
      nullable: true                # может быть null
      target: managerId
    - name: password
      type: string
      required: true
      target: password
    - name: organization_id
      type: int
      required: true
      target: organization_id
    - name: personnel_number
      type: string
      required: true
      target: personnelNumber
    - name: avatar_id
      type: string
      required: true
      nullable: true
      target: avatarId
  system_fields:
    - name: target_id              # Генерируется в resolve-стадии
      type: string
      required: true
      generated: true
```

---

## 📌 Важные детали

### Поведение on_error

| `on_error` | Ошибка в правиле | Итог |
|------------|-----------------|------|
| `"error"` (дефолт) | Target не назначается, `DiagnosticItem(ERROR)` добавляется | `final_row = None` если есть хоть одна ERROR |
| `"warn"` | Target не назначается, `DiagnosticItem(WARNING)` добавляется | `row` продолжает строиться |

`on_error: "warn"` полезен для опциональных полей — ошибка в них не должна блокировать строку.

### source_columns и позиционный fallback

`source_columns` критичен при `has_header_default: false` (CSV без заголовка):

```
source_columns: [raw_id, full_name, login, ...]
→ MapperCore._source_index = {"raw_id": 0, "full_name": 1, "login": 2, ...}

При чтении "raw_id" из записи {"col_0": "u-001", "col_1": "Иванов", ...}:
→ "raw_id" не найден напрямую
→ _source_index["raw_id"] = 0 → ищем "col_0" → найдено → "u-001"
```

Без `source_columns` маппинг работает только с заголовочными CSV.

### MetaRule применяются после успешного маппинга

```python
# MapperCore._apply_rules():
if not errors:
    for meta_rule in self.compiled.meta:
        meta_value, issues = self._resolve_meta_value(record, row, meta_rule)
        ...
```

Если в основных правилах есть ошибки — meta не вычисляется. Это намеренно:
нет смысла создавать метаданные для сломанной строки.

### Pydantic model_validator: sugar op → ops

```python
# В MappingRule:
@model_validator(mode="after")
def _validate_targets_sources(self) -> "MappingRule":
    if self.op and not self.ops:
        self.ops = [OperationCall(op=self.op, args=self.args or {})]
    ...
```

```yaml
# YAML (короткая форма):
- target: personnel_number
  source: raw_id
  op: copy
# После model_validator становится эквивалентным:
- target: personnel_number
  source: raw_id
  ops:
    - op: copy
      args: {}
```

---

## 🧪 Тестовое покрытие

| Файл | Что тестирует |
|------|--------------|
| `tests/unit/transform/test_mapping_dsl.py` | `MapperEngine.from_dataset()`, успешный маппинг, отсутствующие колонки, compile validation |
| `tests/unit/transform/test_source_spec.py` | `SourceSpec` загрузка и валидация, `resolve_source_location` |
| `tests/unit/transform/test_source_mapper.py` | `MapperEngine.map()` — полный маппинг с реальными данными |

---

## ❓ FAQ

**Почему `const` не требует `source`?**

Pydantic model_validator проверяет: если `source` и `sources` отсутствуют,
допускается это только когда в `ops` есть `op: const`. Иначе `ValueError`.

**Что если `targets: [a, b]` а op возвращает dict, а не list?**

`_assign_targets` обрабатывает оба случая:
- `isinstance(value, dict)` → `row[target] = value.get(target)` для каждого target
- `isinstance(value, (list, tuple))` → позиционно: `row[targets[0]] = value[0]`, и т.д.

**Как добавить поддержку нового типа источника (`type: "db"`)?**

Только в `connector/infra/sources/` — нужно создать новый ридер, реализующий
`RowSource` Protocol. Сам DSL-слой (`SourceSpec`) уже объявляет `type: "file" | "db" | "api"`,
поэтому изменений в specs не требуется.

**Зачем `sink.system_fields` отдельно от `fields`?**

`system_fields` (например, `target_id`) не маппируются mapper-стадией — они
генерируются или назначаются позже. При проверке `_validate_targets_in_sink` оба набора
включаются в допустимые names, но `MapperCore` не валидирует их отдельно.

**Что такое `allow_extra: true` в MappingSchema?**

Разрешает поля в `row`, которые не перечислены в `schema.required`. При `false`
(не используется пока) дополнительные поля давали бы предупреждение. Значение
`true` — безопасный дефолт: mapper может добавлять произвольные поля.

**Можно ли использовать одну операцию с несколькими `sources`?**

Да. Если `sources: [field1, field2]`, то в `_resolve_rule_value` собирается `list`
значений `[value1, value2]`, который передаётся как входное значение в `ops`.
Операция (`extract_patterns`) умеет работать со списком входных данных.

---

## 🔗 Связанные документы

| Документ | Описание |
|----------|---------|
| [mapper-core.md](mapper-core.md) | Core-логика: RowSource, CsvRecordSource, MapperCore, TransformResult, pipeline |
| [docs/dev/layers/dsl/dsl-engine.md](../dsl/dsl-engine.md) | TransformationEngine, операции, OperationRegistry |
| [docs/dev/layers/dsl/dsl-specs.md](../dsl/dsl-specs.md) | Базовые DSL-абстракции (DslBaseModel, OperationCall) |
| `datasets/employees.mapping.yaml` | Эталонный пример mapping-спецификации |
| `datasets/employees.source.yaml` | Эталонный пример source-спецификации |
| `datasets/employees.sink.yaml` | Эталонный пример sink-спецификации |
| `datasets/registry.yml` | Центральный реестр датасетов |

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-03-01 | Создан документ — DSL-спецификации mapper-слоя | xORex-LC |
