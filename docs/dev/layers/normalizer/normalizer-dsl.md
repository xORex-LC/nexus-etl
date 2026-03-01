# Normalizer DSL — спецификации правил нормализации и операций

> **Normalizer DSL** — декларативный слой, определяющий правила нормализации (`NormalizeSpec`): приведение типов, форматирование, обогащение значений. Хранится в YAML и компилируется в `CompiledNormalizeRules` при инициализации.

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

Normalizer-слой — вторая стадия transform-pipeline. Он получает `TransformResult`
после mapper-стадии (строки уже «сырые», тип полей — `str | None`) и приводит значения
к каноническому виду: убирает лишние пробелы, конвертирует типы, применяет регулярные
выражения и таблицы замен.

**Что получает normalizer на вход:**

```
TransformResult(
    row={"email": "  John@EX.COM  ", "is_logon_disable": "false", "organization_id": "77"},
    errors=(),
    ...
)
```

**Что отдаёт следующей стадии (enrich):**

```
TransformResult(
    row={"email": "John@EX.COM", "is_logon_disable": False, "organization_id": 77},
    errors=(),
    ...
)
```

Нормализация описывается декларативно — одним YAML-файлом (`*.normalize.yaml`).
Компилятор `NormalizerDsl` превращает эту спецификацию в `CompiledNormalizeRules`,
которые `NormalizerCore` применяет к каждой записи.

**Файловая структура слоя:**

```
connector/domain/transform_dsl/
├── specs/
│   └── normalize.py          # NormalizeSpec, NormalizeBlock, NormalizeRule
├── compilers/
│   └── normalize.py          # NormalizerDsl, CompiledNormalizeRules
├── build_options.py          # NormalizeDslBuildOptions
└── loader.py                 # load_normalize_spec_for_dataset,
                              # load_normalize_build_options_for_dataset

connector/domain/dsl/
├── ops.py                    # Каталог операций (shared: map + normalize + enrich)
├── engine.py                 # TransformationEngine
├── registry.py               # OperationRegistry, register_core_ops
└── build_options.py          # BaseDslBuildOptions

datasets/
└── employees.normalize.yaml  # Пример DSL-конфига нормализации
```

---

## 🏗️ Архитектура слоя

```
datasets/registry.yml
        │
        │  (stage="normalize")
        ▼
load_normalize_spec_for_dataset()
        │
        ▼
NormalizeSpec (Pydantic)
  └── NormalizeBlock
        └── [NormalizeRule, ...]
              ├── field: str
              └── ops: [OperationCall, ...]
        │
        ▼
NormalizerDsl.compile()
  ├── _validate_ops_known()   (если fail_on_unknown_ops=True)
  └── CompiledNormalizeRules (frozen dataclass)
        ├── rules: tuple[NormalizeRule, ...]
        ├── on_error: str
        └── options: NormalizeDslBuildOptions
              │
              ▼
NormalizerCore._apply_rules()
  ├── for rule in rules:
  │     value = row[rule.field]
  │     result, issues = apply_ops(engine, value, rule.ops)
  │     row[rule.field] = result
  └── validate_sink_row/validate_sink_fields (если sink_spec задан)
```

| Компонент | Файл | Ответственность |
|-----------|------|-----------------|
| `NormalizeSpec` | `specs/normalize.py` | Pydantic-модель YAML-файла |
| `NormalizeBlock` | `specs/normalize.py` | Контейнер правил + глобальный `on_error` |
| `NormalizeRule` | `specs/normalize.py` | Одно поле + цепочка операций |
| `CompiledNormalizeRules` | `compilers/normalize.py` | Frozen-результат компиляции |
| `NormalizerDsl` | `compilers/normalize.py` | Компилятор spec → rules |
| `NormalizeDslBuildOptions` | `build_options.py` | Compile-policy (validate, strict) |
| `OperationRegistry` | `dsl/registry.py` | Реестр операций по имени |
| `TransformationEngine` | `dsl/engine.py` | Применение цепочек операций |
| `ops.py` | `dsl/ops.py` | Реализации всех 26 операций |

---

## 🔑 Ключевые абстракции

### NormalizeRule

**Файл:** `connector/domain/transform_dsl/specs/normalize.py`

Атомарное правило нормализации одного поля:

```python
class NormalizeRule(DslBaseModel):
    field: str                                    # Имя поля в row
    ops: list[OperationCall] = []                 # Цепочка операций
    op: str | None = None                         # Сокращение для одной операции
    args: dict[str, Any] | None = None            # Аргументы для op
    on_error: Literal["error", "warn"] = "error"  # Поведение при ошибке
```

**Сахар `op → ops`**: Pydantic `model_validator` автоматически оборачивает
`op + args` в `ops=[OperationCall(op=op, args=args or {})]`. После компиляции
всегда используется `ops`, `op` и `args` игнорируются.

| Поле | Тип | Обязательность | Описание |
|------|-----|----------------|----------|
| `field` | `str` | Да | Имя поля в `row` |
| `ops` | `list[OperationCall]` | Нет (дефолт `[]`) | Цепочка операций |
| `op` | `str \| None` | Нет | Краткая форма: одна операция |
| `args` | `dict \| None` | Нет | Аргументы для `op` |
| `on_error` | `"error" \| "warn"` | Нет (дефолт `"error"`) | Severity при ошибке |

