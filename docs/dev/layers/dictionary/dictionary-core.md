# Dictionary Core (Runtime)

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
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Компиляция валидированных DSL-specs в исполняемый runtime bundle (без IO), и детерминированное версионирование словарей через fingerprint-схему.

**Ключевая ответственность**:
- Приём уже валидированных `DictionarySpec` и `DictionaryManifestSpec` из DSL-слоя
- Резолвинг `normalized_key.ops` через `OperationRegistry` в цепочку callable объектов
- Верификация целостности: соответствие `schema_hash` из manifest вычисленному значению
- Вычисление детерминированных fingerprints (`schema_hash`, `version_id`) без IO
- Предоставление `DictionaryDslRuntimeBundle` как единой точки входа для backend

**Расположение в кодовой базе**:
- `connector/infra/dictionaries/dsl_runtime.py` — компилятор DSL → runtime объекты
- `connector/infra/dictionaries/versioning.py` — функции хэширования и `DictionaryVersionInfo`

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
connector/infra/dictionaries/
├── dsl_runtime.py     # Компилятор: DSL specs → CompiledDictionarySpec → Bundle
│   ├── CompiledDictionaryOperation   # Скомпилированная op нормализации
│   ├── CompiledDictionarySpec        # Compiled spec одного словаря (без данных)
│   ├── DictionaryDslRuntimeBundle    # Полный runtime bundle (все словари)
│   └── build_dictionary_dsl_runtime()  # Функция компиляции
└── versioning.py      # Fingerprinting и version info
    ├── DictionaryVersionInfo         # Version contract (v1/v2 forward-compatible)
    ├── build_dictionary_schema_hash()  # Детерминированный hash схемы
    ├── build_content_sha256_bytes()  # Hash raw bytes
    ├── build_content_sha256_for_file()  # Hash файла
    ├── build_dictionary_version_id() # Компактный version ID
    └── build_dictionary_version_info()  # Конструктор DictionaryVersionInfo
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [Dictionary Core Class Diagram](../../uml/dictionary/dictionary_core_class.png) | Структура compiled объектов и связи |
| Activity | [Compilation Flow](../../uml/dictionary/dictionary_core_activity_compilation.png) | Алгоритм компиляции specs → bundle |
| Sequence | [Build Runtime Sequence](../../uml/dictionary/dictionary_core_sequence_build.png) | Взаимодействие компонентов при build |

**PlantUML исходники**: `docs/uml/dictionary/*.puml`

### 🎭 Применённые паттерны

#### Паттерн 1: Compile-time Verification

**Где применяется**: `build_dictionary_dsl_runtime()` выполняет полную верификацию консистентности конфигурации до создания runtime объектов.

**Реализация в коде**:
- **Компилятор**: `build_dictionary_dsl_runtime()` в `dsl_runtime.py:130`
- **Schema hash verification**: сравнение manifest vs вычисленный `build_dictionary_schema_hash()`
- **Path reconciliation**: `_normalize_rel_path()` для сравнения `manifest.csv_path` и `spec.source.location`

**Пример использования**:
```python
# Компиляция выполняется один раз при старте — все ошибки всплывают сразу
bundle = build_dictionary_dsl_runtime(
    specs={"organizations": org_spec},
    manifest_spec=manifest_spec,
)
# После этого bundle — immutable, verifiable, ready for backend
```

**Зачем**: Fail-fast при старте вместо runtime surprises. Если schema в manifest не совпадает с реальной spec — это обнаруживается на startup, а не при первом lookup.

---

#### Паттерн 2: Immutable Compiled Objects (frozen dataclass)

**Где применяется**: `CompiledDictionaryOperation`, `CompiledDictionarySpec`, `DictionaryDslRuntimeBundle`, `DictionaryVersionInfo` — все frozen dataclasses.

**Реализация в коде**:
- `@dataclass(frozen=True)` в `dsl_runtime.py:30`, `dsl_runtime.py:49`, `dsl_runtime.py:113`
- `@dataclass(frozen=True)` в `versioning.py:102`

**Пример использования**:
```python
@dataclass(frozen=True)
class CompiledDictionarySpec:
    dict_name: str
    spec: DictionarySpec
    manifest_item: DictionaryManifestItemSpec
    schema_hash: str
    normalized_key_ops: tuple[CompiledDictionaryOperation, ...]
    # После создания объект неизменяем — попытка присвоить поле вызовет FrozenInstanceError
```

**Зачем**: Thread-safety для lookup в многопоточных сценариях. Предотвращение случайной мутации state после инициализации.

---

#### Паттерн 3: Operation Chain (Command + Chain of Responsibility)

**Где применяется**: `normalized_key_ops` — скомпилированная цепочка операций нормализации ключа.

