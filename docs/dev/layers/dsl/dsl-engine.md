# DSL Engine

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

**Назначение**: Универсальный stage-agnostic движок трансформаций: регистрирует именованные операции, последовательно применяет их к значениям, собирает диагностику

**Ключевая ответственность**:
- Хранение и выдача операций DSL по имени (реестр)
- Последовательное применение цепочки операций к значению (движок)
- Фиксация ошибок runtime как `DslIssue` с fail-fast семантикой
- Предоставление 25 базовых операций для стадий mapping/normalize/enrich

**Расположение в кодовой базе**:
- `connector/domain/dsl/engine.py` — движок трансформаций
- `connector/domain/dsl/registry.py` — реестр операций
- `connector/domain/dsl/ops.py` — реализация базовых операций
- `connector/domain/dsl/helpers.py` — convenience wrapper

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
dsl/
├── registry.py    # 110 строк: OperationRegistry + register_core_ops()
├── engine.py      #  83 строки: TransformationEngine + EngineResult
├── ops.py         # 477 строк: 25 функций-операций
└── helpers.py     #  26 строк: apply_ops() convenience wrapper
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [DSL Engine Class Diagram](../../../uml/dsl/dsl_engine_class.png) | Структура Engine, Registry, Operation |
| Activity | [Apply Flow](../../../uml/dsl/dsl_engine_activity.png) | Алгоритм применения операций |

**PlantUML исходники**: `docs/uml/dsl/*.puml`

> **Примечание**: UML диаграммы находятся в процессе обновления.

### 🎭 Применённые паттерны

#### Паттерн 1: Registry Pattern

**Где применяется**: `OperationRegistry` как словарь `name → Operation`

**Реализация в коде**:
- **Registry**: `OperationRegistry` в `connector/domain/dsl/registry.py`
- **Entry**: `Operation` (frozen dataclass: `name` + `func`)
- **Bootstrap**: `register_core_ops()` регистрирует все 25 базовых операций

**Пример использования**:
```python
registry = OperationRegistry()
register_core_ops(registry)

# Получить операцию по имени
op = registry.get("trim")       # Operation | None
op = registry.require("trim")   # Operation (raises KeyError)

# Применить напрямую через реестр
result = registry.apply("trim", "  hello  ")  # → "hello"
```

**Зачем**: Операции определяются один раз, используются повсюду; легко добавить новую операцию без изменения движка

#### Паттерн 2: Pipeline Pattern (Sequential Apply)

**Где применяется**: `TransformationEngine.apply()` — последовательное применение операций

**Реализация в коде**:
- **Engine**: `TransformationEngine` в `connector/domain/dsl/engine.py`
- **Result**: `EngineResult` (frozen dataclass: `value` + `issues`)

**Пример использования**:
```python
engine = TransformationEngine(registry)
result = engine.apply("  Hello World  ", [
    OperationCall(op="trim"),
    OperationCall(op="lower"),
])
# result.value == "hello world"
# result.issues == ()
```

**Зачем**: Единообразная обработка цепочек операций с fail-fast на первой ошибке; отделение исполнения от описания

#### Паттерн 3: Factory Method

**Где применяется**: `TransformationEngine.with_core_ops()` — быстрое создание движка

**Реализация в коде**:
- `TransformationEngine.with_core_ops()` в `connector/domain/dsl/engine.py` line 36

**Пример использования**:
```python
# Вместо ручного создания реестра
engine = TransformationEngine.with_core_ops()
result = engine.apply(value, ops)
```

**Зачем**: Сокращает boilerplate при типичном использовании (создание реестра + регистрация + создание движка → одна строка)

### Диаграмма зависимостей

```
[OperationCall]  (из specs.py)
       ↓
[OperationRegistry] ← register_core_ops() ← [ops.py: 25 функций]
       ↓
[TransformationEngine]
       ↓
[EngineResult] → { value, issues: tuple[DslIssue, ...] }
       ↓
[helpers.apply_ops()] — convenience wrapper
```