### NormalizeBlock

**Файл:** `connector/domain/transform_dsl/specs/normalize.py`

Контейнер правил с глобальным `on_error`:

```python
class NormalizeBlock(DslBaseModel):
    on_error: Literal["error", "warn"] = "error"  # Дефолт для всех правил
    rules: list[NormalizeRule] = []
```

Поле `on_error` блока служит дефолтом при отсутствии `on_error` на правиле.
Но в текущей реализации каждое `NormalizeRule` имеет собственный `on_error`
(дефолт `"error"`), а `NormalizeBlock.on_error` используется при sink-валидации.

### NormalizeSpec

**Файл:** `connector/domain/transform_dsl/specs/normalize.py`

Корневая модель YAML-файла:

```python
class NormalizeSpec(DslBaseModel):
    dataset: str
    normalize: NormalizeBlock
```

Загружается через `load_normalize_spec_for_dataset(dataset)` → Pydantic валидирует
структуру и возвращает готовый объект или бросает `DslLoadError`.

### OperationCall

**Файл:** `connector/domain/dsl/specs/_base.py`

Атомарный вызов операции:

```python
@dataclass
class OperationCall:
    op: str          # Имя операции в реестре
    args: dict       # Именованные аргументы
```

---

## 🗂️ Модели данных

### CompiledNormalizeRules

**Файл:** `connector/domain/transform_dsl/compilers/normalize.py`

Результат компиляции — frozen dataclass:

```python
@dataclass(frozen=True)
class CompiledNormalizeRules:
    rules: tuple[NormalizeRule, ...]   # Иммутабельный кортеж правил
    on_error: str                      # Глобальный on_error (из NormalizeBlock)
    options: NormalizeDslBuildOptions  # Compile-policy
```

Иммутабелен после создания, безопасен для переиспользования между записями.
`NormalizerCore` держит ссылку на `CompiledNormalizeRules` через весь lifecycle runtime.

### NormalizeDslBuildOptions

**Файл:** `connector/domain/transform_dsl/build_options.py`

```python
@dataclass(frozen=True)
class NormalizeDslBuildOptions(BaseDslBuildOptions):
    validate_only_touched_fields: bool = False
```

Наследует от `BaseDslBuildOptions`:

```python
@dataclass(frozen=True)
class BaseDslBuildOptions:
    strict: bool = False
    fail_on_unknown_ops: bool = True
```

| Параметр | Тип | Дефолт | Описание |
|----------|-----|--------|----------|
| `strict` | `bool` | `False` | Режим строгой проверки (unknown keys → DslLoadError) |
| `fail_on_unknown_ops` | `bool` | `True` | DslLoadError если op не в реестре |
| `validate_only_touched_fields` | `bool` | `False` | Валидировать только поля, затронутые правилами |

**Важно:** Если `strict=True`, он принудительно выставляет `fail_on_unknown_ops=True`
даже если явно задано `False` — `build_options_from_mapping()` исправляет это автоматически.

#### `validate_only_touched_fields`

- `False` (дефолт): `validate_sink_row(row, sink_spec)` — проверяется вся строка
  целиком против sink-схемы. Все обязательные поля должны присутствовать.
- `True`: `validate_sink_fields(row, sink_spec, fields=touched_fields)` — проверяются
  только поля, к которым применялись правила нормализации. Остальные поля
  не затрагиваются (полезно если sink-проверка уже была в mapper-стадии).

---

## 📊 Ключевые методы и алгоритмы

### Каталог операций

Все операции зарегистрированы в `register_core_ops()` и доступны во всех DSL-стадиях:
map, normalize, enrich. `TransformationEngine.with_core_ops()` создаёт движок
с полным реестром 26 операций.

**Файл:** `connector/domain/dsl/ops.py`

**Сигнатура каждой операции:** `func(value: Any, **kwargs: Any) -> Any`

При исключении внутри `func` движок создаёт `DslIssue(code="DSL_OP_FAILED")` и
прерывает цепочку для текущего правила. При неизвестном имени операции — `DslIssue(code="DSL_OP_UNKNOWN")`.

---

#### Строковые операции

##### `trim`

```python
def op_trim(value: Any) -> str | None
```

Нормализует пробельные символы (коллапсирует множественные пробелы в один,
убирает ведущие/хвостовые) и возвращает `None` для пустых строк.

| Вход | Выход |
|------|-------|
| `"  John Doe  "` | `"John Doe"` |
| `"  "` | `None` |
| `None` | `None` |
| `"  a  b  "` | `"a b"` |
| `123` | `"123"` |

**Применение в normalize:** Используется для большинства строковых полей
(`email`, `first_name`, `last_name`, `phone`, `user_name`, `password`, и т.д.)
для очистки от артефактов CSV-парсинга.

```yaml
- field: email
  op: trim
```

---

##### `lower`

```python
def op_lower(value: Any) -> str | None
```

Приводит строку к нижнему регистру. `None` → `None`.