**Реализация в коде**:
- **Command**: `CompiledDictionaryOperation` в `dsl_runtime.py:30` — инкапсулирует одну операцию (func + args)
- **Chain**: `CompiledDictionarySpec.normalize_key()` в `dsl_runtime.py:98` — последовательно применяет операции
- **Factory**: `_compile_normalized_key_ops()` в `dsl_runtime.py:198` — создаёт chain из DSL-описания

**Пример использования**:
```python
# Декларативное описание в YAML:
# ops: [{op: trim}, {op: lower}]

# Превращается в compiled chain:
compiled_ops = (
    CompiledDictionaryOperation(name="trim", func=trim_func, args={}),
    CompiledDictionaryOperation(name="lower", func=lower_func, args={}),
)

# Применяется к каждому ключу:
result = compiled_spec.normalize_key(" ORG-1 ")
# → trim(" ORG-1 ") → "ORG-1" → lower("ORG-1") → "org-1"
```

**Зачем**: Расширяемость без изменения core-логики. Каждая операция — self-contained callable. Цепочка конфигурируется декларативно через DSL.

---

#### Паттерн 4: Deterministic Schema Fingerprinting

**Где применяется**: `build_dictionary_schema_hash()` вычисляет стабильный fingerprint схемы для drift detection.

**Реализация в коде**:
- **Функция**: `build_dictionary_schema_hash()` в `versioning.py:38`
- **Canonical JSON**: `_canonical_json()` в `versioning.py:23` — `sort_keys=True, separators=(",", ":")`

**Зачем**: Детерминированность — один и тот же spec всегда даёт одинаковый hash. Используется для обнаружения schema drift без полного сравнения YAML.

### Диаграмма зависимостей

```
[DictionarySpec]     [DictionaryManifestSpec]
      ↓                       ↓
[build_dictionary_dsl_runtime()]
      ├── build_dictionary_schema_hash(spec) ← versioning.py
      ├── _compile_normalized_key_ops()      ← dsl_runtime.py
      │       └── OperationRegistry.get(op_name)
      └── [DictionaryDslRuntimeBundle]
              ├── specs: dict[str, CompiledDictionarySpec]
              │       ├── CompiledDictionarySpec.normalized_key_ops
              │       │       └── CompiledDictionaryOperation (func + args)
              │       └── CompiledDictionarySpec.manifest_item
              └── manifest_spec: DictionaryManifestSpec

[DictionaryDslRuntimeBundle] → передаётся в [PolarsDictionaryBackend]
[DictionaryVersionInfo]       → создаётся в [load_dictionary_frame()] (infra)
```

---

## 🔑 Ключевые абстракции

### Основные классы

| Класс | Роль | Ключевые методы/свойства |
|-------|------|--------------------------|
| `CompiledDictionaryOperation` | Скомпилированная единица нормализации | `apply(value) -> Any` |
| `CompiledDictionarySpec` | Compiled runtime описание словаря (без данных) | `normalize_key()`, свойства `key_column`, `value_columns`, `allowed_columns`, `source_location` |
| `DictionaryDslRuntimeBundle` | Полный runtime bundle всех словарей | `get(dict_name) -> CompiledDictionarySpec` |
| `DictionaryVersionInfo` | Version contract (v1/v2 forward-compatible) | fields: `version_id`, `schema_hash`, `row_count` |

### Функции

| Функция | Расположение | Назначение |
|---------|-------------|-----------|
| `build_dictionary_dsl_runtime()` | `dsl_runtime.py:130` | Основная точка входа — compile DSL → bundle |
| `build_dictionary_schema_hash()` | `versioning.py:38` | SHA-256 hash lookup-схемы (детерминированный) |
| `build_content_sha256_bytes()` | `versioning.py:66` | SHA-256 raw bytes |
| `build_content_sha256_for_file()` | `versioning.py:74` | SHA-256 файла (по path) |
| `build_dictionary_version_id()` | `versioning.py:84` | Компактный ID: `name:schema[:12]:content[:12]` |
| `build_dictionary_version_info()` | `versioning.py:118` | Конструктор `DictionaryVersionInfo` с дефолтами |

---

## 🗂️ Модели данных

### Dataclass: `CompiledDictionaryOperation`

**Назначение**: Скомпилированная (resolved) операция нормализации ключа — содержит имя, callable функцию и аргументы.

**Структура**:
```python
@dataclass(frozen=True)
class CompiledDictionaryOperation:
    name: str                    # Имя операции (e.g. "trim", "lower", "regex_replace")
    func: Callable[..., Any]     # Callable из OperationRegistry
    args: dict[str, Any]         # Аргументы операции (e.g. {"old": "\n", "new": ""})

    def apply(self, value: Any) -> Any:
        return self.func(value, **self.args)
```

**Создание**:
```python
# Создаётся в _compile_normalized_key_ops()
op = registry.get("trim")  # OperationRegistry lookup
compiled = CompiledDictionaryOperation(
    name=op.name,
    func=op.func,
    args=dict(op_call.args),  # из DSL OperationCall
)
```