---

## 🔑 Ключевые абстракции

### Основные классы

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
| `Operation` | Immutable описание одной зарегистрированной операции | — (frozen dataclass: `name`, `func`) |
| `OperationRegistry` | Хранит операции DSL и выдаёт их по имени | `register()`, `get()`, `require()`, `apply()` |
| `TransformationEngine` | Применяет цепочку операций к значению | `apply()`, `with_core_ops()` |
| `EngineResult` | Результат применения операций | — (frozen dataclass: `value`, `issues`) |

### Вспомогательные функции

| Функция | Роль | Расположение |
|---------|------|-------------|
| `register_core_ops()` | Регистрирует 25 базовых операций в реестре | `registry.py` line 51 |
| `apply_ops()` | Convenience wrapper: engine.apply() → (value, issues) | `helpers.py` line 15 |

---

## 🗂️ Модели данных

### Dataclass: `Operation`

**Назначение**: Описание зарегистрированной операции (имя + функция)

**Структура**:
```python
@dataclass(frozen=True)
class Operation:
    name: str              # Имя операции (напр. "trim", "lower")
    func: OperationFunc    # Callable[..., Any]
```

**Lifecycle**:
1. **Создание**: В `OperationRegistry.register()` — из имени и функции
2. **Хранение**: Внутри `OperationRegistry._ops` (dict)
3. **Использование**: `TransformationEngine.apply()` вызывает `op.func(value, **args)`

**Инварианты**:
- `frozen=True` — операция не изменяется после создания
- `func` — чистая функция (no side effects)

---

### Dataclass: `EngineResult`

**Назначение**: Результат применения цепочки операций к значению

**Структура**:
```python
@dataclass(frozen=True)
class EngineResult:
    value: Any                              # Итоговое значение после всех операций
    issues: tuple[DslIssue, ...] = ()       # Диагностика (ошибки/предупреждения)
```

**Создание и использование**:
```python
# Создаётся в TransformationEngine.apply()
result = engine.apply("hello", [OperationCall(op="upper")])

# Использование
if result.issues:
    # Есть ошибки — value может быть промежуточным
    for issue in result.issues:
        handle_issue(issue)
else:
    # Успех — value содержит финальный результат
    process(result.value)
```

**Lifecycle**:
1. **Создание**: В `TransformationEngine.apply()` line 82 — после прохода по всем операциям
2. **Трансформации**: Нет — `frozen=True`
3. **Потребление**: Передаётся в `diagnostics.append_dsl_issue()` для перевода issues → `DiagnosticItem`, или распаковывается через `apply_ops()` в `(value, list[DslIssue])`

**Инварианты**:
- Если `issues` пустой — `value` содержит успешный результат всех операций
- Если `issues` непустой — `value` содержит промежуточное значение (до первой ошибки)
- `issues` содержит максимум 1 элемент (fail-fast на первой ошибке)

---

## 🎯 DSL

### Каталог операций (25 Core Operations)

Все операции регистрируются в `register_core_ops()` (`registry.py` line 51).

#### Type Conversion (преобразование типов)

| Op | Описание | Вход | Выход | None-safe | Ошибки |
|----|----------|------|-------|-----------|--------|
| `to_int` | Строгое преобразование в int | scalar | `int \| None` | ✅ → None | `ValueError` на bool, пустую строку |
| `to_float` | Строгое преобразование в float | scalar | `float \| None` | ✅ → None | `ValueError` на bool, пустую строку |
| `to_bool` | Строгое: только "true"/"false" | scalar | `bool \| None` | ✅ → None | `ValueError` на невалидные значения |
| `to_string` | В строку + trim, пустая → None | scalar | `str \| None` | ✅ → None | — |
| `int_if_digits` | В int если число, иначе строка | scalar | `int \| str \| None` | ✅ → None | — |