| Вход | Выход |
|------|-------|
| `"JOHN.DOE@EXAMPLE.COM"` | `"john.doe@example.com"` |
| `"MixedCase"` | `"mixedcase"` |
| `None` | `None` |

```yaml
- field: email
  ops:
    - op: trim
    - op: lower
```

---

##### `upper`

```python
def op_upper(value: Any) -> str | None
```

Приводит строку к верхнему регистру. `None` → `None`.

```yaml
- field: country_code
  op: upper
```

---

##### `to_string`

```python
def op_to_string(value: Any) -> str | None
```

Конвертирует значение в строку через `str()`, применяет `strip()`.
Пустая строка → `None`.

| Вход | Выход |
|------|-------|
| `42` | `"42"` |
| `True` | `"True"` |
| `"  "` | `None` |
| `None` | `None` |

---

#### Конвертация типов

##### `to_bool`

```python
def op_to_bool(value: Any) -> bool | None
```

Строгая конвертация в `bool`. Допустимые значения (регистронезависимо):
`"true"` → `True`, `"false"` → `False`. Любое другое значение — исключение.

| Вход | Выход | Примечание |
|------|-------|------------|
| `"true"` | `True` | |
| `"false"` | `False` | |
| `"True"` | `True` | case-insensitive |
| `"FALSE"` | `False` | case-insensitive |
| `True` | `True` | уже bool |
| `None` | `None` | |
| `"1"` | ❌ ValueError | Не допускается |
| `"yes"` | ❌ ValueError | Не допускается |

**Применение:** `is_logon_disable` — поле с типом `bool` в sink-схеме.

```yaml
- field: is_logon_disable
  op: to_bool
```

---

##### `to_int`

```python
def op_to_int(value: Any) -> int | None
```

Строгая конвертация в `int`. Бросает исключение для нечисловых строк,
пустых строк и `bool`-значений.

| Вход | Выход | Примечание |
|------|-------|------------|
| `"42"` | `42` | |
| `"  42  "` | `42` | trim входит |
| `42` | `42` | уже int |
| `None` | `None` | |
| `""` | ❌ ValueError | пустая строка |
| `"abc"` | ❌ ValueError | не число |
| `True` | ❌ ValueError | bool не int |

```yaml
- field: employee_count
  op: to_int
```

---

##### `to_float`

```python
def op_to_float(value: Any) -> float | None
```

Строгая конвертация в `float`. Аналогичное поведение с `to_int`,
но принимает вещественные числа.

| Вход | Выход |
|------|-------|
| `"3.14"` | `3.14` |
| `42` | `42.0` |
| `None` | `None` |
| `"abc"` | ❌ ValueError |
| `True` | ❌ ValueError |

---

##### `int_if_digits`

```python
def op_int_if_digits(value: Any) -> int | str | None
```

«Мягкая» конвертация: если строка состоит только из цифр — возвращает `int`,
иначе возвращает строку как есть. Пустая строка → `None`.

| Вход | Выход | Примечание |
|------|-------|------------|
| `"77"` | `77` | чистые цифры → int |
| `"ORG-42"` | `"ORG-42"` | есть нецифровые → str |
| `77` | `77` | уже int |
| `""` | `None` | пустая → None |
| `None` | `None` | |

**Применение:** `organization_id` — в источнике может быть как числом (`"77"`),
так и строкой (`"ORG-DEPT-01"`). `int_if_digits` сохраняет оба варианта корректно.

```yaml
- field: organization_id
  op: int_if_digits
```

---

#### Операции с дефолтами (fallback-генерация)

##### `default_uuid`

```python
def op_default_uuid(value: Any) -> Any
```

Возвращает `UUID4` в виде строки, если значение пустое (`None` или пустая строка),
иначе возвращает исходное значение без изменений.

| Вход | Выход |
|------|-------|
| `None` | `"f47ac10b-58cc-4372-a567-0e02b2c3d479"` (пример) |
| `"  "` | `"<uuid>"` |
| `"existing-id"` | `"existing-id"` |

```yaml
- field: avatar_id
  op: default_uuid
```

---

##### `default_prefixed_uuid`

```python
def op_default_prefixed_uuid(value: Any, *, prefix: str = "") -> Any
```

Возвращает `prefix + uuid_hex[:8]` если значение пустое. Иначе — исходное значение.

| Вход | Аргументы | Выход |
|------|-----------|-------|
| `None` | `prefix="emp-"` | `"emp-a1b2c3d4"` |
| `"existing"` | `prefix="emp-"` | `"existing"` |

```yaml
- field: external_id
  op: default_prefixed_uuid
  args:
    prefix: "emp-"
```

---

##### `default_password`

```python
def op_default_password(value: Any) -> Any
```

Генерирует случайный пароль вида `<буква a-f><uuid_hex>` если значение пустое.
Гарантирует, что пароль начинается с латинской буквы (удовлетворяет типичной
политике `startWithAlphabet`).

| Вход | Выход |
|------|-------|
| `None` | `"af47ac10b58cc4372a5670e02b2c3d479"` |
| `"  "` | `"<сгенерированный пароль>"` |
| `"secret123"` | `"secret123"` |

```yaml
- field: password
  op: default_password
```