**Lifecycle**:
1. **Создание**: В `_compile_normalized_key_ops()` при компиляции bundle
2. **Хранение**: В `CompiledDictionarySpec.normalized_key_ops` (frozen tuple)
3. **Применение**: Через `CompiledDictionarySpec.normalize_key()` при каждом lookup

**Инварианты**:
- `func` — side-effect-free callable (только операции из whitelist)
- `args` — dict без ссылок на изменяемые объекты (создаётся через `dict()` копирование)
- `frozen=True` — неизменяем после создания

---

### Dataclass: `CompiledDictionarySpec`

**Назначение**: Полное скомпилированное описание одного словаря — содержит всё необходимое для загрузки данных и выполнения lookup, кроме самих данных.

**Структура**:
```python
@dataclass(frozen=True)
class CompiledDictionarySpec:
    dict_name: str                                           # Имя словаря
    spec: DictionarySpec                                     # Оригинальный DSL spec
    manifest_item: DictionaryManifestItemSpec                # Fingerprint metadata из manifest
    schema_hash: str                                         # Вычисленный hash схемы (верифицирован)
    normalized_key_ops: tuple[CompiledDictionaryOperation, ...]  # Compiled normalization chain

    # Computed properties (делегируют в spec):
    @property
    def key_column(self) -> str: ...                # spec.data_schema.key_column
    @property
    def value_columns(self) -> tuple[str, ...]: ... # spec.data_schema.value_columns
    @property
    def allowed_columns(self) -> tuple[str, ...]: . # (key_column, *value_columns)
    @property
    def allow_duplicates(self) -> bool: ...         # spec.lookup.allow_duplicates
    @property
    def source_location(self) -> str: ...           # spec.source.location
    @property
    def csv_delimiter(self) -> str: ...             # spec.source.csv.delimiter
    @property
    def csv_has_header(self) -> bool: ...           # spec.source.csv.has_header
    @property
    def csv_encoding(self) -> str: ...              # spec.source.csv.encoding
```

**Метод `normalize_key()`**:
```python
def normalize_key(self, value: Any) -> Any:
    """
    Применить compiled chain normalized_key.ops к значению ключа.
    - При отсутствии ops возвращает значение как есть.
    - Исключения операций не подавляются (fail-fast runtime semantics).
    """
    current = value
    for op in self.normalized_key_ops:
        current = op.apply(current)
    return current
```

**Lifecycle**:
1. **Создание**: В `build_dictionary_dsl_runtime()` — после верификации hash и компиляции ops
2. **Хранение**: В `DictionaryDslRuntimeBundle.specs[dict_name]`
3. **Использование**: В `PolarsDictionaryBackend` при построении key-index и при каждом lookup

**Инварианты**:
- `schema_hash` совпадает с `manifest_item.schema_hash` (проверено при создании bundle)
- `normalized_key_ops` содержит только операции из whitelist
- `allowed_columns = {key_column} ∪ value_columns`

---

### Dataclass: `DictionaryDslRuntimeBundle`

**Назначение**: Единая точка входа для всего скомпилированного dictionary runtime — содержит все compiled specs и manifest.

**Структура**:
```python
@dataclass(frozen=True)
class DictionaryDslRuntimeBundle:
    specs: dict[str, CompiledDictionarySpec]  # dict_name → CompiledDictionarySpec
    manifest_spec: DictionaryManifestSpec     # Исходный manifest (для reference)

    def get(self, dict_name: str) -> CompiledDictionarySpec:
        spec = self.specs.get(dict_name)
        if spec is None:
            raise KeyError(dict_name)
        return spec
```

**Создание**:
```python
bundle = build_dictionary_dsl_runtime(
    specs={"organizations": org_spec, "departments": dept_spec},
    manifest_spec=manifest_spec,
)
```

**Lifecycle**:
1. **Создание**: `build_dictionary_dsl_runtime()` — один раз при старте
2. **Хранение**: В `PolarsDictionaryBackend` как `self.bundle`
3. **Завершение**: Живёт всё время жизни приложения (no teardown)

**Инварианты**:
- Только enabled specs входят в `specs`
- Каждый key в `specs` соответствует entry в `manifest_spec.items`
- Нет specs с расхождением `schema_hash`

---

### Dataclass: `DictionaryVersionInfo`

**Назначение**: Унифицированный version contract словаря — создаётся после загрузки данных, описывает версию загруженного snapshot.

**Структура**:
```python
@dataclass(frozen=True)
class DictionaryVersionInfo:
    dict_name: str           # Имя словаря
    version_id: str          # Компактный ID: "orgs:sha[:12]:sha[:12]"
    schema_hash: str         # Полный SHA-256 hash схемы
    row_count: int           # Количество строк в загруженном snapshot
    source_format: str       # Формат источника ("csv" в v1)
    loaded_at: str           # ISO timestamp загрузки (UTC)
    fingerprint_kind: str    # Тип fingerprint ("content_sha256" в v1)
```