**YAML пример**:
```yaml
ops:
  - op: to_int        # "42" → 42
  - op: to_string     # 42 → "42"
  - op: int_if_digits # "42" → 42, "abc" → "abc"
```

#### String (строковые операции)

| Op | Описание | Вход | Выход | None-safe | Параметры |
|----|----------|------|-------|-----------|-----------|
| `trim` | Нормализация пробелов, пустая → None | str | `str \| None` | ✅ → None | — |
| `lower` | Приведение к нижнему регистру | str | `str \| None` | ✅ → None | — |
| `upper` | Приведение к верхнему регистру | str | `str \| None` | ✅ → None | — |
| `concat` | Склейка списка значений в строку | list | `str \| None` | ✅ (пропускает None элементы) | `sep: str = ""` |
| `split` | Разделение строки по разделителю | str | `list[str] \| None` | ✅ → None | `sep: str = ","` |
| `split_name` | Разбор составного поля на части | str | `dict[str, str \| None] \| None` | ✅ → None | `fields`, `separator`, `allow_comma_format`, `max_parts` |

**YAML пример**:
```yaml
ops:
  - op: trim                                     # "  hello  " → "hello"
  - op: lower                                    # "HELLO" → "hello"
  - op: concat
    args: { sep: " " }                           # ["John", "Doe"] → "John Doe"
  - op: split_name
    args: { fields: [last, first], separator: " " }  # "Doe John" → {last: "Doe", first: "John"}
```

#### UUID (генерация идентификаторов)

| Op | Описание | Вход | Выход | None-safe | Параметры |
|----|----------|------|-------|-----------|-----------|
| `uuid` | Новый UUID v4 | Any (игнорируется) | `str` | — | — |
| `default_uuid` | UUID если значение пустое | Any | `Any \| str` | ✅ → UUID | — |
| `default_prefixed_uuid` | Префикс+UUID(8) если пустое | Any | `Any \| str` | ✅ → prefix+hex8 | `prefix: str = ""` |

**YAML пример**:
```yaml
ops:
  - op: default_uuid                              # None → "a1b2c3d4-..."
  - op: default_prefixed_uuid
    args: { prefix: "EMP-" }                      # None → "EMP-a1b2c3d4"
```

#### Value Selection (выбор значения)

| Op | Описание | Вход | Выход | None-safe | Параметры |
|----|----------|------|-------|-----------|-----------|
| `copy` | Возвращает значение без изменений | Any | Any | ✅ → None | — |
| `const` | Возвращает константу из args | Any (игнорируется) | Any | — | `value: Any` (обязательный) |
| `coalesce` | Первое непустое значение из списка | list/scalar | Any | ✅ → default | `default: Any = None` |

**YAML пример**:
```yaml
ops:
  - op: copy                                       # passthrough
  - op: const
    args: { value: "active" }                      # → "active" (всегда)
  - op: coalesce
    args: { default: "N/A" }                       # [None, "", "hello"] → "hello"
```

#### Key Building (построение ключей)

| Op | Описание | Вход | Выход | None-safe | Параметры |
|----|----------|------|-------|-----------|-----------|
| `build_delimited_key` | Составной ключ через разделитель | list | `str \| None` | strict: raise / soft: None | `sep: str = "\|"`, `strict: bool = True` |
| `build_link_keys` | Link-ключи для FK lookup | scalar | `dict \| None` | ✅ → None | `field: str`, `link_type: str = "match_key"` |

**YAML пример**:
```yaml
ops:
  - op: build_delimited_key
    args: { sep: "|", strict: true }               # ["A", "B"] → "A|B"
  - op: build_link_keys
    args: { field: "manager", link_type: "match_key" }  # "KEY123" → {manager: {match_key: "KEY123"}}
```

#### Pattern / Regex (паттерны)