---

##### `uuid`

```python
def op_uuid(value: Any) -> str
```

Всегда генерирует новый `UUID4`, игнорируя входное значение.
Используется для назначения идентификаторов при создании.

```yaml
- field: sync_id
  op: uuid
```

---

#### Сохранение значения

##### `copy`

```python
def op_copy(value: Any) -> Any
```

Возвращает значение без изменений. Полезна как явная документация того,
что поле не трансформируется, или как `noop` при цепочке.

```yaml
- field: raw_field
  op: copy
```

##### `const`

```python
def op_const(value: Any, *, value: Any) -> Any
```

Возвращает фиксированную константу из аргументов, игнорируя входное значение.

```yaml
- field: source_type
  op: const
  args:
    value: "employees"
```

---

#### Работа с несколькими значениями

##### `coalesce`

```python
def op_coalesce(values: Any, *, default: Any = None) -> Any
```

Возвращает первое непустое значение из списка. Принимает как список,
так и одиночное значение.

| Вход | Аргументы | Выход |
|------|-----------|-------|
| `[None, "", "john"]` | — | `"john"` |
| `[None, None]` | `default="unknown"` | `"unknown"` |
| `"value"` | — | `"value"` |
| `[None, None]` | — | `None` |

```yaml
# Используется в mapping (несколько sources), но доступна в normalize
- field: display_name
  op: coalesce
  args:
    default: "Unknown"
```

---

##### `concat`

```python
def op_concat(values: Any, *, sep: str = "") -> str | None
```

Склеивает список значений в строку через разделитель. `None`-элементы пропускаются.

| Вход | Аргументы | Выход |
|------|-----------|-------|
| `["John", "Doe"]` | `sep=" "` | `"John Doe"` |
| `["John", None, "Doe"]` | `sep=" "` | `"John Doe"` |
| `[]` | — | `None` |

---

##### `build_delimited_key`

```python
def op_build_delimited_key(values: Any, *, sep: str = "|", strict: bool = True) -> str | None
```

Собирает составной ключ из списка значений. В режиме `strict=True` (по умолчанию)
бросает исключение если хоть одно значение пустое. В `strict=False` — пропускает.

| Вход | Аргументы | Выход |
|------|-----------|-------|
| `["emp", "42"]` | `sep=":"` | `"emp:42"` |
| `["emp", None]` | `strict=True` | ❌ ValueError |
| `["emp", None]` | `strict=False` | `"emp"` |

---

##### `split`

```python
def op_split(value: Any, *, sep: str = ",") -> list[str] | None
```

Делит строку по разделителю, возвращает список строк.

| Вход | Аргументы | Выход |
|------|-----------|-------|
| `"a,b,c"` | — | `["a", "b", "c"]` |
| `"a;b"` | `sep=";"` | `["a", "b"]` |
| `None` | — | `None` |

---

#### Структурный парсинг

##### `split_name`

```python
def op_split_name(
    value: Any,
    *,
    fields: list[str],
    separator: str = " ",
    allow_comma_format: bool = False,
    max_parts: int | None = None,
) -> dict[str, str | None] | None
```

Универсально разбивает составное поле (ФИО и т.п.) по разделителю
и раскладывает части по именованным полям.

| Аргумент | Тип | Описание |
|----------|-----|----------|
| `fields` | `list[str]` | Имена выходных полей |
| `separator` | `str` | Разделитель (дефолт `" "`) |
| `allow_comma_format` | `bool` | `"Фамилия, Имя Отчество"` → `["Фамилия", "Имя", "Отчество"]` |
| `max_parts` | `int \| None` | Максимальное число частей |

| Вход | Аргументы | Выход |
|------|-----------|-------|
| `"Doe John M."` | `fields=["last","first","mid"]` | `{"last": "Doe", "first": "John", "mid": "M."}` |
| `"Doe, John M."` | `allow_comma_format=True` | `{"last": "Doe", "first": "John", "mid": "M."}` |
| `"Doe John"` | `fields=["last","first","mid"]` | `{"last": "Doe", "first": "John", "mid": None}` |

**Важно:** `split_name` используется в маппинге (один source → несколько targets).
В normalize её применяют реже, но технически доступна.

---

##### `extract_patterns`

```python
def op_extract_patterns(
    values: Any,
    *,
    patterns: dict[str, str],   # name → regex pattern
    split_pattern: str = r"[;|,]",
    keyed_prefixes: dict[str, str] | None = None,
) -> dict[str, str | None] | None
```

Извлекает значения по regex-паттернам из одного или нескольких строк.
Разбивает каждую строку на токены по `split_pattern`, затем применяет паттерны.
Кешированная компиляция regex через `@lru_cache`.

| Аргумент | Описание |
|----------|----------|
| `patterns` | Словарь `имя → regex` для каждого выходного поля |
| `split_pattern` | Regex разделителя токенов (дефолт: `;`, `\|`, `,`) |
| `keyed_prefixes` | `{"field": "prefix"}` — сначала ищет по prefix, затем по pattern |

---

##### `parse_kv_pairs`