**Формат `version_id`**:
```
{dict_name}:{schema_hash[:12]}:{content_sha256[:12]}

Пример: "organizations:c797aaf53db7:59aff796321b"
```

**Lifecycle**:
1. **Создание**: В `PolarsDictionaryBackend.load_dictionary_frame()` через `build_dictionary_version_info()`
2. **Хранение**: В `_LoadedDictionaryData.version_info` и в `DictionaryTelemetry._metadata_by_dict`
3. **Использование**: В telemetry snapshot, в `DictionaryCsvLoadEvent`, через `backend.get_version_info()`

**Инварианты**:
- `version_id` детерминирован для одного и того же content + schema
- `fingerprint_kind = "content_sha256"` в v1 (зарезервировано для v2)
- `loaded_at` — ISO 8601 UTC без микросекунд

---

## 📊 Ключевые методы и алгоритмы

### Обзор сложных методов

| Метод/Функция | Строк | Сложность | Назначение |
|---------------|-------|-----------|------------|
| `build_dictionary_dsl_runtime()` | 65 | O(n) | Компиляция всех specs + manifest в bundle |
| `_compile_normalized_key_ops()` | 30 | O(k) | Резолвинг ops в callable chain |
| `build_dictionary_schema_hash()` | 25 | O(1) | SHA-256 hash subset полей схемы |
| `CompiledDictionarySpec.normalize_key()` | 8 | O(k) | Применение chain к значению ключа |

*n = количество словарей, k = длина цепочки normalized_key.ops*

---

### Функция: `build_dictionary_dsl_runtime()`

**Расположение**: `connector/infra/dictionaries/dsl_runtime.py:130`

**Сигнатура**:
```python
def build_dictionary_dsl_runtime(
    *,
    specs: dict[str, DictionarySpec],
    manifest_spec: DictionaryManifestSpec,
    operation_registry: OperationRegistry | None = None,
) -> DictionaryDslRuntimeBundle:
    """
    Скомпилировать dictionary DSL specs + manifest в runtime bundle (без IO).
    """
```

**Назначение**: Основная функция компиляции — принимает валидированные Pydantic-модели и производит готовый к использованию runtime bundle с верифицированными fingerprints и скомпилированными операциями.

**Алгоритм**:
```
1. Инициализация OperationRegistry (line 145)
   registry = operation_registry OR register_core_ops(OperationRegistry())
   (lazily инициализируется если не передан — для тестов и standalone use)

2. FOR EACH (dict_name, spec) IN specs.items(): (lines 148-190)

   2.1. Проверка наличия в manifest (lines 149-155)
     manifest_item = manifest_spec.items.get(dict_name)
     IF manifest_item IS None:
       RAISE DslLoadError(DICT_SOURCE_MANIFEST_INVALID,
                          "Dictionary manifest entry is missing for '{dict_name}'")

   2.2. Верификация csv_path (lines 157-169)
     _normalize_rel_path(manifest_item.csv_path) == _normalize_rel_path(spec.source.location)
     IF mismatch:
       RAISE DslLoadError(DICT_SOURCE_MANIFEST_INVALID,
                          "Dictionary manifest csv_path mismatch for '{dict_name}'")
     (нормализация: Path.as_posix().lstrip("./") для идемпотентного сравнения)

   2.3. Верификация schema_hash (lines 171-181)
     schema_hash = build_dictionary_schema_hash(spec)
     IF manifest_item.schema_hash != schema_hash:
       RAISE DslLoadError(DICT_SOURCE_FINGERPRINT_MISMATCH,
                          "Dictionary schema hash mismatch for '{dict_name}'")

   2.4. Компиляция normalized_key.ops (line 183)
     compiled_ops = _compile_normalized_key_ops(dict_name, spec, registry)
     → FOR EACH op_call IN spec.data_schema.normalized_key.ops:
         op = registry.get(op_call.op)
         IF op IS None:
           RAISE DslLoadError(DICT_DSL_SPEC_INVALID, "Unknown op")
         CREATE CompiledDictionaryOperation(name, func, args)

   2.5. Создание CompiledDictionarySpec (lines 184-190)
     compiled_specs[dict_name] = CompiledDictionarySpec(
       dict_name, spec, manifest_item, schema_hash, compiled_ops
     )

3. Return DictionaryDslRuntimeBundle(specs=compiled_specs, manifest_spec=manifest_spec)
```

**Временная сложность**:
- **Типичный случай**: O(n × k), где n = число словарей, k = длина ops chain
- SHA-256 computation: O(len(canonical_json)) ≈ O(1) (схема небольшая)
- OperationRegistry.get(): O(1) per op

**Инварианты**:
1. Для каждого spec в `specs` существует entry в `manifest_spec.items`
2. `manifest_item.schema_hash` совпадает с вычисленным `build_dictionary_schema_hash(spec)`
3. `manifest_item.csv_path` и `spec.source.location` нормализуются к одному пути
4. Все ops в `normalized_key.ops` существуют в `OperationRegistry`