| Op | Описание | Вход | Выход | None-safe | Параметры |
|----|----------|------|-------|-----------|-----------|
| `extract_patterns` | Извлечь значения по regex из набора строк | list/str | `dict[str, str \| None] \| None` | ✅ → None | `patterns`, `split_pattern`, `keyed_prefixes` |
| `regex_extract` | Извлечь группу regex | str | `str \| None` | ✅ → None | `pattern: str`, `group: int = 0` |
| `regex_replace` | Заменить по regex | str | `str \| None` | ✅ → None | `pattern: str`, `repl: str` |

**YAML пример**:
```yaml
ops:
  - op: regex_extract
    args: { pattern: "\\d+", group: 0 }            # "emp-42-test" → "42"
  - op: regex_replace
    args: { pattern: "[^\\d]", repl: "" }           # "emp-42-test" → "42"
  - op: extract_patterns
    args:
      patterns:
        phone: "\\+?\\d[\\d\\-]{6,}"
        email: "[\\w.]+@[\\w.]+"
```

#### Parsing (разбор структурированных данных)

| Op | Описание | Вход | Выход | None-safe | Параметры |
|----|----------|------|-------|-----------|-----------|
| `parse_kv_pairs` | Разобрать "key=val;key2=val2" | str | `dict[str, str \| None] \| None` | ✅ → None | `sep`, `kv_sep`, `keys` |
| `map_dict` | Маппинг через словарь | scalar | Any | ✅ → None | `mapping: dict`, `casefold: bool = False` |

**YAML пример**:
```yaml
ops:
  - op: parse_kv_pairs
    args:
      sep: ";"
      kv_sep: "="
      keys: { phone: "tel", mail: "email" }        # "tel=123;email=a@b" → {phone: "123", mail: "a@b"}
  - op: map_dict
    args:
      mapping: { "M": "male", "F": "female" }
      casefold: true                                # "m" → "male"
```

#### Comparison (сравнение)

| Op | Описание | Вход | Выход | None-safe | Параметры |
|----|----------|------|-------|-----------|-----------|
| `equals_path` | Сравнить два вложенных значения по path | dict/obj | `bool` | — | `left: str`, `right: str` |

**YAML пример**:
```yaml
ops:
  - op: equals_path
    args: { left: "source.id", right: "target.id" }  # {source: {id: 1}, target: {id: 1}} → true
```

### Где определены операции

- **Путь к реализации**: `connector/domain/dsl/ops.py`
- **Внешняя зависимость**: `normalize_text()` из `connector/domain/transform/common` (используется в `op_trim`)
- **Регистрация**: `register_core_ops()` в `connector/domain/dsl/registry.py` line 51

---

## 📊 Ключевые методы и алгоритмы

### Обзор сложных методов

| Метод | Строк | Сложность | Назначение |
|-------|-------|-----------|------------|
| `TransformationEngine.apply()` | 25 | O(k) | Последовательное применение k операций к значению |
| `register_core_ops()` | 59 | O(1) | Регистрация 25 базовых операций |
| `op_extract_patterns()` | 43 | O(c×t×p) | Извлечение паттернов из набора строк |
| `op_split_name()` | 32 | O(n) | Разбор составного имени на поля |
| `op_build_delimited_key()` | 35 | O(n) | Построение составного ключа |

---

### Метод: `TransformationEngine.apply()`

**Расположение**: `connector/domain/dsl/engine.py` line 48

**Сигнатура**:
```python
def apply(self, value: Any, ops: Iterable[OperationCall]) -> EngineResult:
```

**Назначение**: Последовательно применить цепочку DSL-операций к значению, собирая диагностику. Это центральный метод всего DSL engine.

---

**Алгоритм** (pseudocode с номерами строк):

