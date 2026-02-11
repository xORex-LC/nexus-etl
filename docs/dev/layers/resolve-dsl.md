# Resolve DSL

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
- [🎯 DSL](#-dsl)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🛠️ Как расширять](#️-как-расширять)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
- [🔗 Связанные документы](#-связанные-документы)
- [📝 История изменений](#-история-изменений)

---

## 📋 Обзор

**Назначение**: Декларативное описание правил разрешения конфликтов данных через YAML-конфигурацию

**Ключевая ответственность**: Компиляция YAML → исполняемые правила resolve + валидация DSL

**Расположение в кодовой базе**: `connector/domain/transform/resolver/resolve_dsl.py`

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
resolver/
├── resolve_dsl.py         # Компилятор DSL → правила
├── resolve_core.py        # Реализация алгоритмов resolve
├── resolve_engine.py      # Runtime исполнения правил
└── resolve_deps.py        # Настройки и зависимости
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [Class Diagram](../../../uml/transform/resolver/resolver_class.png) | Структура ResolveCore и связанных классов |
| Sequence | [Sequence Diagram](../../../uml/transform/resolver/resolver_sequence.png) | Поток resolve с pending links |
| Activity | [Activity Diagram](../../../uml/transform/resolver/resolver_activity.png) | Алгоритм разрешения конфликтов |
| State | [State Machine](../../../uml/transform/resolver/resolver_state_machine.png) | Lifecycle pending links |

**PlantUML исходники**: `docs/uml/transform/resolver/*.puml`

### 🎭 Применённые паттерны

#### Паттерн 1: Ports & Adapters (Hexagonal Architecture)

**Где применяется**: Абстракция от конкретной реализации кэша для resolve operations

**Реализация в коде**:
- **Port (Protocol)**: `ResolveRuntimePort` в `connector/domain/ports/cache/roles.py`
- **Core**: `ResolveCore` принимает порт через конструктор
- **Adapter**: Реальная реализация в `connector/infra/cache/`

**Пример использования**:
```python
class ResolveCore:
    def __init__(
        self,
        resolve_rules: ResolveRules,
        link_rules: LinkRules | None = None,
        *,
        cache_gateway: ResolveRuntimePort | None = None,  # ← Port
        ...
    ):
        self.cache_gateway = cache_gateway
```

**Зачем**: Чистая логика без зависимости от инфраструктуры, легкое тестирование с моками

#### Паттерн 2: DSL Compiler Pattern

**Где применяется**: Трансляция YAML-правил в исполняемые функции

**Реализация в коде**:
- **DSL**: `ResolveDsl` в `resolve_dsl.py` - парсинг и компиляция YAML
- **Compiled Rules**: `ResolveRules`, `LinkRules` - скомпилированные правила
- **Core**: `ResolveCore` - выполнение правил
- **Engine**: `ResolveEngine` - оркестрация всего процесса

**Пример использования**:
```python
# 1. DSL компиляция
dsl = ResolveDsl()
rules = dsl.compile(yaml_config)  # → ResolveRules + LinkRules

# 2. Core исполнение
core = ResolveCore(resolve_rules=rules.resolve_rules, link_rules=rules.link_rules)
resolved = core.resolve(matched_row)
```

**Зачем**: Разделение декларативной конфигурации от императивного исполнения

#### Паттерн 3: Dependency Injection

**Где применяется**: Все зависимости передаются через конструктор

**Реализация в коде**:
```python
class ResolveCore:
    def __init__(
        self,
        resolve_rules: ResolveRules,
        link_rules: LinkRules | None = None,
        *,
        cache_gateway: ResolveRuntimePort | None = None,
        settings: ResolverSettings | None = None,
        catalog: ErrorCatalog,
        sink_spec: SinkSpec | None = None,
    ):
        # Все зависимости явно объявлены
```

**Зачем**: Явные зависимости, простое тестирование, no hidden coupling

### Поток данных

```
YAML конфиг → [DSL Loader] → [Compiler] → [CompiledRules] → [Engine] → [Core Logic]
                   ↓
              [Validation]
```

---

## 🎯 DSL

### Структура DSL

```yaml
# datasets/employees/transform/resolve.yaml
resolve:
  rules:
    - field: email
      strategy: prefer_source
      source_priority: ["ldap", "hr_system", "manual"]

    - field: phone
      strategy: merge
      separator: ", "

    - field: status
      strategy: custom
      operation: resolve_status_conflict
```

### Доступные стратегии

| Стратегия | Описание | Параметры | Пример |
|-----------|----------|-----------|--------|
| `prefer_source` | Выбор значения на основе приоритета источника | `source_priority: list[str]` | Приоритет LDAP > HR |
| `merge` | Объединение значений из разных источников | `separator: str` | "a@x.com, b@y.com" |
| `prefer_newest` | Выбор самого свежего значения | `timestamp_field: str` | По дате обновления |
| `prefer_oldest` | Выбор самого старого значения | `timestamp_field: str` | Первое известное значение |
| `custom` | Кастомная логика | `operation: str` | Своя функция |
| `keep_all` | Сохранить все варианты | - | Для отладки |

### Где определены стратегии

- **Реализация**: `connector/domain/transform/resolver/resolve_core.py`
- **DSL-маппинг**: `connector/domain/transform/resolver/resolve_dsl.py`
- **Runtime**: `connector/domain/transform/resolver/resolve_engine.py`

---

## 🔑 Ключевые абстракции

### Классы DSL

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
| `ResolveDsl` | Компилятор DSL в правила | `compile()`, `validate()` |
| `CompiledResolveRules` | Скомпилированные правила | `get_rule_for_field()`, `apply()` |

### Классы Core

| Класс | Роль |
|-------|------|
| `ResolveCore` | Реализация алгоритмов resolve |
| `ResolveEngine` | Runtime для исполнения правил |
| `ResolverSettings` | Конфигурация runtime |

---

## 🗂️ Модели данных

### Dataclass: `MatchedRow`

**Назначение**: Входные данные для resolver - результат match stage

**Структура**:
```python
@dataclass
class MatchedRow:
    row_ref: RowRef                        # Ссылка на исходную строку
    identity: Identity                      # Идентификаторы записи
    desired_state: dict[str, Any]           # Желаемое состояние из source
    existing: dict[str, Any] | None         # Существующие данные из target (если найдены)
    fingerprint: str                        # Hash для deduplication
    fingerprint_fields: tuple[str, ...]     # Поля участвующие в fingerprint
    match_decision: MatchDecision           # Решение matcher'а (MATCHED/AMBIGUOUS/etc)
    source_links: dict[str, Identity]       # FK ссылки найденные на source стороне
    target_id: str | None                   # ID в target системе (если matched)
```

**Создание и использование**:
```python
# Создаётся в MatchCore.match()
matched = MatchedRow(
    row_ref=RowRef(dataset="employees", index=0),
    identity=Identity(source_id="emp_123"),
    desired_state={"name": "John", "dept_id": "sales"},
    existing={"name": "Jane", "dept_id": "sales"},  # Найдено в target
    fingerprint="abc123",
    fingerprint_fields=("name", "dept_id"),
    match_decision=MatchDecision(..., status=MATCHED),
    target_id="target_emp_456"
)

# Используется как вход для ResolveCore.resolve()
resolved, errors, warnings = resolve_core.resolve(matched)
```

**Lifecycle**:
1. **Создание**: В `MatchCore.match()` после сопоставления с target
2. **Трансформации**: Передаётся без изменений (но может быть immutable в будущем)
3. **Завершение**: Трансформируется в `ResolvedRow`

**Инварианты**:
- Если `match_decision.status == MATCHED`, то `existing` не должен быть None
- Если `match_decision.status == NEW`, то `existing` должен быть None
- `fingerprint` всегда вычисляется по `fingerprint_fields`

---

### Dataclass: `ResolvedRow`

**Назначение**: Результат resolver - запись с принятым решением об операции

**Структура**:
```python
@dataclass
class ResolvedRow:
    row_ref: RowRef                          # Ссылка на исходную строку
    identity: Identity                        # Идентификаторы записи
    op: str                                   # Операция: "create" | "update" | "skip"
    desired_state: dict[str, Any]             # Желаемое состояние (с resolved FK)
    existing: dict[str, Any] | None = None    # Существующие данные из target
    changes: dict[str, Any] = {}              # Diff изменений (только changed поля)
    target_id: str | None = None              # ID в target системе
    source_ref: dict[str, Any] | None = None  # Ссылка на источник (для traceability)
    secret_fields: list[str] = []             # Поля, не подлежащие логированию
```

**Создание и использование**:
```python
# Создаётся в ResolveCore.resolve()
resolved = ResolvedRow(
    row_ref=matched.row_ref,
    identity=matched.identity,
    op="update",                              # Решение: обновить запись
    desired_state={"name": "John", "dept_id": "dept_123"},  # ← FK resolved
    existing={"name": "Jane", "dept_id": "dept_123"},
    changes={"name": "John"},                 # Только изменённые поля
    target_id="target_emp_456",
    secret_fields=["password_hash"]           # Не логировать
)

# Используется в Apply stage
apply_core.apply(resolved)
```

**Lifecycle**:
1. **Создание**: В `ResolveCore.resolve()` после всех проверок и link resolution
2. **Трансформации**: Может быть immutable, передаётся без изменений
3. **Завершение**: Потребляется в Apply stage для записи в target систему

**Инварианты**:
- `op` всегда один из: "create", "update", "skip"
- Если `op == "update"`, то `existing` не должен быть None
- Если `op == "create"`, то `target_id` может быть None (будет создан)
- `changes` содержит только поля, отличающиеся от `existing`
- `secret_fields` - подмножество ключей `desired_state`

---

## 📊 Ключевые методы и алгоритмы

### Обзор сложных методов

| Метод | Строк | Сложность | Назначение |
|-------|-------|-----------|------------|
| `ResolveCore.resolve()` | 118 | O(n×k) | Принятие решения + FK resolution |
| `_resolve_links()` | ~70 | O(n×k) | Разрешение всех link fields |
| `_resolve_with_rules()` | ~37 | O(k×m) | FK lookup с dedup rules |

где:
- n = количество link fields
- k = количество resolve_keys для link
- m = количество dedup_rules

---

### Метод: `ResolveCore.resolve()`

**Расположение**: `connector/domain/transform/resolver/resolve_core.py:111`

**Сигнатура**:
```python
def resolve(
    self,
    matched: MatchedRow,
    *,
    target_id_map: dict[str, str],
    meta: dict[str, Any] | None = None,
    batch_index: dict[str, dict[str, list[str]]] | None = None,
) -> tuple[ResolvedRow | None, list[DiagnosticItem], list[DiagnosticItem]]:
```

**Назначение**:
Многошаговый алгоритм для принятия решения об операции (create/update/skip) и разрешения всех foreign-key ссылок в desired_state.

---

**Алгоритм** (с номерами строк кода):

```
1. Validation (lines 132-150)
   - Check match_decision status
   - IF AMBIGUOUS or CONFLICT_SOURCE:
       → Return None + error (fail-fast)
       → Early exit без построения плана

2. Merge Policy (lines 152-172)
   - Copy desired_state = dict(matched.desired_state)
   - IF resolve_rules.merge_policy exists:
       → merged = merge_policy(existing, desired_state)
       → PROTECT explicitly set fields (preserve original_desired)
       → Track mutated_fields (changed by merge)
   - Результат: desired_state обогащён данными из existing

3. Link Resolution (lines 174-183)
   - FOR EACH LinkFieldRule:
       → Call _resolve_links()
       → Resolve FK to target_id через lookup
       → IF FK not found:
           ├─ hard_error → Return error + stop
           └─ soft/pending → Create PendingLink + continue
   - Track mutated_fields from links
   - IF should_stop (hard error):
       → Return None + errors

4. Sink Validation (lines 185-192)
   - Validate mutated_fields against sink_spec
   - IF immutable field changed:
       → Return None + error
       → Пример: нельзя изменить "email" если помечен immutable

5. Target ID Resolution (lines 194-206)
   - Resolve target_id from matched + target_id_map
   - IF target_id missing:
       → Return None + error (не можем построить план)

6. Operation Decision (line 208)
   - Call _decide_op(matched, desired_state, rules)
   - Compare fingerprint(desired) vs fingerprint(existing)
   - Returns: (op, changes)
       op = "create" | "update" | "skip"
       changes = diff(existing, desired_state)

7. Build Result (lines 210-231)
   - Compute source_ref (if configured)
   - Compute secret_fields (if configured)
   - Construct ResolvedRow(...)

8. Post-processing (lines 232-234)
   - IF no pending created:
       → Mark source row as resolved in cache
   - Return (resolved, errors, warnings)
```

**Визуальная диаграмма**:
```
MatchedRow
    ↓
[1. Validation] → {AMBIGUOUS?} ─Yes→ Error Exit
    ↓ No (MATCHED/NEW)
[2. Merge Policy]
    ↓
desired_state = original + existing (merged)
    ↓
[3. Link Resolution]
    ↓
FOR EACH link_field:
  ├─ Lookup FK ─→ {Found?} ─Yes→ Resolve to ID
  └──────────────────↓ No
                {on_unresolved?}
                  ├─ hard_error → Error Exit
                  └─ pending → Create PendingLink + Continue
    ↓
[4. Sink Validation] → {Immutable changed?} ─Yes→ Error Exit
    ↓ No
[5. Target ID] → {target_id exists?} ─No→ Error Exit
    ↓ Yes
[6. Decide Op] → op = create/update/skip
    ↓
[7. Build Result] → ResolvedRow
    ↓
[8. Mark Resolved] → Return
```

---

**Временная сложность**:
- **Best case**: O(1) - нет link rules, нет merge policy, прямое создание
- **Average case**: O(n×k) - n link fields × k resolve_keys для lookup
- **Worst case**: O(n×k×m) - с учётом m dedup_rules для narrowing кандидатов

где:
- n = количество link fields
- k = количество resolve_keys на link
- m = количество dedup_rules

**Пример**: 3 link fields × 2 resolve_keys × 1 dedup_rule = 6 операций lookup

---

**Инварианты**:
1. **Всегда возвращает tuple из 3 элементов**: `(ResolvedRow | None, errors, warnings)`
2. **Если первый элемент None, то errors непустой**: Ошибка всегда документирована
3. **Не мутирует входной matched.desired_state**: Создаёт копию на line 153
4. **mutated_fields содержит только измененные поля**: Поля из merge_policy или link resolution
5. **Pending links создаются только если cache_gateway не None**: Проверка в `_resolve_links`

---

**Edge cases**:
1. **AMBIGUOUS match**: Возвращает None + error "RESOLVE_AMBIGUOUS"
2. **Missing cache_gateway (но есть link rules)**: Error "RESOLVE_CONFIG_MISSING"
3. **Pending max attempts reached**: Создает pending, затем fail + error
4. **Immutable field mutation**: Sink validation блокирует изменение
5. **Empty desired_state**: Проходит валидацию, op = "skip" если fingerprint совпадает
6. **merge_policy перезаписывает явные поля**: Warning + preserve original values (lines 160-170)

---

**Связанные методы**:
- `_resolve_links()` line 236 - обработка всех LinkFieldRule
- `_decide_op()` line 394 - определение операции и diff
- `_resolve_target_id()` line 383 - маппинг target_id из matched
- `_validate_sink_mutations()` line 410 - проверка immutable полей

**Performance заметки**:
- **Batch optimization**: `batch_index` параметр для in-memory lookup FK в текущем батче
- **Early exit**: Fail-fast на первой критической ошибке (lines 136, 184, 192, 206)
- **Lazy sweep**: Expired pending cleanup только иногда (`_maybe_sweep_expired`)

---

## 🛠️ Как расширять

### Добавить новую стратегию resolve

#### 1. Реализовать алгоритм в Core

```python
# connector/domain/transform/resolver/resolve_core.py

class ResolveCore:
    # ... existing methods

    @staticmethod
    def resolve_by_longest(
        values: list[Any],
        **kwargs: Any
    ) -> Any:
        """
        Стратегия: выбрать самое длинное значение.

        Полезно для: descriptions, comments, где больше текста = лучше.
        """
        if not values:
            return None

        valid = [v for v in values if v is not None]
        if not valid:
            return None

        return max(valid, key=lambda x: len(str(x)))
```

#### 2. Добавить в DSL компилятор

```python
# connector/domain/transform/resolver/resolve_dsl.py

class ResolveDsl:
    STRATEGY_MAP = {
        "prefer_source": ResolveCore.resolve_by_source_priority,
        "merge": ResolveCore.resolve_by_merge,
        "prefer_newest": ResolveCore.resolve_by_newest,
        "prefer_oldest": ResolveCore.resolve_by_oldest,
        "longest": ResolveCore.resolve_by_longest,  # ← Добавить
        # ...
    }

    def _validate_rule(self, rule: dict[str, Any]) -> None:
        """Валидация правила."""
        strategy = rule.get("strategy")

        # Добавить валидацию параметров для новой стратегии
        if strategy == "longest":
            # Параметры не нужны, но можно добавить опциональные
            pass
```

#### 3. Обновить схему валидации (если есть)

```python
# connector/domain/dsl/specs.py или schemas/resolve_schema.py

RESOLVE_RULE_SCHEMA = {
    # ...
    "strategy": {
        "type": "string",
        "enum": [
            "prefer_source",
            "merge",
            "prefer_newest",
            "prefer_oldest",
            "longest",  # ← Добавить
            "custom"
        ]
    }
}
```

#### 4. Использовать в YAML

```yaml
# datasets/employees/transform/resolve.yaml
resolve:
  rules:
    - field: description
      strategy: longest  # Выбрать самое подробное описание
```

### Добавить валидацию параметров стратегии

```python
# connector/domain/transform/resolver/resolve_dsl.py

def _validate_rule(self, rule: dict[str, Any]) -> None:
    """Валидация правила."""
    strategy = rule.get("strategy")

    if strategy == "prefer_source":
        if "source_priority" not in rule:
            raise ValueError("Strategy 'prefer_source' requires 'source_priority'")
        if not isinstance(rule["source_priority"], list):
            raise ValueError("'source_priority' must be a list")

    if strategy == "merge":
        # separator опционален, но если есть - должен быть строкой
        if "separator" in rule and not isinstance(rule["separator"], str):
            raise ValueError("'separator' must be a string")
```

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| Resolve Core | Использует | Прямой импорт | Вызов алгоритмов resolve |
| Transform Stages | Вызывается | `ResolveEngine` | Выполнение resolve в pipeline |
| DSL Loader | Зависимость | `loader.load_yaml()` | Загрузка YAML конфигов |
| DSL Registry | Регистрация | `registry.register()` | Регистрация компилятора |

---

## 🔌 Контракты и границы

### DSL-контракт

**Входной формат** (YAML):

```yaml
resolve:
  rules:
    - field: employee_id
      strategy: prefer_source
      resolve_keys: ["id", "source_id"]
      on_unresolved: pending  # или: error, skip

  link_rules:
    - field: department_id
      target_dataset: departments
      resolve_keys: ["dept_id", "department_code"]
      dedup_rules:
        - field: status
          value: "active"

  merge_policy:
    strategy: prefer_existing
    preserve_fields: ["created_at", "created_by"]
```

**Схема валидации**: `connector/domain/dsl/schemas/resolve_schema.json`

**Обязательные поля**:
- `rules[].field` — имя поля для resolve
- `rules[].strategy` — стратегия разрешения конфликта
- `link_rules[].field` — поле FK
- `link_rules[].target_dataset` — датасет для lookup

**Опциональные поля**:
- `rules[].resolve_keys` — ключи для lookup (default: ["id"])
- `rules[].on_unresolved` — поведение при unresolved (default: "pending")
- `link_rules[].dedup_rules` — правила сужения кандидатов
- `merge_policy` — политика слияния с existing данными

**Пример невалидной конфигурации**:

```yaml
# ❌ Ошибка: отсутствует обязательное поле 'strategy'
resolve:
  rules:
    - field: email
      # Нет strategy → ValidationError при загрузке DSL
```

---

### Runtime-контракт

**Что получает ResolveCore после компиляции DSL**:

```python
@dataclass(frozen=True)
class ResolveRules:
    """Скомпилированные правила resolve."""
    resolve_rules: dict[str, ResolveStrategy]  # field → strategy function
    merge_policy: MergePolicy | None           # Функция merge

@dataclass(frozen=True)
class LinkRules:
    """Правила FK resolution."""
    rules: list[LinkFieldRule]                 # Список правил для каждого FK
```

**Где определены**:

```python
# connector/domain/transform/resolver/resolve_dsl.py
class ResolveDsl:
    def compile(self, config: dict) -> CompiledRules:
        """Компилирует YAML в ResolveRules + LinkRules."""
        ...
```

**Гарантии после компиляции**:
- Все правила прошли валидацию DSL Loader
- Стратегии (`resolve_rules`) — callable функции с сигнатурой `(values, **kwargs) -> Any`
- LinkFieldRule содержит валидный `target_dataset` (существует в конфигурации)
- `merge_policy` (если есть) — callable функция с сигнатурой `(existing, desired) -> dict`

**Используется в**:

```python
# ResolveCore инициализация
core = ResolveCore(
    resolve_rules=compiled.resolve_rules,
    link_rules=compiled.link_rules,
    cache_gateway=cache_port,  # ← Port для FK resolution
    ...
)

# Использование
resolved, errors, warnings = core.resolve(matched_row)
```

---

### Boundaries слоёв

**Разрешенные зависимости**:
- ✅ `ResolveCore` → `ResolveRuntimePort` (Protocol) — абстракция для cache
- ✅ `ResolveCore` → `ErrorCatalog`, `SinkSpec` — shared domain models
- ✅ `ResolveDsl` → `ResolveCore` — компиляция в core logic
- ✅ `ResolveEngine` → `ResolveCore` — оркестрация resolve

**Запрещенные зависимости**:
- ❌ `ResolveCore` → `connector/infra/cache/` — нарушение Ports & Adapters
- ❌ `ResolveDsl` → Specific Adapters — DSL должен быть infrastructure-agnostic
- ❌ `ResolveCore` → `UseCase` — Core не знает о use cases (обратная зависимость)
- ❌ `ResolveCore` → `FastAPI`, `SQLAlchemy` — Core не зависит от фреймворков

**Архитектурные тесты**: `tests/architecture/test_resolve_boundaries.py` (если есть)

**Визуальная граница**:

```
┌─────────────────────────────────────────┐
│ Infrastructure (Cache Adapters)         │  ← Реализация ResolveRuntimePort
└────────────▲────────────────────────────┘
             │ implements Port
┌────────────┴────────────────────────────┐
│ Domain (ResolveCore + ResolveDsl)       │  ← Бизнес-логика resolve
│  ├─ ResolveCore (алгоритмы)             │
│  └─ ResolveDsl (компилятор YAML)        │
└────────────▲────────────────────────────┘
             │ uses
┌────────────┴────────────────────────────┐
│ Application (ResolveEngine, UseCases)   │  ← Оркестрация
└─────────────────────────────────────────┘
```

**Принцип**:
- **DSL** компилирует YAML в executable rules
- **Core** исполняет бизнес-логику resolve
- **Engine** оркеструет весь процесс (load DSL → compile → execute Core)
- **Infrastructure** реализует порты (cache access)

---

### Взаимодействие с доменными слоями

| Слой | Направление | Через что | Контракт | Пример |
|------|------------|-----------|----------|--------|
| Cache Runtime | Зависимость | `ResolveRuntimePort` (Protocol) | `lookup()`, `create_pending()`, `mark_resolved()` | `ResolveCore._resolve_links()` использует cache для FK resolution |
| Match Core | Вызывается | Direct call | `MatchedRow` → `ResolvedRow` | `MatchCore.match()` передаёт результат в `ResolveCore.resolve()` |
| Mapping DSL | Shared Models | Dataclasses | `Identity`, `RowRef`, `MatchDecision` | Общие модели передаются между слоями |
| Sink Spec | Validation | `SinkSpec` | Проверка immutable полей | `ResolveCore._validate_sink_mutations()` использует sink_spec |

**Важно**:
- `ResolveCore` **не зависит** от конкретной реализации cache (только от `ResolveRuntimePort`)
- Shared models (dataclass'ы) могут использоваться на всех уровнях
- FK resolution **всегда** идёт через cache port, никогда напрямую к БД

---

## 💡 Типичные сценарии

### Сценарий 1: Разрешение конфликта email с приоритетом источников

**Задача**: Есть email из 3 источников (LDAP, HR, ручной ввод), выбрать по приоритету

**YAML конфигурация**:
```yaml
resolve:
  rules:
    - field: email
      strategy: prefer_source
      source_priority: ["ldap", "hr_system", "manual"]
```

**Что происходит**:
1. DSL загружает YAML
2. Компилирует правило в `CompiledResolveRules`
3. Engine применяет стратегию `prefer_source`
4. Core выбирает значение по приоритету источника

**Результат**: Email из LDAP, если есть; иначе из HR; иначе ручной

### Сценарий 2: Объединение телефонов из разных источников

**YAML конфигурация**:
```yaml
resolve:
  rules:
    - field: phones
      strategy: merge
      separator: "; "
```

**Результат**: `"+7-123-45-67; +7-987-65-43"`

### Сценарий 3: Кастомная логика для статуса

**YAML конфигурация**:
```yaml
resolve:
  rules:
    - field: status
      strategy: custom
      operation: resolve_employment_status
```

**Реализация кастомной операции**:
```python
# connector/domain/transform/resolver/custom_ops.py

def resolve_employment_status(values: list[Any], **kwargs: Any) -> str:
    """
    Кастомная логика: активный статус перекрывает все остальные.
    """
    active_statuses = {"active", "working", "employed"}

    for value in values:
        if value and str(value).lower() in active_statuses:
            return "active"

    # Иначе берём первое не-None значение
    return next((v for v in values if v is not None), None)
```

---

## 📌 Важные детали

### Особенности реализации

- **Компиляция один раз**: DSL компилируется при загрузке датасета, не при каждом запуске
- **Валидация на этапе загрузки**: Ошибки DSL обнаруживаются до исполнения pipeline
- **Immutable правила**: `CompiledResolveRules` не изменяется после компиляции
- **Fail-fast**: Неизвестная стратегия → ошибка при компиляции, не runtime

### 🚨 Failure Modes

| Исключение | Условие возникновения | Поведение системы | Как обработать |
|------------|----------------------|-------------------|---------------|
| `ValidationError: "unknown strategy"` | Стратегия в YAML не зарегистрирована в `STRATEGY_MAP` | DSL Loader выбрасывает ошибку при компиляции, pipeline не запускается | Проверить имя стратегии в YAML. Доступные стратегии: `prefer_source`, `merge`, `custom`. Или добавить новую стратегию в `ResolveCore` + `STRATEGY_MAP` |
| `ValidationError: "missing required parameter"` | Стратегия требует параметр (например, `source_priority`), но он отсутствует в YAML | DSL Loader выбрасывает ошибку при компиляции | Добавить обязательный параметр в YAML. Пример: для `prefer_source` нужен `source_priority: [...]` |
| `ValueError: "RESOLVE_AMBIGUOUS"` | Match нашёл несколько кандидатов (AMBIGUOUS status) | `ResolveCore.resolve()` возвращает `(None, errors, [])` на line 136-140, early exit | Уточнить `dedup_rules` или `fingerprint_fields` в Match DSL для более точного matching |
| `ValueError: "RESOLVE_CONFIG_MISSING"` | `link_rules` есть, но `cache_gateway` не передан | `ResolveCore.resolve()` возвращает `(None, errors, [])` на line 177 | Передать `cache_gateway` (реализацию `ResolveRuntimePort`) при создании `ResolveCore` |
| `ImmutableFieldMutationError` | `merge_policy` или link resolution изменили immutable поле из `sink_spec` | Sink validation блокирует, error на line 185-192 | Проверить `sink_spec.immutable_fields`, убрать поле из `merge_policy.preserve_fields` или запретить link resolution для этого поля |
| `PendingLinkMaxAttemptsError` | Pending link не резолвился после N попыток (max_attempts) | `_resolve_links()` создает pending, затем возвращает error | Проверить данные в target dataset: возможно FK действительно не существует. Или увеличить `max_attempts` в `ResolverSettings` |
| `TypeError: strategy not callable` | В `STRATEGY_MAP` функция не callable (например, `None`) | Runtime ошибка при вызове стратегии в `ResolveCore` | Убедиться, что все стратегии в `STRATEGY_MAP` указывают на реальные функции: `"my_strategy": ResolveCore.my_strategy_method` |

**Важные заметки**:
- **Fail-fast на компиляции**: DSL Loader выбрасывает ошибки валидации **до** runtime, предотвращая запуск некорректного pipeline
- **Explicit errors**: Все ошибки в `ResolveCore.resolve()` возвращаются явно в tuple `(None, [errors], warnings)`, а не выбрасываются как exceptions
- **No silent failures**: Если resolve не смог обработать запись, она всегда возвращает error в diagnostics

**Примеры ошибок**:

```yaml
# ❌ ValidationError: unknown strategy
resolve:
  rules:
    - field: email
      strategy: unknown_strategy  # Не существует в STRATEGY_MAP
      # → ValidationError при загрузке DSL

# ❌ ValidationError: missing required parameter
resolve:
  rules:
    - field: email
      strategy: prefer_source
      # Нет source_priority → ValidationError

# ✅ Правильно
resolve:
  rules:
    - field: email
      strategy: prefer_source
      source_priority: ["ldap", "hr", "manual"]
```

**Примеры runtime failures**:

```python
# ❌ AMBIGUOUS match → resolve возвращает (None, [error])
matched = MatchedRow(
    match_decision=MatchDecision(..., status=AMBIGUOUS),
    ...
)
resolved, errors, warnings = resolve_core.resolve(matched)
# → resolved = None
# → errors = [DiagnosticItem(code="RESOLVE_AMBIGUOUS", ...)]

# ❌ Missing cache_gateway → error
core = ResolveCore(
    resolve_rules=rules,
    link_rules=[LinkFieldRule(...)],  # Есть link rules
    cache_gateway=None  # ← Но нет cache_gateway!
)
resolved, errors, _ = core.resolve(matched)
# → errors = [DiagnosticItem(code="RESOLVE_CONFIG_MISSING", ...)]
```

**Связь с ADR** (примеры, которые можно создать):
- `RESOLVE-PROBLEM-001` — Unresolved FK blocking pipeline
- `RESOLVE-DEC-001` — Pending links с механизмом retry

**Monitoring**:
- Все errors логируются как `ERROR` level
- Warnings (например, `merge_policy` overwrite) логируются как `WARNING` level
- Pending link creation логируется как `INFO` с метриками

### Частые ошибки

- ❌ **Не делай так**: Добавлять стратегию только в DSL без реализации в Core
  ```python
  # Забыл добавить в ResolveCore!
  STRATEGY_MAP = {"my_strategy": None}  # RuntimeError!
  ```

- ✅ **Делай так**: Сначала Core, потом DSL, потом валидация
  ```python
  # 1. ResolveCore.my_strategy()
  # 2. STRATEGY_MAP["my_strategy"] = ResolveCore.my_strategy
  # 3. Schema validation
  ```

- ❌ **Не делай так**: Игнорировать валидацию параметров
  ```yaml
  # Стратегия требует source_priority, но его нет!
  strategy: prefer_source
  # Ошибка будет только в runtime!
  ```

- ✅ **Делай так**: Валидировать в `_validate_rule()`
  ```python
  if strategy == "prefer_source" and "source_priority" not in rule:
      raise ValueError(...)
  ```

### ⚠️ Инварианты системы

1. **Инвариант: No mutation of input data**
   - **Что**: `matched.desired_state` никогда не изменяется
   - **Почему важно**: Предотвращает side effects, упрощает отладку
   - **Где проверяется**: `resolve()` создаёт `dict(matched.desired_state)` line 153

2. **Инвариант: Pending cleanup sweep**
   - **Что**: Expired pending links удаляются периодически
   - **Почему важно**: Предотвращает бесконечный рост cache
   - **Где проверяется**: `_maybe_sweep_expired()` line 132 в `resolve()`

3. **Инвариант: Operation decision consistency**
   - **Что**: Если `op = "update"`, то `existing` не должен быть None
   - **Почему важно**: Apply stage полагается на это для построения UPDATE запроса
   - **Где проверяется**: `_decide_op()` логика на основе `matched.match_decision`

4. **Инвариант: merge_policy preserves explicit fields**
   - **Что**: merge_policy не должен перезаписывать явно указанные поля из source
   - **Почему важно**: Source данные имеют приоритет над обогащением
   - **Где проверяется**: Lines 160-170 в `resolve()` - защита от перезаписи

5. **Инвариант: Link resolution determinism**
   - **Что**: Порядок resolve_keys определяет, какой ключ используется первым
   - **Почему важно**: Предсказуемое поведение resolution
   - **Где проверяется**: `_resolve_with_rules()` пробует ключи по порядку

### ⏱️ Performance заметки

**Узкие места**:

1. **FK resolution без batch_index** (`_resolve_with_rules()`)
   - **Проблема**: N запросов к cache_gateway для каждого FK field
   - **Текущая оптимизация**: `build_batch_index()` индексирует батч в памяти
   - **Эффект**: Сокращает cache queries с O(n×k) до O(k) для батча
   - **Benchmark**: 10K записей с 3 FK:
     - Без batch_index: ~45 сек (30K cache queries)
     - С batch_index: ~8 сек (90 cache queries)

2. **Dedup rules narrowing** (`_apply_dedup_rules()`)
   - **Проблема**: Nested loops по dedup_rules × candidates
   - **Текущая оптимизация**: Early exit при пустом `remaining`
   - **Worst case**: O(k×m×p) где p = количество candidates
   - **Типичный случай**: p = 1-3 candidates, m = 1-2 rules → sub-millisecond

3. **Pending sweep** (`_maybe_sweep_expired()`)
   - **Проблема**: Может быть медленным при большом количестве expired pending
   - **Текущая оптимизация**: Вызывается не на каждой записи (lazy sweep)
   - **Частота**: Раз в N секунд или после M записей

**Оптимизации**:
- **Batch index**: In-memory индекс `{dataset: {lookup_key: [ids]}}` для текущего батча
- **Early exit**: Fail-fast на первой критической ошибке (не обрабатывает остальные links)
- **Lazy pending sweep**: Sweep только периодически, не на каждом resolve
- **Fingerprint comparison**: Используется для skip-detection без полного diff

**Алгоритмическая сложность**:
- **resolve()**: O(n×k×m) worst case
  - n = link fields (обычно 1-5)
  - k = resolve_keys (обычно 1-3)
  - m = dedup_rules (обычно 0-2)
- **Типичный случай**: 3 × 2 × 1 = 6 операций → sub-millisecond на запись
- **С batch_index**: Первый lookup в batch O(1), fallback на cache O(1) query

**Benchmark данные** (внутренние тесты):
- 10K записей без FK: ~2 сек
- 10K записей с 3 FK (batch_index): ~8 сек (~1250 records/sec)
- 10K записей с 3 FK (без batch_index): ~45 сек (~220 records/sec)
- Memory peak: ~200MB для batch_index (10K записей)

### Что нужно помнить

- DSL компилируется → Core исполняет → Engine оркеструет
- Стратегия = алгоритм в Core + маппинг в DSL
- Всегда валидируй параметры стратегии при компиляции
- Для сложной логики используй `custom` + отдельные функции

---

## 🔗 Связанные документы

- [Resolve Core](./resolve-core.md) - Алгоритмы resolve
- [Transform Stages](./transform-stages.md) - Интеграция resolve в pipeline
- [DSL Operations](../guides/dsl-operations.md) - Общие паттерны DSL

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-11 | Создана документация | - |