**Edge cases**:
- **Пустой `specs`**: Возвращает пустой bundle без ошибок
- **`normalized_key=None`**: `_compile_normalized_key_ops()` возвращает `()` (empty tuple)
- **Кастомный `operation_registry`**: Используется в тестах для подстановки mock-операций

---

### Функция: `build_dictionary_schema_hash()`

**Расположение**: `connector/infra/dictionaries/versioning.py:38`

**Сигнатура**:
```python
def build_dictionary_schema_hash(spec: DictionarySpec) -> str:
    """
    Вычислить schema_hash словаря по ADR v1 (subset contract).
    В hash входят только поля, влияющие на lookup semantics и storage contract.
    """
```

**Назначение**: Детерминированный fingerprint lookup-схемы словаря для drift detection. Позволяет обнаружить изменение схемы без полного сравнения YAML.

**Алгоритм**:
```
1. Построить canonical subset (lines 46-61):
   schema_subset = {
     "dictionary": spec.dictionary,
     "source": {"format": spec.source.format},
     "schema": {
       "key_column": spec.data_schema.key_column,
       "value_columns": list(spec.data_schema.value_columns),
       "normalized_key": {
         "ops": [{"op": op.op, "args": dict(op.args)} for op in normalized_key.ops]
         # или [] если normalized_key is None
       }
     },
     "lookup": {"allow_duplicates": spec.lookup.allow_duplicates}
   }

2. Canonical JSON serialization (line 28):
   json.dumps(schema_subset,
              ensure_ascii=False,
              sort_keys=True,       # Детерминированный порядок ключей
              separators=(",", ":")) # Без пробелов → минимальный payload

3. SHA-256 hash:
   hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
```

**Что входит в hash** (влияет на lookup semantics):
- `dictionary` — имя словаря
- `source.format` — тип источника данных
- `schema.key_column` — колонка поиска
- `schema.value_columns` — возвращаемые колонки
- `schema.normalized_key.ops` — цепочка нормализации
- `lookup.allow_duplicates` — политика дубликатов

**Что НЕ входит в hash** (не влияет на lookup):
- `source.csv.delimiter`, `source.csv.encoding`, `source.csv.has_header` — параметры парсинга, не lookup semantics
- `manifest.updated_at_utc`, `manifest.owner` — метаданные

**Детерминированность**: Для одного и того же spec — всегда один и тот же hash, независимо от Python version, порядка объявления полей или платформы (благодаря `sort_keys=True`).

---

### Метод: `CompiledDictionarySpec.normalize_key()`

**Расположение**: `connector/infra/dictionaries/dsl_runtime.py:98`

**Сигнатура**:
```python
def normalize_key(self, value: Any) -> Any:
    """
    Применить compiled chain normalized_key.ops к значению ключа.
    - При отсутствии ops возвращает значение как есть.
    - Исключения операций не подавляются (fail-fast runtime semantics).
    """
```

**Назначение**: Hot path — вызывается при каждом lookup для нормализации входящего ключа перед поиском в index.

**Алгоритм**:
```
IF normalized_key_ops == ():
  RETURN value (без изменений)

current = value
FOR op IN normalized_key_ops:
  current = op.apply(current)
  → op.func(current, **op.args)
RETURN current

Пример: normalize_key(" ORG-1 ")
  → trim(" ORG-1 ") → "ORG-1"
  → lower("ORG-1")  → "org-1"
```

**Временная сложность**: O(k), где k = длина `normalized_key_ops` (обычно 1–3 операции)

**Инварианты**:
- Операции применяются строго в порядке объявления в DSL
- Ошибки операций пробрасываются как-есть (fail-fast)
- При пустой цепочке — identity function (no-op)

---

## 🛠️ Как расширять

### Добавить поддержку нового типа операции в compiled chain

1. **Реализовать функцию операции**:
   ```python
   # connector/domain/dsl/ops/string_ops.py (или аналог)
   def strip_prefix(value: Any, *, prefix: str) -> Any:
       text = str(value) if value is not None else ""
       return text.removeprefix(prefix)
   ```

2. **Зарегистрировать в `OperationRegistry`**:
   ```python
   # connector/domain/dsl/registry.py → register_core_ops()
   registry.register("strip_prefix", strip_prefix)
   ```

3. **Добавить в whitelist** (в domain/dictionary_dsl/specs.py):
   ```python
   DICTIONARY_NORMALIZED_KEY_OPS_WHITELIST: frozenset[str] = frozenset({
       ..., "strip_prefix"
   })
   ```

4. **Использовать в DSL**:
   ```yaml
   normalized_key:
     ops:
       - op: strip_prefix
         args:
           prefix: "DEPT-"
   ```

5. **Обновить manifest**: Изменение `normalized_key.ops` меняет `schema_hash` — нужно пересчитать и обновить manifest.

---