```
1. Init (line 58-59)
   current = value
   issues = []

2. FOR EACH op_call IN ops (line 60):

   2a. Lookup (line 61)
       op = registry.get(op_call.op)

   2b. Unknown op? (lines 62-70)
       IF op is None:
           → append DslIssue(code="DSL_OP_UNKNOWN")
           → BREAK (fail-fast)

   2c. Execute (lines 71-72)
       TRY: current = op.func(current, **op_call.args)

   2d. Execution error? (lines 73-81)
       EXCEPT Exception:
           → append DslIssue(code="DSL_OP_FAILED", message=str(exc))
           → BREAK (fail-fast)

3. Return (line 82)
   RETURN EngineResult(value=current, issues=tuple(issues))
```

**ASCII Flow**:

```
Input value
  ↓
[op_1] → {OK?} ─No→ DslIssue("DSL_OP_UNKNOWN" или "DSL_OP_FAILED") → STOP
  ↓ Yes
[op_2] → {OK?} ─No→ DslIssue → STOP
  ↓ Yes
 ...
[op_k] → {OK?} ─No→ DslIssue → STOP
  ↓ Yes
EngineResult(value=final, issues=())
```

---

**Временная сложность**:
- **Best case**: O(k) — все k операций успешны, каждая O(1)
- **Worst case**: O(k × C_op) — k операций, C_op = стоимость самой дорогой операции
- k = количество операций в цепочке (обычно 1-5)

**Инварианты**:
1. **Fail-fast**: При первой ошибке дальнейшие операции не выполняются
2. **Максимум 1 issue**: `issues` содержит 0 или 1 элемент
3. **Не мутирует вход**: Исходное `value` не изменяется
4. **Детерминизм**: Для одинаковых входов — одинаковый результат (кроме `uuid`)

**Edge cases**:
1. **Пустой список ops**: Возвращает `EngineResult(value=input, issues=())`
2. **None input**: Передаётся в первую операцию; поведение зависит от операции
3. **Неизвестная операция**: `DSL_OP_UNKNOWN` issue, value = промежуточный результат

**Связанные методы**:
- `OperationRegistry.get()` line 37 — lookup операции
- `apply_ops()` в `helpers.py` line 15 — convenience wrapper

---

### Метод: `register_core_ops()`

**Расположение**: `connector/domain/dsl/registry.py` line 51

**Сигнатура**:
```python
def register_core_ops(registry: OperationRegistry) -> OperationRegistry:
```

**Назначение**: Зарегистрировать 25 базовых операций DSL в переданном реестре.

**Алгоритм**: Последовательно импортирует все функции из `ops.py` и регистрирует каждую под именем:

```
1. Import (lines 56-82)
   Lazy import всех 25 функций из connector.domain.dsl.ops

2. Register (lines 84-108)
   Для каждой функции: registry.register("имя", op_функция)
   Порядок: trim, lower, upper, to_int, to_float, to_bool, to_string,
            int_if_digits, uuid, default_uuid, default_prefixed_uuid,
            copy, const, coalesce, concat, build_delimited_key,
            extract_patterns, split, split_name, regex_extract, regex_replace,
            parse_kv_pairs, map_dict, build_link_keys, equals_path

3. Return (line 109)
   RETURN registry (для цепочки вызовов)
```

**Инварианты**:
- Lazy import: `ops.py` импортируется только при вызове `register_core_ops()`, не при import модуля
- Функция идемпотентна: повторный вызов перезаписывает операции тем же набором

---

## 🛠️ Как расширять

### Добавить новую DSL операцию

1. **Создать функцию операции** в `connector/domain/dsl/ops.py`:
   ```python
   def op_my_operation(value: Any, *, param1: str, param2: int = 0) -> str | None:
       """
       Назначение:
           Описание операции.
       """
       if value is None:
           return None
       # Логика трансформации
       return transformed_value
   ```

   **Контракт функции**:
   - Первый позиционный аргумент — текущее значение (`value`)
   - Именованные аргументы — параметры из `OperationCall.args`
   - Возвращает трансформированное значение
   - `None` input → `None` output (рекомендуемое поведение)
   - Исключения фиксируются движком как `DSL_OP_FAILED`