```python
def op_parse_kv_pairs(
    value: Any,
    *,
    sep: str = ";",
    kv_sep: str = "=",
    keys: dict[str, str],   # target_field → source_key
) -> dict[str, str | None] | None
```

Парсит строку вида `"key=val;key2=val2"` и раскладывает по mapping.

| Аргумент | Описание |
|----------|----------|
| `sep` | Разделитель пар (дефолт `";"`) |
| `kv_sep` | Разделитель ключ-значение (дефолт `"="`) |
| `keys` | `{target_field: source_key}` — какой source_key куда класть |

| Вход | `keys` | Выход |
|------|--------|-------|
| `"org_id=77;tab=TAB-01"` | `{"org": "org_id", "tab": "tab"}` | `{"org": "77", "tab": "TAB-01"}` |

---

#### Regex-операции

##### `regex_extract`

```python
def op_regex_extract(value: Any, *, pattern: str, group: int = 0) -> str | None
```

Извлекает совпадение или группу из строки.

| Аргумент | Описание |
|----------|----------|
| `pattern` | Regex-паттерн |
| `group` | Номер группы (0 = всё совпадение) |

| Вход | Аргументы | Выход |
|------|-----------|-------|
| `"manager: 42"` | `pattern=r"\d+"` | `"42"` |
| `"no digits"` | `pattern=r"\d+"` | `None` |
| `None` | — | `None` |

```yaml
- field: manager_id
  op: regex_extract
  args:
    pattern: '\d+'
```

---

##### `regex_replace`

```python
def op_regex_replace(value: Any, *, pattern: str, repl: str) -> str | None
```

Заменяет все совпадения regex в строке.

| Вход | Аргументы | Выход |
|------|-----------|-------|
| `"+1-202-555-0100"` | `pattern=r"[-\s]", repl=""` | `"+12025550100"` |
| `None` | — | `None` |

---

#### Словарные операции

##### `map_dict`

```python
def op_map_dict(value: Any, *, mapping: dict[str, Any], casefold: bool = False) -> Any
```

Преобразует значение по таблице соответствий.
При `casefold=True` ключи нормализуются через `str.casefold()` для сравнения.
Кешированная нормализация через `@lru_cache`.

| Вход | `mapping` | Выход |
|------|-----------|-------|
| `"enabled"` | `{"enabled": True, "disabled": False}` | `True` |
| `"ENABLED"` | `{...}`, `casefold=True` | `True` |
| `"unknown"` | `{...}` | `None` |

```yaml
- field: status
  op: map_dict
  args:
    mapping:
      active: "ENABLED"
      inactive: "DISABLED"
    casefold: true
```

---

#### Meta/Link операции

##### `build_link_keys`

```python
def op_build_link_keys(
    value: Any,
    *,
    field: str,
    link_type: str = "match_key",
) -> dict[str, dict[str, str]] | None
```

Строит `link_keys` для последующих lookup-операций в enrich-стадии.
Используется в маппинге для подготовки ссылок на связанные объекты.

```yaml
# В mapping:
- target: link_keys
  source: manager
  op: build_link_keys
  args:
    field: manager
    link_type: match_key
```

---

##### `equals_path`

```python
def op_equals_path(value: Any, *, left: str, right: str) -> bool
```

Сравнивает два значения по dotted-путям внутри контекста (dict или объект).
Используется в сложных условных правилах enrich.

```yaml
- field: is_self_managed
  op: equals_path
  args:
    left: "manager_id"
    right: "personnel_number"
```

---

### Алгоритм компиляции: `NormalizerDsl.compile(spec)`

**Файл:** `connector/domain/transform_dsl/compilers/normalize.py`

```
1. Если fail_on_unknown_ops → _validate_ops_known(spec)
   → for rule in spec.normalize.rules:
       for op_call in rule.ops:
         if engine.registry.get(op_call.op) is None:
           raise DslLoadError(code="DSL_OP_UNKNOWN")

2. Иначе:
   return CompiledNormalizeRules(
       rules=tuple(spec.normalize.rules),
       on_error=spec.normalize.on_error,
       options=self.options,
   )

3. При любом исключении (кроме DslLoadError) → DslLoadError(code="NORMALIZE_DSL_COMPILE_INVALID")
```

Компиляция — лёгкая операция: spec → frozen tuple + on_error + options.
Никакой обработки значений, только структурная валидация.

### `load_normalize_spec_for_dataset(dataset)`

**Файл:** `connector/domain/transform_dsl/loader.py`

```
1. Загрузить registry.yml (_load_registry_or_raise)
2. Найти datasets[dataset]["normalize"] → путь к YAML
3. Прочитать YAML файл (_read_yaml_or_raise)
4. Pydantic NormalizeSpec.model_validate(raw) → NormalizeSpec
5. При ошибке → DslLoadError(code="NORMALIZE_DSL_SPEC_INVALID")
```

### `load_normalize_build_options_for_dataset(dataset)` — merge-приоритет

**Файл:** `connector/domain/transform_dsl/loader.py`

```
defaults (NormalizeDslBuildOptions())
    │
    ├── registry.build_options.base.*
    │       (перезаписывает defaults)
    │
    ├── registry.build_options.stages.normalize.*
    │       (перезаписывает base)
    │
    └── datasets[dataset].build_options.normalize.*
            (перезаписывает всё предыдущее)
```