### Добавить поле в `DictionaryVersionInfo` (v2 extension)

`DictionaryVersionInfo` спроектирован как forward-compatible — добавление необязательных полей допустимо:

```python
@dataclass(frozen=True)
class DictionaryVersionInfo:
    # ... существующие поля ...
    parquet_path: str | None = None  # ← v2: путь к Parquet snapshot
    temporal_at: str | None = None   # ← v2: temporal lookup timestamp
```

**Важно**: Изменение полей влияет на telemetry snapshot (`asdict(version_info)`) — проверить `DictionaryTelemetry.record_dictionary_loaded()`.

---

### Добавить новый тип source в compiled spec (v2+)

1. Добавить новые свойства в `CompiledDictionarySpec` для нового source type (например, `parquet_path`)
2. Обновить `build_dictionary_dsl_runtime()` для условной компиляции в зависимости от `spec.source.format`
3. Создать новый `_compile_parquet_spec()` по аналогии с текущей логикой

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| Dictionary DSL | Потребляет | `DictionarySpec`, `DictionaryManifestSpec` | Входные данные для компиляции |
| DSL Core | Потребляет | `OperationRegistry`, `DslLoadError` | Резолвинг ops, типизация ошибок |
| Dictionary Infra (Backend) | Предоставляет | `DictionaryDslRuntimeBundle`, `CompiledDictionarySpec` | Backend получает compiled bundle |
| Dictionary Infra (Loader) | Предоставляет | `DictionaryVersionInfo`, `build_content_sha256_*` | Versioning утилиты для loader |
| Dictionary Delivery | Предоставляет | `build_dictionary_dsl_runtime()` | Container вызывает при startup |

---

## 🔌 Контракты и границы

### Runtime-контракт: `DictionaryDslRuntimeBundle`

**Что получает инфраструктурный слой после компиляции DSL**:

```python
@dataclass(frozen=True)
class DictionaryDslRuntimeBundle:
    specs: dict[str, CompiledDictionarySpec]  # Всё для инициализации backend
    manifest_spec: DictionaryManifestSpec     # Для reference / audit
```

**Гарантии bundle**:
- Все `CompiledDictionarySpec.schema_hash` совпадают с `manifest_item.schema_hash`
- Все `normalized_key_ops` — resolved callable chains
- Нет specs с unknown op-именами
- `manifest_item.csv_path` нормализован и совпадает с `spec.source.location`

**Используется в**: `PolarsDictionaryBackend.__init__(bundle=...)`

**Пример использования**:
```python
# После компиляции DSL:
bundle = build_dictionary_dsl_runtime(specs=specs, manifest_spec=manifest)

# Backend принимает bundle как единственный источник правды:
backend = PolarsDictionaryBackend(bundle=bundle)

# Получение spec по имени (KeyError если не существует):
compiled = bundle.get("organizations")
print(compiled.key_column)      # "code"
print(compiled.allowed_columns) # ("code", "name", "ouid")
```

---

### Versioning-контракт: `DictionaryVersionInfo`

**Что создаётся при загрузке данных**:

```python
@dataclass(frozen=True)
class DictionaryVersionInfo:
    dict_name: str
    version_id: str          # "orgs:schema_prefix:content_prefix"
    schema_hash: str         # Полный hash
    row_count: int
    source_format: str       # "csv"
    loaded_at: str           # ISO UTC
    fingerprint_kind: str    # "content_sha256"
```

**Гарантии**:
- `version_id` — детерминирован для одного content + schema
- `loaded_at` — всегда UTC ISO 8601 без микросекунд
- `fingerprint_kind = "content_sha256"` в v1 (reserved for evolution)

**Используется в**: `_LoadedDictionaryData`, `DictionaryCsvLoadEvent`, `DictionaryTelemetry`

---

### Границы слоёв

**Разрешённые зависимости**:
- ✅ `dsl_runtime.py` → `connector/domain/dictionary_dsl/specs` — использует DSL models
- ✅ `dsl_runtime.py` → `connector/domain/dsl/issues` — `DslLoadError`
- ✅ `dsl_runtime.py` → `connector/domain/dsl/registry` — `OperationRegistry`
- ✅ `dsl_runtime.py` → `connector/infra/dictionaries/versioning` — `build_dictionary_schema_hash`
- ✅ `versioning.py` → `connector/domain/dictionary_dsl/specs` — `DictionarySpec` для hash
- ✅ `versioning.py` → stdlib (`hashlib`, `json`, `pathlib`) — только stdlib

**Запрещённые зависимости**:
- ❌ `dsl_runtime.py` / `versioning.py` → `polars` — нет зависимости от backend
- ❌ `dsl_runtime.py` / `versioning.py` → `connector/delivery/*` — нет DI
- ❌ `dsl_runtime.py` / `versioning.py` → CSV IO — compile-time only, нет IO