2. **Добавить import в `register_core_ops()`** (`connector/domain/dsl/registry.py` line 56):
   ```python
   from connector.domain.dsl.ops import (
       ...,
       op_my_operation,
   )
   ```

3. **Зарегистрировать операцию** (после line 108):
   ```python
   registry.register("my_operation", op_my_operation)
   ```

4. **Использовать в YAML конфигурации**:
   ```yaml
   ops:
     - op: my_operation
       args:
         param1: "value"
         param2: 42
   ```

### Создать движок с дополнительными операциями (для слоя)

Если слою нужны операции, не входящие в базовый набор:

```python
from connector.domain.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.dsl.engine import TransformationEngine

# Создать реестр с базовыми + своими операциями
registry = OperationRegistry()
register_core_ops(registry)
registry.register("my_layer_op", my_layer_op_func)

# Создать движок
engine = TransformationEngine(registry)
```

### Добавить новый helper

Если нужен новый convenience wrapper, добавить в `connector/domain/dsl/helpers.py`:

```python
def my_helper(engine: TransformationEngine, ...) -> ...:
    result = engine.apply(...)
    # Дополнительная обработка
    return ...
```

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| **Mapping** | Использует engine | `MapperDsl.__init__(registry, engine)` | Применение ops к полям mapping |
| **Normalize** | Использует engine | `NormalizerDsl.__init__(registry, engine)` | Применение ops к полям normalization |
| **Enrich** | Использует engine + registry | `EnricherDsl.__init__(registry, providers)` + `apply_ops()` | Трансформация enriched значений |
| **Match** | **Не использует** engine | — | Match компилирует правила без ops |
| **Resolve** | **Не использует** engine | — | Resolve компилирует policies без ops |
| **Cache** | Использует косвенно | Projection ops в `CacheSyncSpec` | Трансформация при sync (через projection) |

**Важно**: Match и Resolve слои работают только с DSL-спецификациями (`specs.py`) и build options (`build_options.py`), но не используют `TransformationEngine`. Их DSL-компиляторы строят правила (rules/policies), а не цепочки операций.

---

## 🔌 Контракты и границы

### Контракт функции-операции

Каждая операция в `ops.py` обязана следовать контракту:

```python
def op_xxx(value: Any, *, named_arg: Type = default, **_: Any) -> ReturnType:
    """
    - Первый аргумент: текущее значение pipeline (позиционный)
    - Именованные аргументы: из OperationCall.args (YAML)
    - Возврат: трансформированное значение
    - На None: рекомендуется возвращать None (null-safe)
    - На ошибку: поднять исключение (движок поймает как DSL_OP_FAILED)
    """
```

### Контракт движка

```python
# TransformationEngine.apply() гарантирует:
# 1. Не мутирует входное значение
# 2. Возвращает EngineResult (всегда, без исключений)
# 3. issues пустой → value содержит финальный результат
# 4. issues непустой → value содержит промежуточное значение
# 5. Максимум 1 issue (fail-fast)
```

### Границы слоёв

**Разрешенные зависимости**:
- ✅ `engine.py` → `registry.py` (import OperationRegistry)
- ✅ `engine.py` → `specs.py` (import OperationCall)
- ✅ `engine.py` → `issues.py` (import DslIssue, DslSeverity)
- ✅ `ops.py` → `connector.domain.transform.common` (import normalize_text)
- ✅ `helpers.py` → `engine.py`, `specs.py`, `issues.py`

**Запрещенные зависимости**:
- ❌ `engine.py` → `loader.py` — engine не знает о YAML загрузке
- ❌ `ops.py` → `connector/infra/*` — операции не обращаются к инфраструктуре
- ❌ `registry.py` → `engine.py` — registry не зависит от engine (обратная зависимость)

**Единственная внешняя зависимость**: `ops.py` → `normalize_text()` из `connector.domain.transform.common`

---