**Пример в `registry.yml`:**

```yaml
build_options:
  base:
    fail_on_unknown_ops: true
  stages:
    normalize:
      validate_only_touched_fields: false

datasets:
  employees:
    build_options:
      normalize:
        validate_only_touched_fields: true   # ← перекрывает global
        strict: false
```

---

## 🔄 Взаимодействие с другими слоями

```
MapperEngine.map(record)
        ↓
TransformResult[dict]  ←──── row может содержать строки вместо bool/int
        │
        ▼
NormalizerEngine.normalize(result)
        │
        ├── load_normalize_spec_for_dataset() → NormalizeSpec
        ├── load_sink_spec_for_dataset()       → SinkSpec (для валидации)
        └── load_normalize_build_options_for_dataset() → NormalizeDslBuildOptions
        │
        ▼
TransformResult[dict]  ←──── поля приведены к нужным типам
        │
        ▼
EnrichStage.run()
```

**Shared DSL engine:** `TransformationEngine.with_core_ops()` создаётся один раз
в `NormalizerDsl.__init__()` и переиспользуется для всех записей. Реестр операций —
тот же, что у маппера и энрайчера.

**Sink spec:** `SinkSpec` загружается той же функцией что и в mapper (`load_sink_spec_for_dataset`).
Это единая схема ожидаемого выхода — один файл `*.sink.yaml` используется несколькими стадиями.

**registry.yml — центральный реестр:**

```yaml
datasets:
  employees:
    source:  employees.source.yaml
    mapping: employees.mapping.yaml
    sink:    employees.sink.yaml
    normalize: employees.normalize.yaml
    enrich:    employees.enrich.yaml
```

Все loader-функции ищут путь к файлу через `datasets[dataset][stage]`.

---

## 🔌 Контракты и границы

**DSL-пакет** (`connector/domain/transform_dsl/`) содержит только:
- Pydantic-модели (specs)
- Компилятор (`NormalizerDsl`)
- Loader-функции
- Build options

**Запрещённые импорты в DSL-слое:**
- `connector/infra/` — никакой инфраструктуры (CSV, httpx и т.д.)
- `connector/delivery/` — никакой доставки
- `connector/domain/transform/normalize/` — нет обратной зависимости (core → dsl, не наоборот)

**Инварианты слоя:**
- `connector/domain/transform_dsl/specs/normalize.py` — только Pydantic модели
- `connector/domain/transform_dsl/compilers/normalize.py` — только компиляция
- `connector/domain/dsl/ops.py` — чистые функции, нет зависимостей на domain
- `NormalizeDslBuildOptions` — compile-policy, не бизнес-правила датасета
- Loader не импортирует инфраструктуру (`connector/infra/`)
- Операции shared: добавление новой операции делает её доступной во всех стадиях

**Инварианты компилятора:**
- `CompiledNormalizeRules` — frozen после создания, безопасен для multi-thread
- Компилятор вызывается один раз при старте, не при каждой записи
- `NormalizerDsl` создаёт `TransformationEngine` только при инициализации

---

## 🛠️ HOW-TO

### Добавить правило нормализации для существующего поля

1. Открыть `datasets/employees.normalize.yaml`
2. Добавить правило в секцию `normalize.rules`:

```yaml
normalize:
  on_error: warn
  rules:
    # Уже существующие правила...

    # Новое правило:
    - field: department_code
      ops:
        - op: trim
        - op: upper
```

3. Убедиться что поле `department_code` описано в `employees.sink.yaml`
4. Запустить тесты: `pytest tests/unit/ -k employees`

---

### Добавить цепочку операций

```yaml
# Один op (краткая форма):
- field: email
  op: trim

# Несколько операций (полная форма):
- field: email
  ops:
    - op: trim
    - op: lower

# Операция с аргументами:
- field: status
  ops:
    - op: trim
    - op: map_dict
      args:
        mapping:
          active: "ENABLED"
          disabled: "DISABLED"
        casefold: true
```

---

### Изменить поведение при ошибке

По умолчанию `on_error: error` — ошибка в правиле → `row = None`.

```yaml
normalize:
  on_error: warn          # Дефолт для sink-валидации
  rules:
    - field: phone
      op: trim
      on_error: warn      # Ошибка → warning, row продолжает строиться

    - field: personnel_number
      op: trim
      # on_error: error   # Дефолт — ошибка → row = None
```

**Когда использовать `warn`:** Для необязательных полей, ошибка нормализации которых
не должна блокировать всю запись. Например, дополнительный телефон, который может
быть пустым или в нестандартном формате.

---

### Добавить новую операцию

1. **Реализовать функцию** в `connector/domain/dsl/ops.py`:

```python
def op_strip_prefix(value: Any, *, prefix: str) -> str | None:
    """
    Назначение:
        Убрать фиксированный префикс из начала строки.
    """
    if value is None:
        return None
    raw = str(value)
    if raw.startswith(prefix):
        return raw[len(prefix):]
    return raw
```

2. **Зарегистрировать** в `connector/domain/dsl/registry.py`:

```python
from connector.domain.dsl.ops import (
    # ... существующие ...
    op_strip_prefix,
)

def register_core_ops(registry: OperationRegistry) -> OperationRegistry:
    # ... существующие ...
    registry.register("strip_prefix", op_strip_prefix)
    return registry
```

3. **Использовать** в YAML:

```yaml
- field: personnel_number
  ops:
    - op: strip_prefix
      args:
        prefix: "EMP-"
```

4. **Написать тест** в `tests/unit/transform/test_dsl_ops.py`:

```python
def test_op_strip_prefix_removes_prefix() -> None:
    result = op_strip_prefix("EMP-001", prefix="EMP-")
    assert result == "001"

def test_op_strip_prefix_no_prefix() -> None:
    result = op_strip_prefix("001", prefix="EMP-")
    assert result == "001"

def test_op_strip_prefix_none() -> None:
    assert op_strip_prefix(None, prefix="EMP-") is None
```

> **Важно:** Новая операция автоматически становится доступной во всех трёх стадиях:
> mapping, normalize, enrich — они все используют `register_core_ops()`.

---

### Настроить compile-policy через registry.yml

```yaml
# datasets/registry.yml

build_options:
  base:
    strict: false
    fail_on_unknown_ops: true
  stages:
    normalize:
      validate_only_touched_fields: false

datasets:
  employees:
    normalize: employees.normalize.yaml
    build_options:
      normalize:
        validate_only_touched_fields: true   # Только затронутые поля
        strict: false
```

---

## 💡 Типичные сценарии

### Сценарий 1: Базовая нормализация строк

Большинство строковых полей требуют только `trim`:

```yaml
normalize:
  on_error: warn
  rules:
    - field: email
      op: trim
    - field: first_name
      op: trim
    - field: last_name
      op: trim
```

После маппинга `"  John  "` → после нормализации `"John"`.

---

### Сценарий 2: Нормализация булевого поля

```yaml
- field: is_logon_disable
  op: to_bool
```

Источник передаёт `"false"` (строка) → `to_bool` → `False` (bool Python).
Если источник передаёт `"1"` — ошибка `DSL_OP_FAILED` (to_bool строгий).

---

### Сценарий 3: «Мягкая» конвертация числа

```yaml
- field: organization_id
  op: int_if_digits
```

- `"77"` → `77` (int, если только цифры)
- `"ORG-ENG-01"` → `"ORG-ENG-01"` (строка, если есть нецифровые символы)

Это позволяет системе корректно работать, даже если организации имеют
как числовые, так и строковые идентификаторы.

---

### Сценарий 4: Цепочка операций

```yaml
- field: username
  ops:
    - op: trim
    - op: lower
```

Вход `"  JohnDoe  "` → trim → `"JohnDoe"` → lower → `"johndoe"`.

---

### Сценарий 5: Генерация пароля при отсутствии

```yaml
- field: password
  op: default_password
```

Если маппер вернул `password=None` (пустое поле в источнике) → `default_password`
генерирует безопасный случайный пароль. Если пароль задан в источнике — оставляет
как есть.

---

### Сценарий 6: Замена по таблице

```yaml
- field: account_type
  ops:
    - op: trim
    - op: lower
    - op: map_dict
      args:
        mapping:
          employee: "STAFF"
          contractor: "EXTERNAL"
          intern: "TRAINEE"
        casefold: true  # "Employee" → "employee" для поиска
```

---

## 📌 Важные детали

| Деталь | Описание |
|--------|----------|
| Операции shared | `ops.py` одинаковы для map, normalize и enrich — новая op доступна везде |
| Цепочка прерывается | При ошибке в одной op следующие op цепочки **не выполняются** |
| `on_error: warn` vs `error` | `warn` → запись продолжает строиться; `error` → `row = None` |
| `sink_spec` optional | Без `sink_spec` валидация не проводится; `NormalizerEngine.from_dataset()` всегда загружает sink |
| `validate_only_touched_fields` | `True` → проверяются только поля с правилами; `False` → вся строка |
| Порядок правил | Правила применяются последовательно в порядке YAML; изменение порядка может влиять на результат |
| Нет rollback | Если правило N упало, правила 0..N-1 уже применены; строка изменена частично → errors → `row=None` |
| `None` пропускается? | Нет — если поле `None`, операция всё равно вызывается. Большинство ops обрабатывают `None` → `None` |
| Реестр compile-time | Операции регистрируются при инициализации `NormalizerDsl`, не при каждом вызове |
| `@lru_cache` в ops | `extract_patterns` и `map_dict` кешируют компиляцию regex/mapping — hot-path оптимизация |

---

## 🧪 Тестовое покрытие

| Файл | Что тестирует |
|------|--------------|
| `tests/unit/transform/test_dsl_ops.py` | Отдельные операции: `map_dict casefold`, `trim`, `to_bool`, `int_if_digits` и другие |
| `tests/unit/transform/test_normalize_dsl.py` | `NormalizerDsl.compile()`, `NormalizeSpec` загрузка и валидация, `NormalizeDslBuildOptions` |
| `tests/integration/transform/test_dsl_build_options.py` | Merge build options, defaults, strict mode, unknown keys |
| `tests/unit/transform/test_pipeline_stage_contract.py` | `NormalizeStage` как участник pipeline |
| `tests/unit/transform/test_stage_factory.py` | Создание стадий через factory |
| `tests/unit/transform/test_mapping_dsl.py` | Операции через MapperEngine (shared ops registry) |
| `tests/e2e/pipelines/test_pipeline_container_e2e.py` | End-to-end, включая нормализацию |