**Визуальная граница**:
```
┌──────────────────────────────────────────────────────────────────┐
│ Dictionary Core (dsl_runtime.py + versioning.py)                 │
│   INPUT:  DictionarySpec + DictionaryManifestSpec (from DSL)     │
│   INPUT:  OperationRegistry (from DSL Core)                      │
│   OUTPUT: DictionaryDslRuntimeBundle (для Infra Backend)         │
│   OUTPUT: DictionaryVersionInfo (для Infra Loader + Telemetry)   │
│   NO IO:  нет CSV, нет файлов, нет сети                          │
│   VERIFY: schema_hash, csv_path reconciliation (fail-fast)       │
└──────────────────────────────────────────────────────────────────┘
```

---

## 💡 Типичные сценарии

### Сценарий 1: Startup компиляция словарей

**Задача**: Собрать runtime bundle при старте приложения.

**Решение**:
```python
from connector.domain.dictionary_dsl import (
    load_enabled_dictionary_specs_for_runtime,
    load_dictionary_manifest_spec_for_runtime,
)
from connector.infra.dictionaries.dsl_runtime import build_dictionary_dsl_runtime

specs = load_enabled_dictionary_specs_for_runtime()
manifest = load_dictionary_manifest_spec_for_runtime()

# Компиляция с верификацией fingerprints (fail-fast на расхождение)
bundle = build_dictionary_dsl_runtime(specs=specs, manifest_spec=manifest)

# bundle готов — можно передавать в PolarsDictionaryBackend
print(bundle.specs.keys())  # dict_keys(['organizations', 'departments'])
```

---

### Сценарий 2: Вычисление schema_hash для обновления manifest

**Задача**: Разработчик изменил `normalized_key.ops` в spec — нужно пересчитать schema_hash.

**Решение**:
```python
from connector.domain.dictionary_dsl import load_dictionary_spec
from connector.infra.dictionaries.versioning import (
    build_dictionary_schema_hash,
    build_content_sha256_for_file,
)

spec = load_dictionary_spec("datasets/dictionaries/organizations.dictionary.yaml")
new_schema_hash = build_dictionary_schema_hash(spec)
new_content_sha256 = build_content_sha256_for_file("datasets/dictionaries/organizations.csv")

print(f"schema_hash:    {new_schema_hash}")
print(f"content_sha256: {new_content_sha256}")
# Обновить актуальный manifest-файл словарей вручную
```

---

### Сценарий 3: Нормализация ключа в тестах

**Задача**: Проверить, что цепочка `[trim, lower]` правильно нормализует ключ.

**Решение**:
```python
from connector.infra.dictionaries.dsl_runtime import build_dictionary_dsl_runtime
from connector.domain.dictionary_dsl import load_dictionary_spec
from connector.domain.dictionary_dsl.specs import DictionaryManifestSpec

spec = load_dictionary_spec("datasets/dictionaries/organizations.dictionary.yaml")
manifest = DictionaryManifestSpec.model_validate({
    "version": 1,
    "items": {
        "organizations": {
            "csv_path": spec.source.location,
            "content_sha256": "...",
            "schema_hash": build_dictionary_schema_hash(spec),
            "row_count": 0,
            "updated_at_utc": "2026-01-01T00:00:00Z",
            "owner": "test",
        }
    }
})
bundle = build_dictionary_dsl_runtime(specs={"organizations": spec}, manifest_spec=manifest)
compiled = bundle.get("organizations")

assert compiled.normalize_key(" ORG-1 ") == "org-1"
assert compiled.normalize_key("ORG-2") == "org-2"
```

---

### Сценарий 4: Диагностика ошибки fingerprint mismatch

**Задача**: При старте получена ошибка `DICT_SOURCE_FINGERPRINT_MISMATCH` — нужно выяснить причину.

**Решение**:
```python
# Шаг 1: Вычислить актуальный schema_hash
from connector.infra.dictionaries.versioning import build_dictionary_schema_hash
from connector.domain.dictionary_dsl import load_dictionary_spec

spec = load_dictionary_spec("datasets/dictionaries/organizations.dictionary.yaml")
actual_hash = build_dictionary_schema_hash(spec)

# Шаг 2: Прочитать hash из manifest
import yaml
with open("datasets/dictionaries/ankey.dictionary.manifest.yaml") as f:
    manifest = yaml.safe_load(f)
manifest_hash = manifest["items"]["organizations"]["schema_hash"]

print(f"Actual:   {actual_hash}")
print(f"Manifest: {manifest_hash}")
# Если не совпадают → spec изменился без обновления manifest
```

---

## 📌 Важные детали

### Особенности реализации

- **`_normalize_rel_path()`**: При сравнении `manifest.csv_path` и `spec.source.location` применяется нормализация через `Path(value).as_posix().lstrip("./")` — позволяет записывать пути как `"dictionaries/orgs.csv"` или `"./dictionaries/orgs.csv"` без ошибок.