## 💡 Типичные сценарии

### Сценарий 1: Trim + Lower для нормализации email

**Задача**: Привести email к единообразному виду

**Решение**:
```python
engine = TransformationEngine.with_core_ops()
result = engine.apply("  John.Doe@COMPANY.COM  ", [
    OperationCall(op="trim"),
    OperationCall(op="lower"),
])
# result.value == "john.doe@company.com"
# result.issues == ()
```

**В YAML**:
```yaml
mapping:
  rules:
    - target: email
      source: rawEmail
      ops:
        - op: trim
        - op: lower
```

### Сценарий 2: Coalesce из нескольких источников

**Задача**: Взять первое непустое значение из нескольких полей

**Решение**:
```python
result = engine.apply(
    [None, "", "john.doe@company.com"],
    [OperationCall(op="coalesce", args={"default": "unknown@none"})],
)
# result.value == "john.doe@company.com"
```

**В YAML**:
```yaml
mapping:
  rules:
    - target: email
      sources: [email, mail, userPrincipalName]
      ops:
        - op: coalesce
          args: { default: "unknown@none" }
        - op: trim
        - op: lower
```

### Сценарий 3: Построение составного match_key

**Задача**: Построить ключ идентификации сотрудника из нескольких полей

**Решение**:
```python
result = engine.apply(
    ["DOE", "JOHN", "12345"],
    [OperationCall(op="build_delimited_key", args={"sep": "|", "strict": True})],
)
# result.value == "DOE|JOHN|12345"
```

**В YAML**:
```yaml
mapping:
  rules:
    - target: match_key
      sources: [last_name, first_name, personnel_number]
      ops:
        - op: upper
        - op: build_delimited_key
          args: { sep: "|", strict: true }
```

### Сценарий 4: Обработка ошибки неизвестной операции

**Задача**: Понять поведение при опечатке в имени операции

**Решение**:
```python
result = engine.apply("hello", [
    OperationCall(op="trim"),
    OperationCall(op="typo_op"),   # ← несуществующая операция
    OperationCall(op="upper"),     # ← НЕ выполнится (fail-fast)
])
# result.value == "hello"  (результат после trim, до ошибки)
# result.issues == (DslIssue(code="DSL_OP_UNKNOWN", message="Unknown operation 'typo_op'"),)
```

---

## 📌 Важные детали

### Особенности реализации

- **Lazy import ops**: `register_core_ops()` импортирует `ops.py` только при вызове (line 56), а не при import `registry.py`. Это позволяет использовать registry без загрузки всех операций
- **`**_: Any` в операциях**: Большинство операций принимают `**_` для игнорирования неожиданных аргументов из YAML (forward-compatibility)
- **`normalize_text` в `op_trim`**: Единственная операция, зависящая от внешнего модуля (`connector.domain.transform.common`). Нормализует пробелы (multiple → single, leading/trailing removed) и конвертирует пустую строку в None

### 🚨 Failure Modes

| Исключение | Условие возникновения | Поведение системы | Как обработать |
|------------|----------------------|-------------------|---------------|
| `DSL_OP_UNKNOWN` (DslIssue) | Операция не найдена в реестре | `engine.apply()` line 63: fail-fast, возвращает промежуточный value | Проверить имя операции в YAML конфигурации, сверить с каталогом |
| `DSL_OP_FAILED` (DslIssue) | Операция подняла исключение | `engine.apply()` line 74: fail-fast, message=str(exc) | Проверить входные данные и аргументы операции в YAML |
| `KeyError` | `registry.require()` для несуществующей операции | Поднимает `KeyError(name)` | Использовать `registry.get()` для безопасного lookup |
| `ValueError` в `op_to_int` | Boolean input или пустая строка | Исключение ловится движком → `DSL_OP_FAILED` | Добавить `to_string` перед `to_int` или проверить входные данные |
| `ValueError` в `op_build_delimited_key` | None/пустой элемент при `strict=True` | Исключение ловится движком → `DSL_OP_FAILED` | Использовать `strict: false` или обеспечить непустые значения |