**Операции покрыты через маппинг e2e**: большинство ops (trim, to_bool, int_if_digits)
проверяются через `test_employees_dsl_mapper_maps_record` в `test_mapping_dsl.py` —
та же `TransformationEngine` с тем же реестром.

---

## ❓ FAQ

**Почему `check_types=True` в normalize, но `check_types=False` в mapper?**

Mapper-стадия не занимается конвертацией типов — она только перекладывает значения
из источника в `row`. Строки остаются строками. Normalize-стадия — специально для
конвертации типов (`to_bool`, `to_int`, `int_if_digits`). Поэтому `validate_sink_row`
в normalize вызывается с `check_types=True`: к этому моменту типы уже должны быть
приведены и проверка имеет смысл. В mapper `check_types=False` — проверяются лишь
наличие полей, не их типы.

**Что если op вернул `None` для обязательного поля?**

Если операция вернула `None` для поля, помеченного в `SinkSpec` как `required: true`
и `nullable: false`, то `validate_sink_row` создаст `DslIssue`. Результат зависит
от `on_error` текущего правила: `"error"` → `row = None`, `"warn"` → warning в errors.

**Зачем нужен `NormalizeDslBuildOptions`, если параметров там мало?**

`NormalizeDslBuildOptions` — точка расширения compile-policy для normalizer-стадии.
Сейчас добавлен `validate_only_touched_fields`, который отсутствует у mapper/enrich.
Будущие параметры (например, `allow_unknown_fields`) добавляются сюда без изменения
базового класса.

**Почему `validate_only_touched_fields` важен?**

Когда mapper-стадия уже провела sink-валидацию всей строки (`check_types=False`),
а normalizer нормализует только часть полей — запускать полную валидацию снова
дорого и может давать ложные ошибки (поля ещё не заполнены энрайчером). С
`validate_only_touched_fields=True` normalize проверяет только те поля, которые
она сама трансформировала, не трогая остальные.

**Почему `to_bool` не принимает `"1"` и `"0"`?**

Строгость: `to_bool` принимает только `"true"`/`"false"`. Если источник даёт `"0"`,
используйте `map_dict: {"0": false, "1": true}` или кастомную операцию.
`validate_sink_row` с `check_types=True` считает `"0"` и `"1"` допустимыми bool (мягкая проверка).

**Можно ли использовать `trim + to_bool` в одном правиле?**

Да, через цепочку `ops`:
```yaml
- field: is_active
  ops:
    - op: trim
    - op: to_bool
```

**Почему операция всё равно вызывается для `None`-значений?**

Применяется — функция вызывается с `value=None`. Большинство ops сразу делают
`if value is None: return None`. Если операция должна заменить `None` на дефолт —
используйте `default_uuid`, `default_password`, `coalesce`.

**Что если поле отсутствует в `row` (не задано в маппинге)?**

`normalized_values.get(rule.field)` вернёт `None`. Операция будет вызвана с `None`.
Поле будет записано обратно. Если операция бросает исключение — `DSL_OP_FAILED`.

**Как добавить операцию, специфичную только для normalize (не для map/enrich)?**

Технически нельзя — реестр shared. Можно создать отдельный `OperationRegistry` и
передать `NormalizerDsl(engine=TransformationEngine(custom_registry))`, но это
нарушит стандартную DI-сборку. Рекомендуется: регистрировать все ops в core_ops,
документировать какие предназначены для каких стадий.

**Чем отличается `on_error` в `NormalizeBlock` от `on_error` в `NormalizeRule`?**

`NormalizeBlock.on_error` применяется при sink-валидации (нет привязки к конкретному полю).
`NormalizeRule.on_error` применяется к ошибкам конкретного правила. Правило может
переопределить блоковый дефолт индивидуально.

---

## 🔗 Связанные документы

| Документ | Описание |
|----------|---------|
| [normalizer-core.md](normalizer-core.md) | Core-логика: NormalizerCore, NormalizerEngine, TransformResult, pipeline |
| [mapper-dsl.md](../mapper/mapper-dsl.md) | DSL-спецификации mapper-слоя (SourceSpec, MappingSpec, SinkSpec) |
| [docs/dev/layers/dsl/dsl-engine.md](../dsl/dsl-engine.md) | TransformationEngine, операции, OperationRegistry |
| [docs/dev/layers/dsl/dsl-specs.md](../dsl/dsl-specs.md) | Базовые DSL-абстракции (DslBaseModel, OperationCall) |
| `datasets/employees.normalize.yaml` | Эталонный пример normalize-спецификации |
| `datasets/registry.yml` | Центральный реестр датасетов |

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-03-01 | Создан документ — DSL-спецификации normalizer-слоя | xORex-LC |
