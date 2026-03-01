# Target DSL — декларативная спецификация целевой системы

> **Назначение**: YAML-файл спецификации полностью управляет поведением TargetKernel.
> Никакого Python-хардкода для классификации ошибок, политики повторов, маскирования логов
> и каталога операций — всё объявляется декларативно.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма зависимостей](#диаграмма-зависимостей)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
  - [TargetCapability](#targetcapability)
  - [FaultRule — правило классификации ошибки](#faultrule--правило-классификации-ошибки)
  - [RetryRule — правило повторной попытки](#retryrule--правило-повторной-попытки)
  - [RetryConfig — параметры повторных попыток](#retryconfig--параметры-повторных-попыток)
  - [OperationSpec — спецификация операции](#operationspec--спецификация-операции)
  - [RedactionSpec — безопасное логирование](#redactionspec--безопасное-логирование)
  - [HealthSpec](#healthspec)
  - [TargetSpec — корневая модель](#targetspec--корневая-модель)
- [🎯 DSL](#-dsl)
  - [Аннотированный YAML-пример](#аннотированный-yaml-пример)
  - [Pydantic v2 coercion](#pydantic-v2-coercion)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
  - [🚨 Failure Modes](#-failure-modes)
  - [⚠️ Инварианты системы](#️-инварианты-системы)
  - [⏱️ Performance заметки](#️-performance-заметки)
- [🛠️ Как расширять](#️-как-расширять)
- [🔗 Связанные документы](#-связанные-документы)
- [📝 История изменений](#-история-изменений)

---

## 📋 Обзор

**Назначение**: управлять поведением `TargetKernel` декларативно, без Python-хардкода в провайдере.
Всё, что ядро должно знать об Ankey IDM (или любом другом провайдере), хранится в одном YAML-файле.

**Ключевая ответственность**:
- Декларировать возможности провайдера (`capabilities`)
- Описывать правила классификации HTTP-ошибок (`fault_rules`)
- Определять политику повторных попыток (`retry_rules`, `retry_config`)
- Задавать правила безопасного логирования (`redaction`)
- Перечислять каталог операций (`operations`) с транспортными payload'ами

**Что остаётся в Python (не переносится в YAML)**:
- `auth` — адаптеры `httpx.Auth` (Bearer, Basic, mTLS)
- `paging strategy` — алгоритм итерации по страницам ответа
- `mutations` — Python-функции, зарегистрированные в `TargetMutationRegistry`
- `provider wiring` — сборка `TargetRuntime` в `AnkeyTargetProvider`

**Расположение в кодовой базе**:

```
connector/
├── domain/
│   └── target_dsl/
│       ├── __init__.py          # публичное API: load_target_spec
│       ├── loader.py            # загрузчик: registry -> YAML -> TargetSpec
│       └── spec_models.py       # Pydantic-модели спецификации
├── infra/
│   └── target/
│       ├── core/
│       │   └── kernel.py        # TargetKernel: classify_fault, retry, redact
│       └── providers/
│           └── ankey_rest/
│               └── provider.py  # AnkeyTargetProvider.build_core_runtime()
datasets/
├── registry.yml                 # targets: ankey -> targets/ankey.target.yaml
└── targets/
    └── ankey.target.yaml        # конкретная спецификация
```

---

## 🏗️ Архитектура слоя

### Основные компоненты

| Компонент | Файл | Назначение |
|-----------|------|-----------|
| `spec_models.py` | `connector/domain/target_dsl/` | Pydantic-модели всех элементов спецификации |
| `loader.py` | `connector/domain/target_dsl/` | Загрузка и валидация YAML → TargetSpec |
| `__init__.py` | `connector/domain/target_dsl/` | Публичный экспорт: `load_target_spec` |
| `ankey.target.yaml` | `datasets/targets/` | Конкретная YAML-спецификация для Ankey IDM |
| `registry.yml` | `datasets/` | Реестр: target_type → путь к YAML |

### 🎭 Применённые паттерны

- **Declarative-first**: поведение ядра описывается данными (YAML), а не кодом. Python-код ядра провайдеро-нейтрален.
- **Frozen data object**: все Pydantic-модели `frozen=True` — однажды созданная спецификация неизменна на весь lifetime runtime.
- **Extra-forbid validation**: `extra="forbid"` на всех моделях — неизвестные поля в YAML немедленно вызывают ошибку.
- **Alias injection**: поле `alias` в `OperationSpec` инжектируется загрузчиком из ключа словаря, устраняя дублирование в YAML.

**Что YAML контролирует полностью**:

| Аспект поведения           | Секция YAML       |
|----------------------------|-------------------|
| Возможности провайдера     | `capabilities`    |
| Классификация HTTP-ошибок  | `fault_rules`     |
| Политика повторных попыток | `retry_rules`     |
| Параметры backoff          | `retry_config`    |
| Маскирование в логах       | `redaction`       |
| Health-check операция      | `health`          |
| Каталог операций           | `operations`      |

### Диаграмма зависимостей

```
datasets/registry.yml
        |
        | targets.ankey --> "targets/ankey.target.yaml"
        v
datasets/targets/ankey.target.yaml
        |
        v
load_target_spec("ankey")          # connector/domain/target_dsl/loader.py
        |
        | 1. load_registry()
        | 2. read_yaml(path)
        | 3. _inject_aliases()       <-- alias: ключ словаря -> OperationSpec.alias
        | 4. TargetSpec.model_validate()  <-- Pydantic: list -> tuple/frozenset
        v
TargetSpec  (frozen Pydantic model, immutable)
        |
        v
TargetKernel.__init__(spec, compiler_registry)
        |
        | строит lookup-таблицы O(1) для classify_fault
        | компилирует все операции через TransportCompilerRegistry
        v
TargetKernel  (неизменяемый на весь runtime)
        |
        v
TargetGateway / DefaultTargetRuntime
```

---

## 🔑 Ключевые абстракции

### Интерфейсы / порты

| Имя | Где определён | Назначение |
|-----|---------------|-----------|
| `load_target_spec(target_type)` | `connector/domain/target_dsl/__init__.py` | Единственный публичный экспорт DSL-модуля |

### Основные классы

| Класс | Файл | Назначение |
|-------|------|-----------|
| `TargetSpec` | `spec_models.py` | Корневая модель всей спецификации |
| `FaultRule` | `spec_models.py` | Правило HTTP-статус → FaultKind |
| `RetryRule` | `spec_models.py` | Правило FaultKind → RetryDirective |
| `RetryConfig` | `spec_models.py` | Параметры экспоненциального backoff |
| `OperationSpec` | `spec_models.py` | Спецификация именованной операции |
| `RedactionSpec` | `spec_models.py` | Правила маскирования в логах |
| `HealthSpec` | `spec_models.py` | Конфигурация health-check операции |

**Типы-перечисления** (объявлены как `Literal` в Python):

```python
TargetFaultKind = Literal[
    "SPEC", "AUTH", "PERMISSION", "DATA",
    "NOT_FOUND", "CONFLICT", "THROTTLE", "TRANSIENT", "UNKNOWN",
]

TargetCapability = Literal["check", "execute", "read_paged"]

RetryDirective = Literal["NO_RETRY", "RETRY_BACKOFF", "RETRY_AFTER", "ESCALATE"]
```

---

## 🗂️ Модели данных

### Иерархия моделей

Все модели наследуют от `_SpecModel` — базового класса с двумя директивами Pydantic:
- `extra="forbid"` — неизвестные поля в YAML вызывают ошибку валидации
- `frozen=True` — экземпляры неизменяемы после создания (hashable, thread-safe)

```
TargetSpec
├── target_type: str
├── capabilities: frozenset[TargetCapability]
├── fault_rules: tuple[FaultRule, ...]
│   └── FaultRule
│       ├── fault_kind: TargetFaultKind
│       ├── match_status: int | None
│       ├── match_status_range: tuple[int, int] | None
│       └── match_error_code: str | None
├── retry_rules: tuple[RetryRule, ...]
│   └── RetryRule
│       ├── directive: RetryDirective
│       ├── match_fault: TargetFaultKind | None
│       ├── match_status: int | None
│       ├── match_reason: str | None          (нормализуется к lowercase)
│       └── mutation: str | None
├── retry_config: RetryConfig
│   ├── max_attempts: int           (default: 3)
│   ├── backoff_base: float         (default: 0.5)
│   ├── backoff_max: float          (default: 30.0)
│   └── jitter: bool                (default: True)
├── redaction: RedactionSpec
│   ├── forbidden_metadata_keys: frozenset[str]
│   ├── forbidden_fields: frozenset[str]
│   └── body_mode: "none" | "keys_only" | "truncated"
├── health: HealthSpec
│   └── operation_alias: str        (default: "health.check")
└── operations: dict[str, OperationSpec]
    └── OperationSpec
        ├── alias: str              (auto-injected из ключа словаря)
        ├── kind: str               (default: "http")
        ├── expected_statuses: tuple[int, ...]  (default: (200,))
        ├── timeout_ms: int | None
        ├── retry_profile: str | None
        ├── redaction_override: dict[str, Any] | None
        └── data: dict[str, Any]   (opaque transport payload)
```

---

### TargetCapability

| Значение     | Что разрешает                                              |
|--------------|------------------------------------------------------------|
| `check`      | Выполнение health-check (обязательно при наличии `health`) |
| `execute`    | Запись: upsert, create, update, delete                     |
| `read_paged` | Чтение с пагинацией (list, search)                         |

YAML-список автоматически преобразуется в `frozenset[TargetCapability]` при валидации Pydantic.

`TargetKernel` предоставляет два метода для работы с capabilities:

```python
def has_capability(self, capability: TargetCapability) -> bool:
    return capability in self._capabilities

def require_capability(self, capability: TargetCapability) -> None:
    if not self.has_capability(capability):
        raise ValueError(
            f"target capability {capability!r} is not supported "
            f"by target_type={self._spec.target_type!r}",
        )
```

`require_capability` вызывается перед каждой операцией в gateway/driver, чтобы провайдер
с ограниченным набором capabilities не мог выполнить запрещённую операцию.

---

### FaultRule — правило классификации ошибки

FaultRule отображает HTTP-статус или error_code драйвера на логический `TargetFaultKind`.

```python
class FaultRule(_SpecModel):
    fault_kind: TargetFaultKind           # к какому виду относить ошибку
    match_status: int | None = None       # точный HTTP-статус (например, 404)
    match_status_range: tuple[int, int] | None = None  # диапазон [low, high]
    match_error_code: str | None = None   # строковый код от драйвера (например, "NETWORK_ERROR")
```

**Правило: ровно один matcher**. Допустимые комбинации:
- только `match_status` — точный код
- только `match_status_range` — включительный диапазон `[low, high]`
- только `match_error_code` — строковый код от транспортного драйвера

```python
# ВЕРНО: точный статус
FaultRule(fault_kind="AUTH", match_status=401)

# ВЕРНО: диапазон
FaultRule(fault_kind="TRANSIENT", match_status_range=(500, 599))

# ВЕРНО: код ошибки
FaultRule(fault_kind="TRANSIENT", match_error_code="NETWORK_ERROR")

# ОШИБКА: нет matcher
FaultRule(fault_kind="DATA")
# -> ValueError: fault rule requires match_status, match_status_range or match_error_code
```

**Перечень TargetFaultKind**:

| FaultKind     | Семантика                                    | Типичный HTTP-код    |
|---------------|----------------------------------------------|----------------------|
| `SPEC`        | Ошибка конфигурации или спецификации         | нет (internal)       |
| `AUTH`        | Аутентификация отклонена                     | 401                  |
| `PERMISSION`  | Недостаточно прав доступа                    | 403                  |
| `DATA`        | Некорректные данные запроса                  | 400, 422             |
| `NOT_FOUND`   | Ресурс не найден                             | 404                  |
| `CONFLICT`    | Конфликт на стороне сервера                  | 409                  |
| `THROTTLE`    | Превышен лимит частоты запросов              | 429                  |
| `TRANSIENT`   | Временная ошибка (сеть, сервер недоступен)   | 500–599, сеть        |
| `UNKNOWN`     | Не совпало ни одно правило                   | любой неизвестный    |

**Приоритет в `classify_fault()`**: error_code → точный status → диапазон status → UNKNOWN.
`error_code` имеет приоритет: транспортный драйвер синтезирует `NETWORK_ERROR` при разрыве
соединения (когда `status_code=None`).

**FaultKind → SystemErrorCode** (маппинг в TargetKernel):

```python
_FAULT_TO_SYSTEM: dict[TargetFaultKind, SystemErrorCode] = {
    "AUTH":       SystemErrorCode.AUTH_UNAUTHORIZED,
    "PERMISSION": SystemErrorCode.AUTH_FORBIDDEN,
    "DATA":       SystemErrorCode.DATA_INVALID,
    "NOT_FOUND":  SystemErrorCode.DATA_INVALID,
    "CONFLICT":   SystemErrorCode.CONFLICT,
    "THROTTLE":   SystemErrorCode.INFRA_UNAVAILABLE,
    "TRANSIENT":  SystemErrorCode.INFRA_UNAVAILABLE,
    "SPEC":       SystemErrorCode.INTERNAL_ERROR,
    "UNKNOWN":    SystemErrorCode.INTERNAL_ERROR,
}
```

---

### RetryRule — правило повторной попытки

```python
class RetryRule(_SpecModel):
    directive: RetryDirective                    # что делать при совпадении
    match_fault: TargetFaultKind | None = None   # фильтр по fault kind
    match_status: int | None = None              # фильтр по HTTP-статусу
    match_reason: str | None = None              # фильтр по причине (нормализуется lowercase)
    mutation: str | None = None                  # имя мутации из TargetMutationRegistry
```

**RetryDirective — что каждое значение означает**:

| Директива       | Действие                                                                      |
|-----------------|-------------------------------------------------------------------------------|
| `NO_RETRY`      | Не повторять, передать ошибку выше как финальную                              |
| `RETRY_BACKOFF` | Повторить через экспоненциальный backoff (параметры из `retry_config`)        |
| `RETRY_AFTER`   | Повторить с задержкой из заголовка `Retry-After` от сервера                  |
| `ESCALATE`      | Передать ошибку вверх как критическую, без накопления в retry-счётчике        |

**Правило: хотя бы один matcher** (`match_fault`, `match_status`, `match_reason`).

**Нормализация match_reason**: поле автоматически приводится к нижнему регистру при валидации.
`"resourceexists"` совпадёт и с `"ResourceExists"` от сервера.

**Опция mutation**: строковое имя функции-мутатора, зарегистрированной в `TargetMutationRegistry`.
Применяется перед повторной попыткой.

**Порядок правил: first match wins**. Более специфичные правила (с несколькими матчерами) должны
идти перед более общими:

```yaml
retry_rules:
  # Сначала специфичный случай CONFLICT + reason
  - directive: RETRY_BACKOFF
    match_fault: CONFLICT
    match_reason: resourceexists
    mutation: regenerate_target_id

  # Затем общий случай CONFLICT
  - directive: NO_RETRY
    match_fault: CONFLICT
```

---

### RetryConfig — параметры повторных попыток

```python
class RetryConfig(_SpecModel):
    max_attempts: int   = Field(default=3,    ge=0)
    backoff_base: float = Field(default=0.5,  ge=0.0)
    backoff_max:  float = Field(default=30.0, ge=0.0)
    jitter: bool = True
```

`max_attempts` — количество **дополнительных** попыток, не считая первоначальной.
Итого выполняется не более `max_attempts + 1` запросов к target.

**Формула экспоненциального backoff**:
```
delay(attempt) = min(backoff_base * 2^attempt, backoff_max)
```

При `jitter=True` к задержке добавляется случайное смещение в диапазоне `[0, delay(attempt)]`.

| Попытка | Без jitter | С jitter (пример) |
|:-------:|:----------:|:-----------------:|
| 1       | 0.5 с      | 0.3 с             |
| 2       | 1.0 с      | 0.8 с             |
| 3       | 2.0 с      | 1.7 с             |
| 4       | 4.0 с      | 3.2 с             |
| 7       | 30.0 с     | 22.1 с (cap)      |

`AnkeyTargetProvider` позволяет переопределить параметры из конфигурации приложения через
`apply_retry_overrides()` — иммутабельное слияние через `model_copy(update=...)`.

---

### OperationSpec — спецификация операции

```python
class OperationSpec(_SpecModel):
    alias: str                                      # уникальное имя (auto-injected)
    kind: str = "http"                              # тип транспорта
    expected_statuses: tuple[int, ...] = (200,)     # успешные HTTP-статусы
    timeout_ms: int | None = Field(default=None, ge=1)
    retry_profile: str | None = None
    redaction_override: dict[str, Any] | None = None
    data: dict[str, Any] = Field(default_factory=dict)  # opaque transport payload
```

**alias: auto-injected из ключа словаря**. Автор YAML **не должен** писать `alias` вручную —
загрузчик инжектирует его автоматически. Ключ словаря в YAML = alias операции.

**kind**: определяет компилятор из `TransportCompilerRegistry`. Текущая реализация поддерживает
только `"http"`. Значение передаётся в `TransportCompilerRegistry.compile()` при инициализации.

**expected_statuses**: если сервер вернул код не из этого списка — результат считается ошибкой
и передаётся в `classify_fault()`.

**data: opaque payload**. TargetKernel не интерпретирует `data` — он передаётся транспортному
компилятору. Для HTTP-транспорта типичная структура:

```yaml
data:
  method: GET
  path_template: /ankey/managed/user/{target_id}
  query_defaults:
    _queryFilter: "true"
```

**redaction_override**: переопределяет настройки `RedactionSpec` для конкретной операции.
Позволяет одним операциям логировать подробнее, другим — скрывать полностью.

---

### RedactionSpec — безопасное логирование

```python
class RedactionSpec(_SpecModel):
    forbidden_metadata_keys: frozenset[str] = frozenset({
        "authorization", "cookie", "set-cookie", "x-api-key", "x-ankey-password",
    })
    forbidden_fields: frozenset[str] = frozenset({
        "password", "token", "secret", "api_key",
    })
    body_mode: Literal["none", "keys_only", "truncated"] = "truncated"
```

**forbidden_metadata_keys**: HTTP-заголовки (lowercase), которые заменяются на `"***"` в логах.
Сравнение через `.lower()` — регистронезависимо.

**body_mode — режим логирования тела**:

| Значение     | Поведение                                                      |
|--------------|----------------------------------------------------------------|
| `none`       | Тело не логируется совсем, возвращается `None`                 |
| `keys_only`  | Для dict — только список ключей верхнего уровня (без значений) |
| `truncated`  | Первые N символов или маскированный dict (дефолт)             |

```python
def safe_body(self, body: Any, redaction: RedactionSpec | None = None) -> Any:
    mode = (redaction or self._spec.redaction).body_mode
    if mode == "none":
        return None
    if isinstance(body, str):
        return truncateText(body)
    if mode == "keys_only" and isinstance(body, dict):
        return list(body.keys())
    return maskSecretsInObject(body)
```

---

### HealthSpec

```python
class HealthSpec(_SpecModel):
    operation_alias: str = "health.check"
```

**Инварианты**:
1. `operation_alias` не может быть пустой строкой
2. Указанный alias обязан присутствовать в словаре `operations`
3. Наличие секции `health` требует capability `check`

---

### TargetSpec — корневая модель

```python
class TargetSpec(_SpecModel):
    target_type: str
    capabilities: frozenset[TargetCapability]
    fault_rules: tuple[FaultRule, ...]
    retry_rules: tuple[RetryRule, ...]
    retry_config: RetryConfig
    redaction: RedactionSpec
    health: HealthSpec
    operations: dict[str, OperationSpec] = Field(default_factory=dict)
```

`operations` — единственное поле с `default_factory=dict`. Все остальные обязательны в YAML.

**Три модельных инварианта** (проверяются `_validate_spec_integrity()`):

```python
# Инвариант 1: health требует capability "check"
if "check" not in self.capabilities:
    raise ValueError("health specification requires 'check' capability")

# Инвариант 2: health alias должен быть в operations
if self.health.operation_alias not in self.operations:
    raise ValueError(f"health operation alias is not declared: {self.health.operation_alias!r}")

# Инвариант 3: ключ словаря == alias (гарантирует корректность alias injection)
for alias, operation in self.operations.items():
    if alias != operation.alias:
        raise ValueError(f"operation alias key mismatch: key={alias!r}, alias={operation.alias!r}")
```

---

## 🎯 DSL

### Аннотированный YAML-пример

Полный файл `datasets/targets/ankey.target.yaml` с комментариями к каждой секции:

```yaml
# Декларативная спецификация target-провайдера Ankey IDM REST API.
# Загружается через connector.domain.target_dsl.load_target_spec("ankey").

# Идентификатор провайдера — совпадает с ключом в datasets/registry.yml
target_type: ankey

# ---------------------------------------------------------------------------
# Возможности провайдера.
# YAML-список -> frozenset[TargetCapability] при валидации.
# "check"      — разрешён health-check (обязателен при наличии секции health)
# "execute"    — разрешены операции записи (upsert, create, update, delete)
# "read_paged" — разрешено чтение с пагинацией (list, search)
# ---------------------------------------------------------------------------
capabilities:
  - check
  - execute
  - read_paged

# ---------------------------------------------------------------------------
# Health-check. operation_alias должен совпадать с ключом в operations.
# ---------------------------------------------------------------------------
health:
  operation_alias: health.check

# ---------------------------------------------------------------------------
# Классификация ошибок: HTTP-статус / error_code -> FaultKind.
# Порядок влияет на построение lookup-таблиц, но не на приоритет
# (TargetKernel проверяет: error_code -> точный статус -> диапазон).
# Каждое правило содержит ровно один matcher.
# ---------------------------------------------------------------------------
fault_rules:
  - fault_kind: AUTH
    match_status: 401

  - fault_kind: PERMISSION
    match_status: 403

  - fault_kind: DATA
    match_status: 400

  - fault_kind: DATA
    match_status: 422

  - fault_kind: NOT_FOUND
    match_status: 404

  - fault_kind: CONFLICT
    match_status: 409

  - fault_kind: THROTTLE
    match_status: 429

  # Диапазон для всех 5xx
  - fault_kind: TRANSIENT
    match_status_range: [500, 599]

  # Сетевые ошибки синтезируются драйвером с кодом NETWORK_ERROR
  - fault_kind: TRANSIENT
    match_error_code: NETWORK_ERROR

# ---------------------------------------------------------------------------
# Параметры механики retry: экспоненциальный backoff с jitter.
# max_attempts  — число ДОПОЛНИТЕЛЬНЫХ попыток (не считая первую)
# backoff_base  — начальная задержка в секундах
# backoff_max   — потолок задержки
# jitter        — рандомизация задержки (предотвращает thundering herd)
# ---------------------------------------------------------------------------
retry_config:
  max_attempts: 3
  backoff_base: 0.5
  backoff_max: 30.0
  jitter: true

# ---------------------------------------------------------------------------
# Правила реакции: FaultKind -> RetryDirective.
# Порядок критичен: first match wins.
# Специфичные правила (несколько матчеров) идут выше общих.
# mutation — имя функции из TargetMutationRegistry; применяется перед повтором.
# ---------------------------------------------------------------------------
retry_rules:
  - directive: RETRY_BACKOFF
    match_fault: TRANSIENT

  - directive: RETRY_AFTER
    match_fault: THROTTLE

  # Специфичный CONFLICT: ресурс уже существует с таким UUID.
  # Мутация генерирует новый target_id. Идёт ПЕРЕД общим NO_RETRY для CONFLICT.
  - directive: RETRY_BACKOFF
    match_fault: CONFLICT
    match_reason: resourceexists
    mutation: regenerate_target_id

  - directive: NO_RETRY
    match_fault: AUTH

  - directive: NO_RETRY
    match_fault: PERMISSION

  - directive: NO_RETRY
    match_fault: DATA

  - directive: NO_RETRY
    match_fault: NOT_FOUND

  # Общий CONFLICT без reason — NO_RETRY
  - directive: NO_RETRY
    match_fault: CONFLICT

# ---------------------------------------------------------------------------
# Правила маскирования для безопасного логирования.
# ---------------------------------------------------------------------------
redaction:
  body_mode: truncated
  forbidden_metadata_keys:
    - authorization
    - cookie
    - set-cookie
    - x-api-key
    - x-ankey-password
  forbidden_fields:
    - password
    - token
    - secret
    - api_key

# ---------------------------------------------------------------------------
# Каталог операций.
# ВАЖНО: alias НЕ указывается в YAML — инжектируется из ключа словаря.
# kind по умолчанию "http".
# data — opaque payload для транспортного компилятора.
#
# Для HTTP-операций:
#   method        — HTTP-метод (GET, PUT, POST, DELETE, PATCH)
#   path_template — шаблон пути; {param} заменяется при выполнении
#   query_defaults — параметры строки запроса (значения ДОЛЖНЫ быть строками)
# ---------------------------------------------------------------------------
operations:
  health.check:
    expected_statuses: [200]
    data:
      method: GET
      path_template: /ankey/managed/user
      query_defaults:
        page: "1"
        rows: "1"
        _queryFilter: "true"

  users.list:
    expected_statuses: [200]
    data:
      method: GET
      path_template: /ankey/managed/user
      query_defaults:
        _queryFilter: "true"

  organizations.list:
    expected_statuses: [200]
    data:
      method: GET
      path_template: /ankey/managed/organization
      query_defaults:
        _queryFilter: "true"

  users.upsert:
    expected_statuses: [200, 201]
    data:
      method: PUT
      path_template: /ankey/managed/user/{target_id}
      query_defaults:
        _prettyPrint: "true"
        decrypt: "false"
```

---

### Pydantic v2 coercion

YAML не имеет типов «кортеж» или «frozenset». Pydantic v2 автоматически выполняет coercion:

| Python-тип в модели           | YAML-тип | Coercion         |
|-------------------------------|----------|------------------|
| `tuple[FaultRule, ...]`       | `list`   | list → tuple     |
| `tuple[RetryRule, ...]`       | `list`   | list → tuple     |
| `tuple[int, ...]`             | `list`   | list → tuple     |
| `tuple[int, int]`             | `list`   | list → tuple     |
| `frozenset[TargetCapability]` | `list`   | list → frozenset |
| `frozenset[str]`              | `list`   | list → frozenset |

**Зачем immutability**:
- `tuple` для `fault_rules`/`retry_rules` — гарантирует порядок и неизменяемость
- `frozenset` для `capabilities`/`forbidden_*` — O(1) lookup, hashable, thread-safe

```python
type(spec.capabilities)  # frozenset
"execute" in spec.capabilities  # True (O(1))

rule = spec.fault_rules[0]
type(rule.match_status_range)  # tuple
```

**Ограничение `extra="forbid"`**: любой неизвестный ключ в YAML вызывает `ValidationError`.
Это предотвращает опечатки (`match_statuses` вместо `match_status`).

---

## 📊 Ключевые методы и алгоритмы

### load_target_spec() — алгоритм загрузки

```python
# connector/domain/target_dsl/__init__.py
from connector.domain.target_dsl.loader import load_target_spec

__all__ = ["load_target_spec"]
```

**Сигнатура**:
```python
def load_target_spec(target_type: str) -> TargetSpec:
    """Загрузить TargetSpec для указанного провайдера из YAML через registry."""
```

**Пошаговый алгоритм**:

```
Шаг 1. load_registry()
        Читает datasets/registry.yml через find_repo_root() + read_yaml().
        Возвращает dict с секциями targets, datasets, cache, dictionaries.

Шаг 2. _resolve_target_path(registry, target_type)
        Ищет registry["targets"][target_type].
        Если ключ отсутствует -> DslLoadError(code="TARGET_DSL_REGISTRY_MISSING")
        Если значение пустое  -> DslLoadError(code="TARGET_DSL_REGISTRY_INVALID")
        Возвращает: find_repo_root() / "datasets" / relative_path

Шаг 3. _read_target_yaml(path, target_type)
        Вызывает read_yaml(path).
        При любой ошибке чтения/парсинга YAML ->
            DslLoadError(code="TARGET_DSL_FILE_ERROR")
        Возвращает raw dict.

Шаг 4. _inject_aliases(raw)
        Для каждого ключа операции в raw["operations"]:
            op_data["alias"] = key
        Модифицирует raw in-place. Не вызывает ошибок.

Шаг 5. _validate_target_spec(raw, target_type, path)
        Вызывает TargetSpec.model_validate(raw).
        Pydantic выполняет:
            - coercion list -> tuple / frozenset
            - field-level валидаторы (FaultRule, RetryRule, OperationSpec, ...)
            - model-level валидатор TargetSpec._validate_spec_integrity()
        При любой Pydantic-ошибке ->
            DslLoadError(code="TARGET_DSL_SPEC_INVALID")
        Возвращает TargetSpec.
```

**Коды ошибок DslLoadError**:

| Код                           | Причина                                               |
|-------------------------------|-------------------------------------------------------|
| `TARGET_DSL_REGISTRY_MISSING` | `target_type` не найден в секции `targets:` registry  |
| `TARGET_DSL_REGISTRY_INVALID` | Путь в registry пустой или None                       |
| `TARGET_DSL_FILE_ERROR`       | Файл не найден или содержит невалидный YAML           |
| `TARGET_DSL_SPEC_INVALID`     | Pydantic-валидация TargetSpec завершилась с ошибкой   |

### Alias injection — _inject_aliases()

```python
def _inject_aliases(data: dict[str, Any]) -> None:
    """Инжектировать поле alias в каждую операцию из ключа словаря."""
    for key, op_data in data.get("operations", {}).items():
        op_data["alias"] = key
```

Зачем нужна инъекция: устраняет дублирование в YAML. Автор не пишет `alias: users.upsert` —
это значение уже есть как ключ словаря.

### Lookup-таблицы TargetKernel

При инициализации `TargetKernel` разбирает `spec.fault_rules` в три структуры:

```python
# O(1) lookup по точному статусу
self._fault_by_status: dict[int, TargetFaultKind] = {
    r.match_status: r.fault_kind
    for r in spec.fault_rules
    if r.match_status is not None
}

# Линейный список диапазонов (обычно один: 500-599)
self._fault_by_range: list[tuple[int, int, TargetFaultKind]] = [
    (*r.match_status_range, r.fault_kind)
    for r in spec.fault_rules
    if r.match_status_range is not None
]

# O(1) lookup по строковому коду (uppercase)
self._fault_by_code: dict[str, TargetFaultKind] = {
    r.match_error_code: r.fault_kind
    for r in spec.fault_rules
    if r.match_error_code is not None
}
```

---

## 🔄 Взаимодействие с другими слоями

```
datasets/registry.yml
       ↓ (путь к YAML)
datasets/targets/ankey.target.yaml
       ↓ load_target_spec()
connector/domain/target_dsl/      ← DSL-слой (этот документ)
       ↓ TargetSpec
connector/infra/target/core/kernel.py   ← TargetKernel читает TargetSpec один раз
       ↓
connector/infra/target/core/gateway.py  ← TargetGateway использует Kernel для classify/retry
       ↓
connector/infra/target/providers/ankey_rest/provider.py  ← вызывает load_target_spec (lazy)
```

**Взаимодействие**:
- DSL → `TargetKernel`: спецификация передаётся при инициализации ядра; ядро строит lookup-таблицы
- DSL → `AnkeyTargetProvider`: провайдер вызывает `load_target_spec()` lazy (внутри метода), чтобы избежать circular import
- DSL → `registry.yml`: загрузчик читает реестр для разрешения пути к YAML-файлу

**Почему lazy import в AnkeyTargetProvider**:

```python
def build_core_runtime(self, ...) -> TargetRuntime:
    from connector.domain.target_dsl import load_target_spec  # lazy!
    spec = load_target_spec("ankey")
```

Причина — циклический импорт: `domain.target_dsl` → `domain.dsl` → (косвенно) → `infra.target`.
Lazy import внутри метода разрывает цикл на уровне Python-загрузчика.

---

## 🔌 Контракты и границы

**Контракт загрузчика**:
- `load_target_spec(target_type)` всегда возвращает валидный `TargetSpec` или бросает `DslLoadError`
- Возвращённый `TargetSpec` — frozen (immutable): никакой пост-изменение не возможно

**Что остаётся opaque для DSL-слоя**:
- Содержимое `OperationSpec.data` — интерпретируется только транспортным компилятором
- Имена мутаций в `RetryRule.mutation` — регистрируются провайдером, не валидируются DSL

**Границы ответственности**:
- DSL **не знает** о `httpx`, `TargetGateway`, конкретных URL провайдера
- DSL **не создаёт** `TargetKernel` — он только поставляет `TargetSpec`
- DSL **не валидирует** содержимое `data` — это задача транспортного компилятора

---

## 💡 Типичные сценарии

### Добавить новый target type

1. Создать `datasets/targets/myidm.target.yaml`
2. Добавить в `datasets/registry.yml`:
   ```yaml
   targets:
     ankey: targets/ankey.target.yaml
     myidm: targets/myidm.target.yaml
   ```
3. Загрузить: `load_target_spec("myidm")`
4. Создать провайдер с `load_target_spec("myidm")` (lazy import)

### Добавить новую операцию

В YAML добавить запись в `operations:` (alias = ключ, писать не нужно):
```yaml
operations:
  users.delete:
    expected_statuses: [204]
    data:
      method: DELETE
      path_template: /ankey/managed/user/{target_id}
```

### Переопределить redaction для одной операции

```yaml
operations:
  users.upsert:
    redaction_override:
      body_mode: none   # не логировать тело для этой операции
    data:
      method: PUT
      path_template: /ankey/managed/user/{target_id}
```

### Добавить mutation в retry rule

1. Зарегистрировать Python-функцию в `TargetMutationRegistry` в провайдере
2. Добавить правило в YAML:
   ```yaml
   retry_rules:
     - directive: RETRY_BACKOFF
       match_fault: CONFLICT
       match_reason: resourceexists
       mutation: regenerate_target_id  # имя функции в реестре мутаций
   ```

### Q: Нужно ли писать alias в YAML?

Нет. Поле `alias` инжектируется автоматически. Если написать расходящиеся alias и ключ — валидация выбросит:
```
ValueError: operation alias key mismatch: key='users.upsert', alias='users.create'
```

### Q: Что значит «opaque data» в OperationSpec?

`data` непрозрачен для TargetKernel. Ядро передаёт его в `TransportCompilerRegistry.compile()`.
Это позволяет добавлять новые транспортные протоколы (gRPC, database) без изменения ядра.

### Q: Почему query_defaults значения должны быть строками?

HTTP-параметры передаются строками. YAML позволяет `page: 1` (int), но это вызовет ошибку типов
в компиляторе. Безопаснее: `page: "1"`.

---

## 📌 Важные детали

### 🚨 Failure Modes

| Инвариант                                    | Где проверяется                       | Исключение    | Как исправить                                         |
|----------------------------------------------|---------------------------------------|---------------|-------------------------------------------------------|
| FaultRule требует ровно один matcher         | `FaultRule._validate_matcher`         | `ValueError`  | Добавить `match_status`, `match_status_range` или `match_error_code` |
| FaultRule не может иметь status + range      | `FaultRule._validate_matcher`         | `ValueError`  | Убрать один из двух матчеров                          |
| RetryRule требует хотя бы один matcher       | `RetryRule._validate_matcher`         | `ValueError`  | Добавить `match_fault`, `match_status` или `match_reason` |
| RetryRule match_reason не пустая строка      | `RetryRule._validate_matcher`         | `ValueError`  | Указать непустое значение или убрать поле             |
| RetryConfig backoff_max >= backoff_base      | `RetryConfig._validate_backoff`       | `ValueError`  | Увеличить `backoff_max` или уменьшить `backoff_base`  |
| OperationSpec http требует непустой data     | `OperationSpec._validate_operation`   | `ValueError`  | Добавить поля method/path_template в `data:`          |
| TargetSpec требует capability "check"        | `TargetSpec._validate_spec_integrity` | `ValueError`  | Добавить `check` в `capabilities:`                   |
| TargetSpec health alias есть в operations    | `TargetSpec._validate_spec_integrity` | `ValueError`  | Добавить операцию или исправить alias                 |
| TargetSpec ключ operations == alias          | `TargetSpec._validate_spec_integrity` | `ValueError`  | Не писать alias вручную в YAML                       |
| Неизвестное поле в YAML                      | Pydantic `extra="forbid"`             | `ValidationError` | Убрать неизвестный ключ или исправить опечатку    |
| target_type не найден в registry             | `_resolve_target_path`                | `DslLoadError` | Добавить в `datasets/registry.yml`                  |
| Файл YAML недоступен                         | `_read_target_yaml`                   | `DslLoadError` | Проверить путь в registry.yml                        |

Все ошибки при загрузке оборачиваются в `DslLoadError` с кодом и `details`:

```python
DslLoadError(
    code="TARGET_DSL_REGISTRY_MISSING",
    message="Target provider 'myidm' not found in registry.yml under 'targets:'",
    details={"target_type": "myidm", "available": ["ankey"]},
)
```

### ⚠️ Инварианты системы

1. `TargetSpec` frozen — создаётся один раз, никогда не изменяется в runtime
2. Все модели `extra="forbid"` — неизвестные ключи в YAML немедленно отклоняются
3. `alias` инжектируется загрузчиком, а не автором YAML
4. Порядок `retry_rules` критичен (first match wins) — специфичные правила выше общих
5. `OperationSpec.data` — opaque для ядра, интерпретируется только транспортным компилятором
6. Единственный публичный экспорт модуля — `load_target_spec`
7. Lazy import `load_target_spec` в методе провайдера — обязательный паттерн

### ⏱️ Performance заметки

- Спецификация читается **один раз** при старте провайдера, не при каждом запросе
- `TargetKernel` строит O(1) lookup-таблицы при инициализации из `fault_rules`
- `frozenset` для `capabilities`/`forbidden_*` — O(1) lookup вместо O(n) списка
- После init — никакого I/O: все операции в памяти

---

## 🛠️ Как расширять

### Добавить новый target провайдер (YAML + registry)

1. Создать `datasets/targets/myidm.target.yaml` (минимальная структура):

```yaml
target_type: myidm
capabilities: [check, execute]

health:
  operation_alias: health.check

fault_rules:
  - fault_kind: AUTH
    match_status: 401
  - fault_kind: TRANSIENT
    match_status_range: [500, 599]
  - fault_kind: TRANSIENT
    match_error_code: NETWORK_ERROR

retry_config:
  max_attempts: 3
  backoff_base: 0.5
  backoff_max: 30.0
  jitter: true

retry_rules:
  - directive: RETRY_BACKOFF
    match_fault: TRANSIENT
  - directive: NO_RETRY
    match_fault: AUTH

redaction:
  body_mode: truncated
  forbidden_metadata_keys: [authorization]
  forbidden_fields: [password, token]

operations:
  health.check:
    expected_statuses: [200]
    data:
      method: GET
      path_template: /api/health
```

2. Добавить в `datasets/registry.yml`:

```yaml
targets:
  ankey: targets/ankey.target.yaml
  myidm: targets/myidm.target.yaml
```

3. В провайдере использовать `load_target_spec("myidm")` (lazy import).

### Добавить новое fault правило

Добавить запись в `fault_rules:` с **ровно одним** matcher:
```yaml
fault_rules:
  - fault_kind: NOT_FOUND
    match_status: 404
```

### Добавить retry с мутацией

1. Реализовать Python-функцию мутатора и зарегистрировать в `build_ankey_mutations()`
2. Добавить в `retry_rules:` (перед общим правилом для этого fault_kind):
```yaml
retry_rules:
  - directive: RETRY_BACKOFF
    match_fault: CONFLICT
    match_reason: my_conflict_reason
    mutation: my_mutation_name
```

---

## 🔗 Связанные документы

- [target-core.md](target-core.md) — TargetKernel: как ядро использует TargetSpec
- [target-transport.md](target-transport.md) — HTTP transport: как `OperationSpec.data` компилируется
- [target-provider.md](target-provider.md) — AnkeyTargetProvider: wiring и lazy import
- [DSL Engine](../dsl/dsl-engine.md) — общая DSL-инфраструктура (`DslLoadError`, `read_yaml`)
- `connector/domain/target_dsl/spec_models.py` — исходный код моделей
- `connector/domain/target_dsl/loader.py` — исходный код загрузчика
- `connector/infra/target/core/kernel.py` — TargetKernel: построение lookup-таблиц
- `datasets/targets/ankey.target.yaml` — реальная спецификация провайдера
- `datasets/registry.yml` — центральный реестр targets

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-28 | Cоздана документация Target Core | xORex-LC |