### ⚠️ Инварианты системы

1. **Инвариант: Операции — чистые функции**
   - **Что**: Операции не имеют side effects, не обращаются к IO, не мутируют входы
   - **Почему важно**: Предсказуемость, тестируемость, повторяемость результатов
   - **Исключение**: `op_uuid`, `op_default_uuid`, `op_default_prefixed_uuid` генерируют случайные значения

2. **Инвариант: Fail-fast на первой ошибке**
   - **Что**: При ошибке в одной операции последующие не выполняются
   - **Почему важно**: Предотвращает каскадные ошибки от невалидных промежуточных значений
   - **Где проверяется**: `engine.py` lines 70, 81 — `break` после append issue

3. **Инвариант: EngineResult всегда возвращается**
   - **Что**: `apply()` никогда не поднимает исключений, всегда возвращает `EngineResult`
   - **Почему важно**: Вызывающий код не должен оборачивать apply() в try/except
   - **Где проверяется**: `engine.py` lines 73-81 — `except Exception` ловит всё

4. **Инвариант: Реестр не зависит от движка**
   - **Что**: `OperationRegistry` можно использовать без `TransformationEngine` (через `.apply()`)
   - **Почему важно**: Слои могут использовать реестр напрямую без создания движка
   - **Где проверяется**: `registry.py` line 46 — `apply()` метод реестра

### ⏱️ Performance заметки

**Стоимость операций**:

| Операция | Сложность | Примечание |
|----------|-----------|------------|
| `trim`, `lower`, `upper`, `copy`, `const` | O(1) | Тривиальные строковые операции |
| `to_int`, `to_float`, `to_bool`, `to_string` | O(1) | Парсинг одного значения |
| `coalesce`, `concat` | O(n) | n = количество элементов в списке |
| `build_delimited_key` | O(n) | n = количество элементов в списке |
| `split`, `split_name` | O(n) | n = длина строки |
| `regex_extract`, `regex_replace` | O(n) | n = длина строки (regex) |
| `extract_patterns` | O(c×t×p) | c = candidates, t = tokens, p = patterns |
| `parse_kv_pairs` | O(n) | n = длина строки |
| `map_dict` с `casefold` | O(m) | m = размер mapping dict (пересоздание) |

**Оптимизации**:
- `extract_patterns` предкомпилирует regex (`re.compile`) при каждом вызове. При массовом использовании — bottleneck
- Движок не кэширует скомпилированные regex между вызовами — каждый `apply()` компилирует заново

### Частые ошибки

- ❌ **Передать список в `to_int`**: `to_int` ожидает скалярное значение, список вызовет ошибку
- ✅ **Делай так**: Используй `coalesce` перед `to_int` для выбора одного значения

- ❌ **Забыть `strict: false` в `build_delimited_key`**: По умолчанию strict=true, None элементы вызовут ошибку
- ✅ **Делай так**: Явно указывай `strict: false` если допускаются пустые элементы

- ❌ **Использовать `op` + `ops` одновременно**: В specs.py `MappingRule` имеет shorthand expansion — `op` автоматически оборачивается в `ops: [OperationCall(...)]`
- ✅ **Делай так**: Используй либо `op` + `args` (для одной операции), либо `ops` (для цепочки)

---

## 🔗 Связанные документы

- [DSL Specs](./dsl-specs.md) — Pydantic-модели, YAML-загрузка, build options
- [DSL Diagnostics](./dsl-diagnostics.md) — Модель ошибок, диагностика, карта интеграции
- [Cache DSL](../cache/cache-dsl.md) — Как cache слой использует DSL для sync/projection
- [Resolve DSL](../resolver/resolve-dsl.md) — Как resolve слой компилирует правила через DSL

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-12 | Создан документ | dev |