- **Lazy `OperationRegistry`**: Если `operation_registry` не передан явно, `build_dictionary_dsl_runtime()` создаёт и инициализирует registry самостоятельно через `register_core_ops()`. Это позволяет вызывать функцию standalone без DI.

- **`normalized_key_ops: tuple`**: Используется `tuple`, а не `list`, потому что `@dataclass(frozen=True)` требует hashable типов для полей. `list` не hashable.

- **`args: dict[str, Any]` в `CompiledDictionaryOperation`**: Создаётся через `dict(op_call.args)` — копирование для изоляции от мутаций исходного объекта.

### 🚨 Failure Modes

| Исключение | Условие возникновения | Поведение системы | Как обработать |
|------------|----------------------|-------------------|---------------|
| `DslLoadError(DICT_SOURCE_MANIFEST_INVALID)` — missing entry | В `manifest.yml` нет entry для словаря, который есть в specs | Fail-fast в `build_dictionary_dsl_runtime()` | Добавить entry в `manifest.yml` |
| `DslLoadError(DICT_SOURCE_MANIFEST_INVALID)` — csv_path mismatch | `manifest.csv_path` не совпадает с `spec.source.location` (после нормализации) | Fail-fast в `build_dictionary_dsl_runtime()` | Синхронизировать пути в manifest и spec |
| `DslLoadError(DICT_SOURCE_FINGERPRINT_MISMATCH)` — schema_hash mismatch | Spec изменился без обновления `schema_hash` в manifest | Fail-fast в `build_dictionary_dsl_runtime()` | Пересчитать и обновить `schema_hash` в manifest |
| `DslLoadError(DICT_DSL_SPEC_INVALID)` — unknown op | `normalized_key.ops` содержит op, не зарегистрированную в `OperationRegistry` | Fail-fast при компиляции ops | Зарегистрировать op или убрать из DSL |
| `KeyError` в `bundle.get()` | Запрос spec по имени словаря, которого нет в bundle | `KeyError` при `backend.bundle.get()` | Проверить, что словарь enabled в registry |

### ⚠️ Инварианты системы

1. **Инвариант: schema_hash верифицирован при компиляции**
   - **Что**: `CompiledDictionarySpec.schema_hash` совпадает с `manifest_item.schema_hash`
   - **Почему важно**: Гарантия, что runtime bundle соответствует зафиксированному snapshot
   - **Где проверяется**: `build_dictionary_dsl_runtime()` line 172

2. **Инвариант: csv_path соответствует source.location**
   - **Что**: После path-нормализации `manifest.csv_path == spec.source.location`
   - **Почему важно**: Loader должен читать именно тот файл, для которого вычислен fingerprint
   - **Где проверяется**: `build_dictionary_dsl_runtime()` line 157

3. **Инвариант: все ops resolved**
   - **Что**: Каждая op в `normalized_key_ops` имеет resolved `func` из `OperationRegistry`
   - **Почему важно**: `normalize_key()` вызывается на hot path — нет места для lazy resolution
   - **Где проверяется**: `_compile_normalized_key_ops()` line 214

4. **Инвариант: bundle frozen после создания**
   - **Что**: `DictionaryDslRuntimeBundle` и все вложенные объекты — `frozen=True`
   - **Почему важно**: Thread-safety при concurrent lookups
   - **Где**: `@dataclass(frozen=True)` на всех compiled объектах

### ⏱️ Performance заметки

**Узкие места**:
1. **Компиляция bundle** (`build_dictionary_dsl_runtime()`)
   - **Проблема**: SHA-256 вычисляется для каждого словаря
   - **Текущая оптимизация**: Выполняется один раз при старте — не hot path
   - **Benchmark**: 10 словарей ≈ 2 мс (доминирует время Pydantic-валидации YAML)

2. **`normalize_key()`** в hot path
   - **Проблема**: Вызывается при каждом lookup + при построении key-index
   - **Текущая оптимизация**: Pre-compiled callable chain (нет runtime parsing)
   - **Benchmark**: Цепочка из 2 операций ≈ 0.5 мкс на ключ

**Оптимизации**:
- **Compiled ops**: Операции компилируются в tuple callable при startup, а не интерпретируются при каждом lookup
- **Frozen dataclasses**: Нет overhead на defensive copy при передаче между слоями

---

## 🔗 Связанные документы

- [Dictionary DSL](./dictionary-dsl.md) — Pydantic-модели и loader (вход для Core)
- [Dictionary Infra (Backend)](./dictionary-infra.md) — PolarsDictionaryBackend, CsvDictionaryLoader
- [Dictionary Delivery](./dictionary-delivery.md) — DI container, точка сборки
- [ADR: Columnar Dictionary Runtime](../../adr/transform/TRANSFORM-DEC-001-columnar-dictionary-runtime-for-enricher.md)

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-27 | Первоначальное создание документа | xORex-LC |
| 2026-05-05 | Обновлены примеры manifest-path под актуальный общий dictionary manifest | xORex-LC |
