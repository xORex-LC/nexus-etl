# Target Core — агностическое ядро целевого слоя

> **Назначение**: transport-agnostic механика retry, классификации сбоев, редакции
> секретных данных и разрешения операций. Всё поведение диктуется `TargetSpec`,
> переданным при инициализации. Ядро не знает об HTTP, httpx, Ankey.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Иерархия компонентов](#иерархия-компонентов)
  - [Таблица ответственностей](#таблица-ответственностей)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
  - [RequestSpec](#requestspec)
  - [ExecutionResult](#executionresult)
  - [RequestExecutorProtocol](#requestexecutorprotocol)
  - [TargetPageResult и TargetPagedReaderProtocol](#targetpageresult-и-targetpagedreaderprotocol)
- [🗂️ Модели данных](#️-модели-данных)
  - [Модели ядра (models.py)](#модели-ядра-modelspy)
  - [Spec-модели (domain/target_dsl/spec_models.py)](#spec-модели-domaintarget_dslspec_modelspy)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
  - [TargetKernel — детальный разбор](#targetkernel--детальный-разбор)
  - [Engines subsystem](#engines-subsystem)
  - [TargetGateway — полный разбор](#targetgateway--полный-разбор)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
  - [TargetMutationRegistry](#targetmutationregistry)
  - [TransportCompilerRegistry](#transportcompilerregistry)
  - [TargetRuntime и DefaultTargetRuntime](#targetruntime-и-defaulttargetruntime)
  - [TargetProviderRegistry](#targetproviderregistry)
  - [Factory: build_target_runtime()](#factory-build_target_runtime)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [💡 Типичные сценарии](#-типичные-сценарии)
  - [Сценарий 1: Успешный upsert (200 OK)](#сценарий-1-успешный-upsert-200-ok)
  - [Сценарий 2: Retry при TRANSIENT (503 → 503 → 200)](#сценарий-2-retry-при-transient-503--503--200)
  - [Сценарий 3: Конфликт UUID с мутацией](#сценарий-3-конфликт-uuid-с-мутацией)
  - [Сценарий 4: Throttle с Retry-After](#сценарий-4-throttle-с-retry-after)
  - [Сценарий 5: ESCALATE — немедленная остановка](#сценарий-5-escalate--немедленная-остановка)
- [📌 Важные детали](#-важные-детали)
  - [🚨 Failure Modes](#-failure-modes)
  - [⚠️ Инварианты системы](#️-инварианты-системы)
  - [⏱️ Performance заметки](#️-performance-заметки)
- [🛠️ Тестовое покрытие](#️-тестовое-покрытие)
- [🔗 Связанные документы](#-связанные-документы)
- [📝 История изменений](#-история-изменений)

---

## 📋 Обзор

**Назначение**: реализовывать универсальную механику retry, классификации сбоев и
редакции секретных данных без зависимости от конкретного транспорта или провайдера.

**Ключевая ответственность**:
- **Retry loop** — владение всем циклом повторных попыток (Gateway)
- **Fault classification** — перевод `status_code` / `error_code` → `TargetFaultKind`
- **Retry resolution** — выбор директивы (`NO_RETRY`, `RETRY_BACKOFF`, `RETRY_AFTER`, `ESCALATE`) на основе fault kind
- **Redaction** — маскирование секретных данных в заголовках, payload и теле ответа перед логированием
- **Operation resolution** — поиск `OperationSpec` по alias и компиляция в `CompiledOperation` через transport-компилятор

**Ключевой принцип — mechanism vs rules**:

> «Механика (retry loop, backoff, error normalization, safe logging) живёт в ядре.
> Правила (какой статус = какой FaultKind, когда ретраить, какие поля маскировать)
> описываются декларативно в `TargetSpec` провайдера.»
>
> — ADR TARGET-DEC-003

**Что ядро знает**:

| Концепция | Откуда |
|---|---|
| `TargetSpec` | YAML-спецификация провайдера, загруженная DSL-загрузчиком |
| `TargetFaultKind` | Enum из spec: `AUTH`, `TRANSIENT`, `CONFLICT`, `THROTTLE`, `DATA`, `NOT_FOUND`, `PERMISSION`, `SPEC`, `UNKNOWN` |
| `RetryDirective` | Enum из spec: `NO_RETRY`, `RETRY_BACKOFF`, `RETRY_AFTER`, `ESCALATE` |
| `RequestSpec` / `ExecutionResult` | Domain ports — контракт с delivery |
| `DriverResponse` / `DriverError` | Результат единственной I/O-попытки от Driver |

**Что ядро не знает**:
- `httpx`, `requests` или любой другой HTTP-клиент
- Ankey API, URL-пути, заголовки `X-Ankey-*`, error codes вида `resourceexists`
- Структуры path-template и шаблонов подстановки — это зона transport compiler
- Логику пагинации — только интерфейс `iter_batches()`, реализация в Driver
- Формат сериализации тел запросов и ответов

**Расположение в кодовой базе**:

```
connector/
├── infra/
│   └── target/
│       ├── core/
│       │   ├── kernel.py             # TargetKernel: classify, retry, redact
│       │   ├── gateway.py            # TargetGateway: retry loop owner
│       │   ├── runtime.py            # TargetRuntime Protocol + DefaultTargetRuntime
│       │   ├── factory.py            # build_target_runtime()
│       │   ├── registry.py           # TargetProviderRegistry
│       │   ├── mutations.py          # TargetMutationRegistry
│       │   ├── transport_compiler.py # TransportCompilerRegistry + CompiledOperation
│       │   ├── models.py             # TargetMeta, TargetStats, TargetCheckResult, TargetConnectionConfig
│       │   └── engines/
│       │       ├── error_normalizer.py  # TargetErrorNormalizer
│       │       ├── fault_handler.py     # TargetFaultHandler
│       │       ├── result_builder.py    # TargetResultBuilder
│       │       ├── retry_engine.py      # TargetRetryEngine (tenacity)
│       │       └── safe_logging.py      # TargetSafeLogger (structlog)
│       └── driver.py                 # TargetDriver Protocol, DriverResponse, DriverError
├── domain/
│   ├── target_dsl/
│   │   └── spec_models.py            # TargetSpec, FaultRule, RetryRule, OperationSpec
│   └── ports/target/
│       ├── execution.py              # RequestSpec, ExecutionResult, RequestExecutorProtocol
│       └── read.py                   # TargetPageResult, TargetPagedReaderProtocol
```

**Связанные ADR**:
- **TARGET-DEC-001** — ввод `TargetRuntime` как единой точки входа; разделение Gateway/Driver; typed models
- **TARGET-DEC-003** — plugin-core модель: fault/retry contracts v1, engine-подсистемы, `core`-only runtime mode

---

## 🏗️ Архитектура слоя

### Иерархия компонентов

```
Delivery (import_apply / cache_refresh / check_api)
  |
  | build_target_runtime(api_settings, ...)
  v
TargetRuntime (Protocol — domain port)
  |
  v
DefaultTargetRuntime (facade)
  |── .executor  ──────────────────────────────────────┐
  |── .reader    ──────────────────────────────────────┤
  |── .check()   ──────────────────────────────────────┤
  |── .meta()    (из TargetConnectionConfig)            |
  |── .stats()   (из gateway.get_stats())               |
  |── .reset()   ───────> gateway.reset_stats()         |
  `── .close()   ───────> gateway.close()               |
                                                        |
  v                                                     v
TargetGateway (retry owner)  <─────────────────────────┘
  │  Реализует RequestExecutorProtocol (.execute)
  │  Реализует TargetPagedReaderProtocol (.iter_pages)
  │
  ├── TargetKernel (immutable classifier/resolver)
  │     ├── _fault_by_status: dict[int, TargetFaultKind]
  │     ├── _fault_by_range:  list[tuple[range, TargetFaultKind]]
  │     ├── _fault_by_code:   dict[str, TargetFaultKind]
  │     ├── _retry_rules:     tuple[RetryRule, ...]
  │     └── _compiled_operations: dict[str, CompiledOperation]
  │
  ├── TargetDriver (single-attempt I/O — инжектируется провайдером)
  │     ├── execute(compiled_request, payload) -> DriverResponse | raises DriverError
  │     ├── iter_batches(compiled_request, batch_size, max_batches) -> Iterator[DriverBatch]
  │     └── close() -> None
  │
  ├── Engines (connector/infra/target/core/engines/)
  │     ├── TargetErrorNormalizer  — status/code → NormalizedFault
  │     ├── TargetFaultHandler     — DriverError/Response → FaultContext + error_details
  │     ├── TargetResultBuilder    — ExecutionResult factory (ok/error/spec/unexpected)
  │     ├── TargetRetryEngine      — backoff + jitter через tenacity
  │     └── TargetSafeLogger       — structlog с гарантированной редакцией
  │
  └── TargetMutationRegistry — имя → чистая функция RequestSpec → RequestSpec

TargetProviderRegistry
  └── register / get / get_default -> TargetProvider

build_target_runtime() / build_target_runtime_with_info() (factory.py)
  └── -> TargetRuntimeBuildResult(runtime, target_type, mode)

TransportCompilerRegistry
  └── register(kind, compiler) -> compile(op_spec) -> CompiledOperation
```

### Таблица ответственностей

| Компонент | Файл | Ответственность |
|---|---|---|
| `TargetKernel` | `core/kernel.py` | Классификация сбоев, retry-директивы, redaction, компиляция операций, capabilities |
| `TargetGateway` | `core/gateway.py` | Единственный владелец retry loop; собирает stats; вызывает Driver |
| `TargetDriver` | `driver.py` (Protocol) | Единственная I/O попытка; никогда не ретраит |
| `TargetErrorNormalizer` | `engines/error_normalizer.py` | Raw status/code → `NormalizedFault(fault_kind, system_code)` |
| `TargetFaultHandler` | `engines/fault_handler.py` | `DriverError`/`DriverResponse` → `FaultContext` с redacted деталями |
| `TargetResultBuilder` | `engines/result_builder.py` | Конструирование всех вариантов `ExecutionResult` |
| `TargetRetryEngine` | `engines/retry_engine.py` | Расчёт задержек: экспоненциальный backoff с jitter (tenacity) |
| `TargetSafeLogger` | `engines/safe_logging.py` | Логирование через structlog; payload и headers всегда redacted |
| `TargetMutationRegistry` | `core/mutations.py` | Реестр чистых функций-мутаций `RequestSpec` |
| `TransportCompilerRegistry` | `core/transport_compiler.py` | `OperationSpec` → `CompiledOperation` по transport kind |
| `DefaultTargetRuntime` | `core/runtime.py` | Тонкий фасад: выдаёт executor, reader, check, meta, stats |
| `TargetProviderRegistry` | `core/registry.py` | Реестр провайдеров по `target_type`, выбор default |
| `build_target_runtime()` | `core/factory.py` | Точка входа для сборки всего runtime через provider registry |

---

## 🔑 Ключевые абстракции

Domain ports определены в `connector/domain/ports/target/` — единственный контракт
между delivery/usecase и target-инфраструктурой.

### RequestSpec

```python
# connector/domain/ports/target/execution.py
@dataclass(frozen=True, slots=True)
class RequestSpec:
    operation_alias: str          # обязателен; alias из каталога OperationSpec
    payload: Any | None = None    # бизнес-данные операции (dict, list, None)
    operation_params: Mapping[str, Any] | None = None  # параметры alias (path-params и т.п.)
```

`RequestSpec` — намерение (intent): delivery описывает, что нужно сделать (`operation_alias`),
с какими параметрами (`operation_params`) и с каким телом (`payload`). Ядро не знает,
что именно скрывается за alias — это определяется `OperationSpec` в `TargetSpec`.

Дополнительно:
- `RequestSpec.operation(alias, *, payload, params)` — фабричный метод для удобного создания
- `__post_init__` гарантирует непустой `operation_alias` и немедленное копирование `operation_params` в dict
- `frozen=True` — неизменяем; мутации при retry создают новый объект

### ExecutionResult

```python
# connector/domain/ports/target/execution.py
@dataclass(frozen=True, slots=True)
class ExecutionResult:
    ok: bool
    answer_code: int | str | None = None        # HTTP-статус или transport code
    response_payload: Any | None = None         # redacted тело ответа
    response_format: ResponsePayloadFormat = "none"  # "json", "text", "bytes", "rows", "object", "none"
    error_code: SystemErrorCode | None = None   # доменный код ошибки
    error_message: str | None = None            # человекочитаемое сообщение (truncated)
    error_reason: str | None = None             # машиночитаемая причина (из ответа target)
    error_details: dict[str, Any] | None = None # redacted диагностические детали
```

**Ключевой инвариант**: `execute()` в `TargetGateway` **никогда не бросает исключений наружу**.
Всегда возвращает `ExecutionResult`. Delivery работает только с этим объектом.

| Поле | При `ok=True` | При `ok=False` |
|---|---|---|
| `answer_code` | HTTP-статус (200, 201, …) | HTTP-статус ошибки или transport code |
| `response_payload` | redacted тело ответа | `None` |
| `error_code` | `None` | `SystemErrorCode` (AUTH_UNAUTHORIZED, DATA_INVALID, …) |
| `error_details` | `None` | Redacted диагностические данные (опционально) |
| `error_reason` | `None` | Строка из тела ответа (например, `"resourceexists"`) |

### RequestExecutorProtocol

```python
# connector/domain/ports/target/execution.py
class RequestExecutorProtocol(Protocol):
    def execute(self, spec: RequestSpec) -> ExecutionResult: ...
```

Delivery-команда `import_apply` взаимодействует только с этим протоколом.
`TargetGateway` структурно удовлетворяет ему. Delivery получает executor через `runtime.executor`.

### TargetPageResult и TargetPagedReaderProtocol

```python
# connector/domain/ports/target/read.py
@dataclass(frozen=True)
class TargetPageResult:
    ok: bool
    page: int
    items: list[dict[str, Any]] | None   # None при ok=False
    error_code: SystemErrorCode | None = None
    error_message: str | None = None
    error_details: dict[str, Any] | None = None

class TargetPagedReaderProtocol(Protocol):
    def iter_pages(
        self,
        operation_alias: str,
        page_size: int,
        max_pages: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterable[TargetPageResult]: ...
```

Используется в `cache_refresh` для постраничного чтения из target-системы.
`TargetGateway` структурно удовлетворяет этому протоколу.

При `ok=True` — `items` содержит записи страницы (после `maskSecretsInObject`).
При `ok=False` — `items=None`, заполнены `error_*` поля. Итератор никогда не бросает исключений.

---

## 🗂️ Модели данных

### Модели ядра (models.py)

```python
# connector/infra/target/core/models.py

TargetFaultKind = Literal[
    "SPEC", "AUTH", "PERMISSION", "DATA", "NOT_FOUND",
    "CONFLICT", "THROTTLE", "TRANSIENT", "UNKNOWN",
]

@dataclass(frozen=True, slots=True)
class TargetMeta:
    target_type: str        # "ankey" или другой провайдер
    transport: str          # "http" или другой транспорт
    endpoint: str | None    # базовый URL target-системы

@dataclass(frozen=True, slots=True)
class TargetStats:
    requests_total: int = 0   # попытки execute + успешные страницы read
    retries_total: int = 0    # повторы, выполненные gateway
    failures_total: int = 0   # операции, завершившиеся неуспехом

@dataclass(frozen=True, slots=True)
class TargetCheckResult:
    ok: bool
    latency_ms: int | None = None              # None если попытки не было
    fault_kind: TargetFaultKind | None = None  # None при ok=True
    error_code: SystemErrorCode | None = None  # None при ok=True
    error_message: str | None = None

@dataclass(frozen=True, slots=True)
class TargetConnectionConfig:
    target_type: str
    endpoint: str
    transport: str
    principal: str = ""   # идентификатор service account (для метаданных)
```

Все модели `frozen=True` — immutable dataclasses. `slots=True` — оптимизация памяти.
Используются на границе `runtime ↔ delivery` без раскрытия внутренних деталей gateway.

Семантика счётчиков `TargetStats`:

| Счётчик | Что считает |
|---|---|
| `requests_total` | Число попыток `driver.execute()` + успешно выданных страниц read |
| `retries_total` | Число повторов (только успешно запланированных) |
| `failures_total` | Число завершившихся неуспехом **операций** (не попыток!) |

Пример: `503 → 503 → 200` → `stats: (3, 2, 0)` — 3 попытки, 2 повтора, 0 провалов.
Пример: `NETWORK_ERROR × 3` при budget=2 → `stats: (3, 2, 1)` — операция провалилась.

### Spec-модели (domain/target_dsl/spec_models.py)

Source of truth — `connector/domain/target_dsl/spec_models.py`. Файл
`connector/infra/target/core/spec_models.py` — compatibility re-export для исторических import-путей.

Все spec-модели наследуют `_SpecModel(BaseModel)` с `extra="forbid", frozen=True`.

```python
TargetFaultKind = Literal[
    "SPEC", "AUTH", "PERMISSION", "DATA", "NOT_FOUND",
    "CONFLICT", "THROTTLE", "TRANSIENT", "UNKNOWN",
]
TargetCapability = Literal["check", "execute", "read_paged"]
RetryDirective = Literal["NO_RETRY", "RETRY_BACKOFF", "RETRY_AFTER", "ESCALATE"]

class FaultRule(_SpecModel):
    fault_kind: TargetFaultKind
    match_status: int | None = None              # точный HTTP-статус
    match_status_range: tuple[int, int] | None   # диапазон [low, high]
    match_error_code: str | None = None          # строковый код ошибки

class RetryRule(_SpecModel):
    directive: RetryDirective
    match_fault: TargetFaultKind | None = None
    match_status: int | None = None
    match_reason: str | None = None   # нормализуется в lowercase
    mutation: str | None = None       # имя мутации (или None)

class RetryConfig(_SpecModel):
    max_attempts: int = 3
    backoff_base: float = 0.5    # базовая задержка, сек
    backoff_max: float = 30.0    # максимальная задержка, сек
    jitter: bool = True

class OperationSpec(_SpecModel):
    alias: str
    kind: str = "http"
    expected_statuses: tuple[int, ...] = (200,)
    timeout_ms: int | None = None
    retry_profile: str | None = None
    redaction_override: dict[str, Any] | None = None
    data: dict[str, Any] = {}      # transport-specific payload (opaque для core)

class RedactionSpec(_SpecModel):
    forbidden_metadata_keys: frozenset[str]  # заголовки для маскирования
    forbidden_fields: frozenset[str]         # поля payload для маскирования
    body_mode: Literal["none", "keys_only", "truncated"] = "truncated"

class HealthSpec(_SpecModel):
    operation_alias: str = "health.check"

class TargetSpec(_SpecModel):
    target_type: str
    capabilities: frozenset[TargetCapability]
    fault_rules: tuple[FaultRule, ...]
    retry_rules: tuple[RetryRule, ...]
    retry_config: RetryConfig
    redaction: RedactionSpec
    health: HealthSpec
    operations: dict[str, OperationSpec] = {}
```

`TargetSpec._validate_spec_integrity()` проверяет инварианты при Pydantic-парсинге:
- `health` требует capability `check`
- `health.operation_alias` должен присутствовать в `operations`
- ключи `operations` должны совпадать с `alias` внутри `OperationSpec`

---

## 📊 Ключевые методы и алгоритмы

### TargetKernel — детальный разбор

**Файл**: `connector/infra/target/core/kernel.py`

`TargetKernel` — immutable classifier. Создаётся один раз при сборке runtime и не
изменяется в течение всего lifetime. Построение lookup-таблиц при инициализации
обеспечивает O(1) / O(n fault_rules) поиск во время выполнения.

#### Инициализация lookup-таблиц

```python
class TargetKernel:
    def __init__(self, spec: TargetSpec, compiler_registry: TransportCompilerRegistry) -> None:
        self._spec = spec

        # --- FAULT LOOKUP TABLES ---
        # O(1) поиск по точному статусу
        self._fault_by_status: dict[int, TargetFaultKind] = {
            rule.match_status: rule.fault_kind
            for rule in spec.fault_rules
            if rule.match_status is not None
        }
        # Линейный поиск по диапазонам (обычно 1-2 правила, например 5xx -> TRANSIENT)
        self._fault_by_range: list[tuple[range, TargetFaultKind]] = [
            (range(rule.match_status_range[0], rule.match_status_range[1] + 1), rule.fault_kind)
            for rule in spec.fault_rules
            if rule.match_status_range is not None
        ]
        # O(1) поиск по строковому error_code (например "NETWORK_ERROR")
        self._fault_by_code: dict[str, TargetFaultKind] = {
            rule.match_error_code.upper(): rule.fault_kind
            for rule in spec.fault_rules
            if rule.match_error_code is not None
        }
        # Retry-правила: линейный поиск с первым совпадением
        self._retry_rules: tuple[RetryRule, ...] = spec.retry_rules

        # --- COMPILED OPERATIONS ---
        # Все операции компилируются при инициализации, не при каждом вызове
        self._compiled_operations: dict[str, CompiledOperation] = {
            alias: compiler_registry.compile(op_spec)
            for alias, op_spec in spec.operations.items()
        }
```

#### classify_fault(status_code, error_code) → TargetFaultKind

Классификация сбоя. **Приоритет**: `error_code` → `status` (точный) → `status` (диапазон) → `"UNKNOWN"`.

```python
def classify_fault(
    self,
    status_code: int | None,
    error_code: str | None = None,
) -> TargetFaultKind:
    # Шаг 1: строковый error_code (высший приоритет — транспортная ошибка)
    if error_code is not None:
        found = self._fault_by_code.get(error_code.upper())
        if found is not None:
            return found

    if status_code is not None:
        # Шаг 2: точное совпадение статуса
        found = self._fault_by_status.get(status_code)
        if found is not None:
            return found

        # Шаг 3: диапазон статусов (например, 500-599 → TRANSIENT)
        for status_range, fault_kind in self._fault_by_range:
            if status_code in status_range:
                return fault_kind

    return "UNKNOWN"
```

Примеры классификации (конфигурация Ankey):

| Вызов | Результат | Причина |
|---|---|---|
| `classify_fault(401)` | `"AUTH"` | точный match_status=401 |
| `classify_fault(503)` | `"TRANSIENT"` | диапазон 500-599 |
| `classify_fault(None, "NETWORK_ERROR")` | `"TRANSIENT"` | match_error_code |
| `classify_fault(401, "NETWORK_ERROR")` | `"TRANSIENT"` | error_code приоритетнее статуса |
| `classify_fault(418)` | `"UNKNOWN"` | нет совпадений |

#### resolve_retry_action(fault_kind, status_code, error_reason) → ResolvedRetryAction

Линейный поиск по `retry_rules`. Возвращает **первое совпавшее** правило.

```python
def resolve_retry_action(
    self,
    fault_kind: TargetFaultKind,
    status_code: int | None = None,
    error_reason: str | None = None,
) -> ResolvedRetryAction:
    normalized_reason = error_reason.lower() if error_reason else None

    for rule in self._retry_rules:
        # Все активные matchers должны совпасть (AND-логика)
        if rule.match_fault is not None and rule.match_fault != fault_kind:
            continue
        if rule.match_status is not None and rule.match_status != status_code:
            continue
        if rule.match_reason is not None and rule.match_reason != normalized_reason:
            continue
        # Первое полное совпадение
        return ResolvedRetryAction(directive=rule.directive, mutation=rule.mutation)

    # Ни одно правило не совпало — без retry
    return ResolvedRetryAction(directive="NO_RETRY", mutation=None)
```

Примеры (конфигурация Ankey):

| fault_kind | status | reason | Результат |
|---|---|---|---|
| `"TRANSIENT"` | 503 | `None` | `RETRY_BACKOFF` |
| `"THROTTLE"` | 429 | `None` | `RETRY_AFTER` |
| `"CONFLICT"` | 409 | `"resourceexists"` | `RETRY_BACKOFF + mutation="regenerate_target_id"` |
| `"CONFLICT"` | 409 | `None` | `NO_RETRY` (reason не совпал) |
| `"AUTH"` | 401 | `None` | `NO_RETRY` (нет правила для AUTH) |

#### system_error_code(fault_kind) → SystemErrorCode

Маппинг `TargetFaultKind` → `SystemErrorCode` для `ExecutionResult`:

| TargetFaultKind | SystemErrorCode |
|---|---|
| `"SPEC"` | `INTERNAL_ERROR` |
| `"AUTH"` | `AUTH_UNAUTHORIZED` |
| `"PERMISSION"` | `AUTH_FORBIDDEN` |
| `"DATA"` | `DATA_INVALID` |
| `"NOT_FOUND"` | `NOT_FOUND` |
| `"CONFLICT"` | `CONFLICT` |
| `"THROTTLE"` | `RATE_LIMITED` |
| `"TRANSIENT"` | `INFRA_UNAVAILABLE` |
| `"UNKNOWN"` | `INTERNAL_ERROR` |

#### Остальные методы TargetKernel

**`resolve_operation(alias) → OperationSpec`** — поиск в `spec.operations` по alias.
`KeyError` → `ValueError` с понятным сообщением.

**`get_compiled_operation(alias) → tuple[OperationSpec, CompiledOperation]`** — возвращает
пару из оригинального `OperationSpec` и скомпилированного объекта транспорта.
Compile происходит при инициализации, не при каждом вызове — O(1) lookup.

**`has_capability(cap) → bool`** / **`require_capability(cap)`** — проверка наличия capability.
`require_capability` бросает `ValueError` при отсутствии.

**`health_operation_alias() → str`** — возвращает `spec.health.operation_alias`.

**Методы редакции**:

```python
def redact_headers(self, headers: dict[str, str]) -> dict[str, str]:
    # forbidden_metadata_keys (case-insensitive) -> значение заменяется на "***"
    ...

def redact_payload(self, payload: Any) -> Any:
    # maskSecretsInObject (глубокое маскирование) + forbidden_fields -> "***"
    ...

def safe_body(self, body: Any) -> str | None:
    # body_mode="none"     -> None (тело не логируется)
    # body_mode="keys_only"-> список ключей dict (только структура)
    # body_mode="truncated"-> str(body)[:N] (первые N символов)
    ...
```

---

### Engines subsystem

**Каталог**: `connector/infra/target/core/engines/`

Пять специализированных компонентов, созданных и скомпонованных в `TargetGateway.__init__`.

#### TargetErrorNormalizer (error_normalizer.py)

Мост между raw transport outcome и domain error:

```python
class TargetErrorNormalizer:
    def from_status(self, status_code: int | None) -> NormalizedFault:
        fault_kind = self._kernel.classify_fault(status_code)
        error_code = self._kernel.system_error_code(fault_kind)
        return NormalizedFault(fault_kind=fault_kind, system_code=error_code)

    def from_status_or_code(
        self, status_code: int | None, error_code: str | None
    ) -> NormalizedFault:
        fault_kind = self._kernel.classify_fault(status_code, error_code)
        system_code = self._kernel.system_error_code(fault_kind)
        return NormalizedFault(fault_kind=fault_kind, system_code=system_code)
```

`NormalizedFault` — промежуточный объект: `fault_kind` (из TargetSpec) + `system_code` (доменный код ошибки).

#### TargetFaultHandler (fault_handler.py)

Классификатор входящих результатов Driver. Два основных метода:

```python
def from_driver_response(self, resp: DriverResponse) -> tuple[NormalizedFault, ResolvedRetryAction]:
    # resp.ok == False: статус не входит в expected_statuses
    normalized = self._normalizer.from_status(resp.answer_code)
    retry_action = self._kernel.resolve_retry_action(
        normalized.fault_kind, resp.answer_code, resp.error_reason
    )
    return normalized, retry_action

def from_driver_error(self, exc: DriverError) -> tuple[NormalizedFault, ResolvedRetryAction]:
    # DriverError: сетевой сбой или transport-уровень ошибка
    normalized = self._normalizer.from_status_or_code(exc.status_code, exc.error_code)
    retry_action = self._kernel.resolve_retry_action(
        normalized.fault_kind, exc.status_code, exc.error_reason
    )
    return normalized, retry_action
```

Также строит `error_details` через `build_resp_details()` и `build_exc_details()` с
redaction через `TargetSafeLogger.build_error_details()`. Метод `mark_escalated(details)`
добавляет `{"escalated": True}` при `ESCALATE` директиве.

#### TargetResultBuilder (result_builder.py)

Конструирует все варианты `ExecutionResult`:

```python
class TargetResultBuilder:
    def execute_success(self, resp: DriverResponse) -> ExecutionResult:
        # ok=True; response_payload -> safe_body(resp.payload) [REDACTION]
        ...

    def from_response_error(
        self, resp: DriverResponse, normalized: NormalizedFault, details: dict | None
    ) -> ExecutionResult:
        # ok=False; заполняет error_code, error_reason, error_details
        ...

    def from_driver_error(
        self, exc: DriverError, normalized: NormalizedFault, details: dict | None
    ) -> ExecutionResult:
        # ok=False; источник — сетевой сбой или transport error
        ...

    def spec_error(self, message: str) -> ExecutionResult:
        # ok=False; error_code=INTERNAL_ERROR; spec/validation ошибка
        ...

    def unexpected_failure(self, exc: Exception) -> ExecutionResult:
        # ok=False; error_code=INFRA_UNAVAILABLE; непойманное исключение
        ...
```

#### TargetRetryEngine (retry_engine.py)

Управляет расчётом и исполнением задержек через tenacity utilities:

```python
class TargetRetryEngine:
    def __init__(self, config: RetryConfig, sleep_fn=time.sleep) -> None:
        # Инициализирует tenacity wait_strategy: exponential backoff + optional jitter
        ...

    @property
    def max_retries(self) -> int:
        return self._config.max_attempts

    def can_retry(self, retries_used: int) -> bool:
        return retries_used < self._config.max_attempts

    def sleep_before_retry(self, retries_used: int) -> float:
        # Рассчитывает и исполняет exponential backoff задержку
        attempt_number = max(1, retries_used)
        delay = float(self._wait_strategy(_RetryAttemptState(attempt_number=attempt_number)))
        if delay > 0:
            self._sleep_fn(delay)
        return delay

    def sleep_exact(self, delay_s: float | None) -> float:
        # Точная задержка для RETRY_AFTER (из Retry-After заголовка)
        ...
```

`can_retry(retries_used=0)` — до первого повтора. При бюджете `max_attempts=3` разрешены повторы 1, 2, 3.

Задержки для конфигурации по умолчанию (`backoff_base=0.5`, `backoff_max=30.0`):

| retries_used | Примерная задержка |
|---|---|
| 1 (первый retry) | ~0.5 сек |
| 2 | ~1.0 сек |
| 3 | ~2.0 сек |
| 4 | ~4.0 сек |
| 5+ | ≤ 30.0 сек |

С `jitter=True` к базовому времени добавляется случайная составляющая `[0, backoff_base)`,
снижая thundering herd при одновременном retry множества операций.

#### TargetSafeLogger (safe_logging.py)

structlog-based логгер с гарантированной редакцией перед любой записью в лог.
Если `structlog` не установлен — все методы становятся no-op (защитный `try/except`-импорт).

```python
class TargetSafeLogger:
    def log_response_error(
        self, *, operation: str, answer_code: int | str | None,
        fault_kind: str, payload: Any, content_preview: str | None,
    ) -> None:
        # WARNING; payload -> safe_body() [REDACTION] перед включением в лог

    def debug_retry(
        self, *, operation: str, fault_kind: str, retries_used: int,
        max_retries: int, delay_s: float, mutation: str | None = None,
    ) -> None:
        # DEBUG; только операционные метрики — бизнес-данные не включаются

    def build_error_details(
        self, *, payload: Any, content_preview: str | None,
    ) -> dict[str, Any] | None:
        # payload -> safe_body -> "response_payload" в details
        # content_preview -> truncateText; None если ни одного значения нет
```

**Инвариант**: ни один вызов `TargetSafeLogger` не пропускает credentials или секретные данные
в структурированный лог. Весь payload проходит через `kernel.safe_body()`.

---

### TargetGateway — полный разбор

**Файл**: `connector/infra/target/core/gateway.py`

`TargetGateway` — единственный владелец retry-политики. Это самый сложный компонент ядра.
Driver никогда не ретраит. Gateway никогда не бросает исключений наружу.

#### Инициализация и зависимости

```python
class TargetGateway:
    def __init__(
        self,
        driver: TargetDriver[Any],
        kernel: TargetKernel,
        *,
        mutation_registry: TargetMutationRegistry | None = None,
    ) -> None:
        self._driver = driver
        self._kernel = kernel
        self._mutations = mutation_registry or TargetMutationRegistry()
        self._retry_engine = TargetRetryEngine(kernel.spec.retry_config)
        safe_logger = TargetSafeLogger(kernel, logger_name=__name__)
        normalizer = TargetErrorNormalizer(kernel)
        self._safe_logger = safe_logger
        self._fault_handler = TargetFaultHandler(kernel, normalizer, safe_logger)
        self._result_builder = TargetResultBuilder(kernel, safe_logger)
        # Счётчики статистики
        self._requests_total: int = 0
        self._retries_total: int = 0
        self._failures_total: int = 0
```

Структурно реализует `RequestExecutorProtocol` (`.execute`) и `TargetPagedReaderProtocol` (`.iter_pages`).

#### execute(spec: RequestSpec) → ExecutionResult

**Контракт: никогда не бросает исключений наружу.**

```
execute(spec)
  │
  ├─> require_capability("execute")
  │     ValueError? -> spec_error, failures++, RETURN
  │
  └═══[ RETRY LOOP ]══════════════════════════════════════╗
       │                                                   ║
       ├─> get_compiled_operation(alias) + compiled.build  ║
       │     ValueError? -> spec_error, failures++, RETURN ║
       │     Exception?  -> unexpected, failures++, RETURN  ║
       │     requests_total++                               ║
       │                                                    ║
       ├─> driver.execute(compiled_request, payload)        ║
       │     │                                              ║
       │     ├─> resp.ok == True                            ║
       │     │     -> execute_success(resp) -> RETURN ✓     ║
       │     │                                              ║
       │     ├─> resp.ok == False                           ║
       │     │     fault_handler.from_driver_response(resp) ║
       │     │     log_response_error(...) [WARNING]        ║
       │     │                                              ║
       │     ├─> DriverError raised                         ║
       │     │     fault_handler.from_driver_error(exc)     ║
       │     │                                              ║
       │     └─> Exception (unexpected)                     ║
       │           -> unexpected_failure, failures++, RETURN║
       │                                                    ║
       ├─> _apply_execute_retry(...)                        ║
       │     directive NOT in {RETRY_BACKOFF, RETRY_AFTER}? ║
       │       -> should_retry=False (NO_RETRY/ESCALATE)    ║
       │     retries_used >= max_attempts?                  ║
       │       -> should_retry=False (бюджет исчерпан)      ║
       │     иначе:                                         ║
       │       mutation? -> current_spec = mutations.apply  ║
       │       retries_used++, retries_total++              ║
       │       compute_retry_delay(directive, retry_after_s)║
       │       safe_logger.debug_retry(...)                 ║
       │       -> should_retry=True ──────────────────────>>╝
       │
       └─> should_retry==False
             failures_total++
             make_error() -> RETURN ✗
```

Важная деталь реализации: переменная-замыкание `make_error` (lambda) создаётся **после** получения
результата от Driver. Это позволяет отложить создание `ExecutionResult` до тех пор, пока не станет
ясно, будет ли повтор. Ссылка `captured = exc` сохраняется явно, потому что Python очищает
переменную из `except as` после блока исключения.

#### _apply_execute_retry (внутренний метод)

```python
def _apply_execute_retry(
    self, *, operation: str, fault_kind: str,
    retry_action: ResolvedRetryAction, retries_used: int,
    current_spec: RequestSpec, retry_after_s: float | None = None,
) -> tuple[bool, int, RequestSpec]:
    directive = retry_action.directive
    if directive not in {"RETRY_BACKOFF", "RETRY_AFTER"}:
        return False, retries_used, current_spec   # NO_RETRY или ESCALATE
    if not self._retry_engine.can_retry(retries_used):
        return False, retries_used, current_spec   # бюджет исчерпан

    if retry_action.mutation is not None:
        current_spec = self._mutations.apply(retry_action.mutation, current_spec)

    retries_used += 1
    self._retries_total += 1
    delay = self._compute_retry_delay(directive, retry_after_s, retries_used)
    self._safe_logger.debug_retry(...)
    return True, retries_used, current_spec
```

Мутация применяется **до** инкремента `retries_used`. Если мутация не зарегистрирована — `ValueError`,
перехватывается в `execute()` → `spec_error`.

`ESCALATE` не входит в `{"RETRY_BACKOFF", "RETRY_AFTER"}` → `should_retry=False` немедленно.
Отличие от `NO_RETRY`: при `ESCALATE` в `error_details` добавляется `{"escalated": True}`.

#### _compute_retry_delay

```python
def _compute_retry_delay(
    self, directive: str, retry_after_s: float | None, retries_used: int,
) -> float:
    if directive == "RETRY_AFTER" and retry_after_s is not None:
        return self._retry_engine.sleep_exact(retry_after_s)
    return self._retry_engine.sleep_before_retry(retries_used)
```

- `RETRY_AFTER` → точная задержка из заголовка `Retry-After`
- `RETRY_BACKOFF` → экспоненциальный backoff с jitter

#### iter_pages(operation_alias, page_size, max_pages, params) → Iterable[TargetPageResult]

**Ключевое архитектурное решение**: retry выполняется **только** если ни одна страница
ещё не была выдана (`last_page == 0`). После выдачи хотя бы одной страницы — ошибка
транслируется в `TargetPageResult(ok=False)` напрямую без повтора.

**Причина**: идемпотентность. Если первые N страниц уже переданы в `cache_refresh`,
повтор начнёт отдавать страницы с начала — данные продублируются в кэше.

```
iter_pages(alias, page_size, max_pages, params)
  1. require_capability("read_paged")
     get_compiled_operation(alias)
     compiled.build(alias, query_overrides=params)
     Errors -> failures++, yield _fail_page(SPEC, message), return

  2. LOOP:
     driver.iter_batches(compiled_request, page_size, max_pages):
       for page, items in batches:
         requests_total++
         last_page = page
         safe_items = maskSecretsInObject(items)
         yield TargetPageResult(ok=True, page=page, items=safe_items)
     return (успех)

     DriverError:
       if last_page == 0:  <- только до первой страницы
         should_retry, retries_used = _apply_read_retry(...)
         if should_retry: continue LOOP
       failures++
       yield TargetPageResult(ok=False, error_code=...), return

     Exception (unexpected):
       failures++
       yield TargetPageResult(ok=False, INFRA_UNAVAILABLE, message), return
```

Items каждой страницы немедленно проходят через `maskSecretsInObject` — данные из
target-системы могут содержать поля `password`, `token` и т.п.

Мутации в `_apply_read_retry` **не поддерживаются**: при read-операциях нечего мутировать.

#### health_check() → TargetCheckResult

```python
def health_check(self) -> TargetCheckResult:
    try:
        self._kernel.require_capability("check")
        operation_alias = self._kernel.health_operation_alias()
        _, compiled = self._kernel.get_compiled_operation(operation_alias)
        compiled_request = compiled.build(alias=operation_alias)
    except ValueError as exc:
        return TargetCheckResult(ok=False, fault_kind="SPEC", ...)

    start = time.monotonic()
    # ... один вызов driver.execute(compiled_request, None) ...
    latency_ms = int((time.monotonic() - start) * 1000)
    # ... возвращает TargetCheckResult ...
```

Health-check **не ретраит**: одна попытка, `latency_ms` через `time.monotonic()`.
Неожиданные `Exception` классифицируются как `TRANSIENT` / `INFRA_UNAVAILABLE`.

Для Ankey-провайдера `health_operation_alias()` возвращает `"health.check"`,
компилируется в `GET /ankey/managed/user`.

---

## 🔄 Взаимодействие с другими слоями

### TargetMutationRegistry

**Файл**: `connector/infra/target/core/mutations.py`

Реестр чистых функций-мутаций `RequestSpec`. Мутация — **чистая функция**: принимает
`RequestSpec`, возвращает **новый** `RequestSpec`. Оригинал не изменяется.

```python
TargetMutation = Callable[[RequestSpec], RequestSpec]

class TargetMutationRegistry:
    def register(self, name: str, mutation: TargetMutation) -> None:
        # Дубликат -> ValueError; пустое имя -> ValueError
        ...

    def apply(self, name: str, request_spec: RequestSpec) -> RequestSpec:
        # Неизвестное имя -> ValueError (перехватывается Gateway -> spec_error)
        ...
```

Gateway заменяет `current_spec`:

```python
current_spec = self._mutations.apply(retry_action.mutation, current_spec)
```

Создаётся провайдером (например, `build_ankey_mutations()`) и передаётся в конструктор
`TargetGateway`. Если мутации не нужны — передаётся пустой `TargetMutationRegistry()`.

**Пример мутации `regenerate_target_id`** (из Ankey-провайдера):

```python
def regenerate_target_id(spec: RequestSpec) -> RequestSpec:
    new_params = dict(spec.operation_params or {})
    new_params["target_id"] = str(uuid.uuid4())
    return RequestSpec(
        operation_alias=spec.operation_alias,
        payload=spec.payload,
        operation_params=new_params,
    )
```

При retry с `CONFLICT + reason=resourceexists`: UUID записи уже занят в target.
Мутация генерирует новый UUID → Gateway повторяет запрос с другим path-параметром
→ `PUT /ankey/managed/user/<new-uuid>`.

---

### TransportCompilerRegistry

**Файл**: `connector/infra/target/core/transport_compiler.py`

Реестр компиляторов: `operation.kind` → функция-компилятор. Разделяет ядро от
конкретного транспорта.

```python
class CompiledOperation(Protocol[TCompiledRequest]):
    def build(
        self,
        *,
        alias: str,
        operation_params: dict[str, Any] | None = None,
        query_overrides: dict[str, Any] | None = None,
        header_overrides: dict[str, str] | None = None,
    ) -> TCompiledRequest: ...

class TransportCompilerRegistry:
    def register(self, kind: str, compiler: OperationCompiler) -> None:
        # kind нормализуется в lowercase; дубликаты не запрещены (перезаписывают)
        ...

    def compile(self, operation: OperationSpec) -> CompiledOperation[Any]:
        # Ищет компилятор по operation.kind; ValueError если не зарегистрирован
        ...
```

HTTP-компилятор регистрируется провайдером при сборке:

```python
# В AnkeyTargetProvider.build_core_runtime():
registry = TransportCompilerRegistry()
registry.register("http", compile_http_operation)
```

`compile(operation)` вызывается при инициализации `TargetKernel` для каждой операции.
Результат (`CompiledOperation`) хранится в `_compiled_operations` ядра и передаётся в
Driver при каждом вызове execute.

Параметры `CompiledOperation.build()`:

| Параметр | Источник | Назначение |
|---|---|---|
| `alias` | `RequestSpec.operation_alias` | Идентификатор операции |
| `operation_params` | `RequestSpec.operation_params` | Подстановка в path template (`{target_id}`) |
| `query_overrides` | `params` из `iter_pages` | Дополнительные query-параметры |
| `header_overrides` | Опционально | Переопределение заголовков |

---

### TargetRuntime и DefaultTargetRuntime

**Файл**: `connector/infra/target/core/runtime.py`

```python
# TargetRuntime — domain port; delivery импортирует только этот Protocol
class TargetRuntime(Protocol):
    @property
    def executor(self) -> RequestExecutorProtocol: ...

    @property
    def reader(self) -> TargetPagedReaderProtocol | None: ...

    def check(self) -> TargetCheckResult: ...
    def meta(self) -> TargetMeta: ...
    def stats(self) -> TargetStats: ...
    def reset(self) -> None: ...
    def close(self) -> None: ...
```

`TargetRuntime` — граница зависимости для delivery. Delivery-команды работают только с
этим Protocol и никогда не импортируют `DefaultTargetRuntime` напрямую. Это позволяет
подменять stub/mock runtime в тестах без патчинга конкретных классов инфраструктуры.

```python
class DefaultTargetRuntime:
    def __init__(
        self, *, gateway: TargetGateway, config: TargetConnectionConfig, has_reader: bool = True
    ) -> None: ...

    @property
    def executor(self) -> RequestExecutorProtocol:
        return self._gateway  # структурное соответствие

    @property
    def reader(self) -> TargetPagedReaderProtocol | None:
        return self._gateway if self._has_reader else None

    def meta(self) -> TargetMeta:
        return TargetMeta(
            target_type=self._config.target_type,
            transport=self._config.transport,
            endpoint=self._config.endpoint,
        )

    def stats(self) -> TargetStats:
        req, ret, fail = self._gateway.get_stats()
        return TargetStats(requests_total=req, retries_total=ret, failures_total=fail)
```

`DefaultTargetRuntime` — тонкая обёртка. Вся логика в Gateway. Runtime только маршрутизирует
вызовы и конструирует typed response objects.

Флаг `has_reader=True` управляет тем, возвращает ли `runtime.reader` gateway (для
режима с чтением из target-системы) или `None` (только write-режим).

---

### TargetProviderRegistry

**Файл**: `connector/infra/target/core/registry.py`

```python
class TargetProviderRegistry:
    def register(self, provider: TargetProvider, *, default: bool = False) -> None:
        # Дубликат -> ValueError
        # Первый зарегистрированный автоматически становится default
        ...

    def get(self, target_type: str) -> TargetProvider:
        # Не найден -> MissingTargetProviderError с перечнем известных
        ...

    def get_default(self) -> TargetProvider:
        # Нет default -> MissingTargetProviderError
        ...
```

В production-конфигурации реестр содержит единственный провайдер: `ankey`.

---

### Factory: build_target_runtime()

**Файл**: `connector/infra/target/core/factory.py`

```python
def build_target_runtime(
    api_settings: ApiSettings,
    *,
    transport: object | None = None,
    include_reader: bool = True,
    runtime_mode: str | None = None,
    target_type: str | None = None,
) -> TargetRuntime: ...

def build_target_runtime_with_info(
    api_settings: ApiSettings,
    *,
    transport: object | None = None,
    include_reader: bool = True,
    runtime_mode: str | None = None,
    target_type: str | None = None,
) -> TargetRuntimeBuildResult: ...
```

`build_target_runtime` — упрощённый фасад. `build_target_runtime_with_info` — полная
версия с метаданными выбора.

Алгоритм сборки:

```
1. _resolve_runtime_mode(runtime_mode)
   -> нормализует строку (strip + lower)
   -> проверяет допустимые значения: {"core"} (единственный режим)
   -> ValueError если передан неизвестный режим

2. build_default_target_provider_registry(api_settings)
   -> строит реестр с AnkeyTargetProvider (default)

3. target_type задан?
   -> registry.get(target_type)
   иначе:
   -> registry.get_default()

4. provider.build_core_runtime(transport=transport, include_reader=include_reader)
   -> DefaultTargetRuntime (kernel + gateway + driver + engines + mutations)

5. return TargetRuntimeBuildResult(
       runtime=runtime,
       target_type=provider.target_type,
       requested_mode=requested_mode,
       effective_mode="core",
   )
```

```python
@dataclass(frozen=True)
class TargetRuntimeBuildResult:
    runtime: TargetRuntime
    target_type: str
    requested_mode: TargetRuntimeMode           # "core" (единственный)
    effective_mode: EffectiveTargetRuntimeMode  # "core" (всегда)
```

Параметр `transport` позволяет инжектировать внешний transport-объект (тестовый
`httpx.Client`) вместо создания нового. При `transport=None` провайдер создаёт transport
самостоятельно.

---

## 🔌 Контракты и границы

**TargetDriver Protocol** (`connector/infra/target/driver.py`):

```python
class TargetDriver(Protocol[TCompiledRequest]):
    def execute(
        self, compiled_request: TCompiledRequest, payload: Any | None
    ) -> DriverResponse: ...
    # Если ошибка — raises DriverError (не возвращает ErrorResponse)

    def iter_batches(
        self, compiled_request: TCompiledRequest, batch_size: int, max_batches: int | None
    ) -> Iterator[DriverBatch]: ...

    def close(self) -> None: ...
```

```python
@dataclass(frozen=True)
class DriverResponse:
    ok: bool                          # True если status in expected_statuses
    answer_code: int | None           # HTTP-статус
    payload: Any | None               # тело ответа (parsed JSON или None)
    content_preview: str | None       # первые 200 символов тела (для логов)
    error_reason: str | None          # машиночитаемая причина (например "resourceexists")
    retry_after_s: float | None       # значение Retry-After заголовка в секундах

@dataclass(frozen=True)
class DriverError(Exception):
    error_code: str                   # "NETWORK_ERROR", "TIMEOUT", "SSL_ERROR" и т.п.
    message: str
    error_reason: str | None = None
    retry_after_s: float | None = None
    status_code: int | None = None
```

**Ключевые ограничения Driver**:
- **Никогда не ретраит** — только один I/O-вызов на каждый вызов `execute()`
- **Не нормализует ошибки** в domain types — только raw transport outcome
- **Не применяет redaction** — этим занимается Gateway через TargetSafeLogger
- **Всегда raises DriverError** при transport-ошибках, не возвращает ErrorResponse

**Импортные границы** (из guard-тестов `tests/architecture/test_target_layer_boundaries.py`):

| Запрет | Причина |
|---|---|
| Delivery не импортирует `httpx`, `tenacity`, `structlog` | Изоляция транспортных зависимостей |
| `core/` не импортирует `providers/` | Ядро не знает о конкретных провайдерах |
| `core/` не импортирует `transports/` | Ядро не знает о конкретном транспорте |
| `domain/` не импортирует `infra/` | Доменный слой чист от инфраструктуры |

---

## 💡 Типичные сценарии

### Сценарий 1: Успешный upsert (200 OK)

```
RequestSpec(alias="users.upsert", params={"target_id": "u-42"}, payload={"name": "Alice"})
  │
  gateway.execute(spec)
    -> kernel.get_compiled_operation("users.upsert")
       compiled.build(operation_params={"target_id": "u-42"})
       -> CompiledHttpRequest(method="PUT", path="/ankey/managed/user/u-42")
    -> requests_total=1
    -> driver.execute(compiled_request, {"name": "Alice"})
       <- HTTP 200 {"id": "u-42", "name": "Alice"}
       DriverResponse(ok=True, answer_code=200, payload={...})
    -> result_builder.execute_success(resp)
       safe_body(payload) -> {"id": "u-42", "name": "Alice"}  [нет секретов]
  │
  ExecutionResult(ok=True, answer_code=200, response_payload={...})
  stats: (1, 0, 0)
```

### Сценарий 2: Retry при TRANSIENT (503 → 503 → 200)

```
gateway.execute(spec)  [max_attempts=3, backoff_base=0.5]

Попытка 1:
  requests_total=1
  driver.execute -> HTTP 503
  fault_kind="TRANSIENT", directive=RETRY_BACKOFF
  retries_used=1, retries_total=1, sleep ~0.5 сек

Попытка 2:
  requests_total=2
  driver.execute -> HTTP 503
  retries_used=2, retries_total=2, sleep ~1.0 сек

Попытка 3:
  requests_total=3
  driver.execute -> HTTP 200
  ExecutionResult(ok=True, answer_code=200, ...)
  stats: (3, 2, 0)
```

### Сценарий 3: Конфликт UUID с мутацией

```
RequestSpec(alias="users.upsert", params={"target_id": "orig-001"}, ...)

Попытка 1:
  path="/ankey/managed/user/orig-001"
  requests_total=1
  driver.execute <- HTTP 409 {"message": "resourceexists"}
  fault_kind="CONFLICT"
  resolve_retry_action(CONFLICT, 409, "resourceexists")
  -> ResolvedRetryAction(RETRY_BACKOFF, mutation="regenerate_target_id")

  _apply_execute_retry:
    mutations.apply("regenerate_target_id", spec)
    -> new_params={"target_id": "regen-uuid-5678"}
    -> current_spec обновлён
    retries_used=1, retries_total=1, sleep ~0.5 сек

Попытка 2:
  path="/ankey/managed/user/regen-uuid-5678"
  requests_total=2
  driver.execute <- HTTP 200
  ExecutionResult(ok=True, answer_code=200, ...)
  stats: (2, 1, 0)
```

### Сценарий 4: Throttle с Retry-After

```
Попытка 1:
  requests_total=1
  driver.execute <- HTTP 429, Retry-After: 5
  DriverResponse(ok=False, answer_code=429, retry_after_s=5.0)
  fault_kind="THROTTLE", directive=RETRY_AFTER

  _apply_execute_retry:
    directive="RETRY_AFTER" -> sleep_exact(5.0)  [ровно 5 секунд]
    retries_used=1, retries_total=1

Попытка 2:
  requests_total=2
  driver.execute <- HTTP 200
  ExecutionResult(ok=True, answer_code=200, ...)
  stats: (2, 1, 0)
```

### Сценарий 5: ESCALATE — немедленная остановка

```
RetryRule(directive="ESCALATE", match_fault="TRANSIENT")

Попытка 1:
  requests_total=1
  driver.execute -> DriverError("network down")
  fault_kind="TRANSIENT"
  resolve_retry_action -> ResolvedRetryAction(directive="ESCALATE")

  _apply_execute_retry:
    "ESCALATE" not in {"RETRY_BACKOFF", "RETRY_AFTER"}
    -> should_retry=False  [НЕМЕДЛЕННО без проверки бюджета]

  build_exc_details -> error_details["escalated"] = True
  failures_total=1
  ExecutionResult(ok=False, error_code=INFRA_UNAVAILABLE, error_details={"escalated": True})
  stats: (1, 0, 1)
```

`ESCALATE` vs `NO_RETRY`:
- `NO_RETRY` — штатная ситуация; retry не предусмотрен для данного fault
- `ESCALATE` — критический сигнал; delivery может использовать `error_details["escalated"]`
  для специальной обработки (алерт, abort пайплайна)

---

## 📌 Важные детали

### 🚨 Failure Modes

| Режим отказа | Что происходит | Результат |
|---|---|---|
| `require_capability` провален | `ValueError` перехватывается в Gateway | `ExecutionResult(ok=False, INTERNAL_ERROR)` |
| Компиляция операции провалена | `ValueError` из `get_compiled_operation` | `ExecutionResult(ok=False, INTERNAL_ERROR)` |
| Driver: `DriverError` | `fault_handler.from_driver_error()` → retry или terminal | `ExecutionResult` с fault классификацией |
| Driver: unexpected `Exception` | `except Exception` в Gateway | `ExecutionResult(ok=False, INFRA_UNAVAILABLE)` |
| Retry budget exhausted | `can_retry()` вернул `False` | `ExecutionResult(ok=False)` по последнему fault |
| Мутация не зарегистрирована | `ValueError` из `mutations.apply` | `ExecutionResult(ok=False, INTERNAL_ERROR)` |
| `ESCALATE` директива | `should_retry=False` немедленно | `ExecutionResult` с `escalated=True` в details |
| `iter_pages` после первой страницы | retry запрещён; DriverError → `TargetPageResult(ok=False)` | Частичный результат для верхнего уровня |

### ⚠️ Инварианты системы

| # | Инвариант |
|---|---|
| 1 | Delivery не импортирует `httpx`, `tenacity`, `structlog` напрямую — только через `TargetRuntime` Protocol |
| 2 | Ядро не содержит provider-specific литералов: нет `"ankey"`, `"resourceexists"`, `"X-Ankey-*"` в `core/` |
| 3 | Driver — всегда single-attempt. Gateway — всегда retry owner. Нарушение → двойной счёт и некорректные мутации |
| 4 | Все пути `execute()` возвращают `ExecutionResult`, никогда не бросают исключений из Gateway |
| 5 | Kernel создаётся один раз; lookup-таблицы immutable → thread-safety при concurrent execution |
| 6 | Всё логирование через `TargetSafeLogger`; прямые `logger.info(payload)` в core запрещены |
| 7 | Мутация при retry — чистая функция; оригинальный `RequestSpec` не изменяется |
| 8 | `TargetSpec` валидируется при загрузке (Pydantic); некорректная спецификация не достигает runtime |
| 9 | Factory принимает только `runtime_mode='core'`; любое другое значение → `ValueError` на старте |
| 10 | Operation aliases — публичный контракт; их изменение в YAML — breaking change |

### ⏱️ Performance заметки

- **O(1) fault classification** — lookup по `_fault_by_status` и `_fault_by_code`
- **O(n fault_rules) range scan** — линейный поиск по `_fault_by_range` (обычно 1-2 правила)
- **O(n retry_rules) retry resolution** — линейный поиск с первым совпадением
- **Lazy compile** — `CompiledOperation` строится при инициализации Kernel, не при каждом вызове execute
- **Backoff задержка** через tenacity wait-strategy объект; jitter добавляет случайную составляющую `[0, backoff_base)`
- **structlog** — conditional import; no-op если не установлен

---

## 🛠️ Тестовое покрытие

### test_target_kernel.py

**Файл**: `tests/unit/infrastructure/test_target_kernel.py`

| Класс | Что проверяется |
|---|---|
| `TestClassifyFault` | 10 тестов: точные статусы, диапазоны 5xx, `error_code="NETWORK_ERROR"`, UNKNOWN, приоритет error_code над status |
| `TestRetryDirective` | 9 тестов: все FaultKind → RetryDirective; `CONFLICT+resourceexists` → mutation; CONFLICT без reason → NO_RETRY |
| `TestSystemErrorCode` | 6 тестов: маппинг AUTH→UNAUTHORIZED, PERMISSION→FORBIDDEN, DATA→DATA_INVALID, CONFLICT→CONFLICT, TRANSIENT→UNAVAILABLE, UNKNOWN→INTERNAL |
| `TestRedactHeaders` | 4 теста: Authorization, X-Ankey-Password, безопасные заголовки, смешанные |
| `TestRedactPayload` | 2 теста: поле password → `"***"`, не-dict → as-is |
| `TestSafeBody` | 3 теста: режимы none, keys_only, truncated |

Тест приоритета error_code:

```python
def test_error_code_takes_priority_over_status(self, kernel: TargetKernel) -> None:
    result = kernel.classify_fault(status_code=401, error_code="NETWORK_ERROR")
    assert result == "TRANSIENT"  # error_code побеждает над статусом 401 (AUTH)
```

Тест компиляции операции с path-params:

```python
def test_get_compiled_operation_renders_path_and_merges_defaults(kernel):
    _, compiled = kernel.get_compiled_operation("users.upsert")
    request = compiled.build(
        alias="users.upsert",
        operation_params={"target_id": "abc-123"},
        query_overrides={"decrypt": "true"},
    )
    assert request.method == "PUT"
    assert request.path == "/ankey/managed/user/abc-123"
    assert request.expected_statuses == (200, 201)
    assert request.query == {"_prettyPrint": "true", "decrypt": "true"}
```

### test_target_gateway.py

**Файл**: `tests/unit/infrastructure/test_target_gateway.py`

Использует `StubDriver` — stub-реализация `TargetDriver` с детерминированным списком
`request_effects` (DriverResponse или Exception). `_make_gateway()` — фабрика:
загружает реальный `ankey` spec через `load_target_spec`, создаёт `TargetKernel` и
`TargetGateway` с `build_ankey_mutations()`.

| Тест | Что проверяется |
|---|---|
| `test_execute_happy_path_returns_ok_and_masks_response` | ok=True, response_payload redacted, stats=(1,0,0) |
| `test_execute_retries_on_transient_and_then_succeeds` | 503→200, stats=(2,1,0) |
| `test_execute_no_retry_on_auth_error` | 401→NO_RETRY, error_code=AUTH_UNAUTHORIZED |
| `test_execute_retries_on_driver_error_and_exhausts` | 3×DriverError бюджет=2, stats=(3,2,1) |
| `test_execute_detects_resourceexists_reason` | 409+reason="resourceexists" |
| `test_execute_operation_alias_applies_resourceexists_mutation_and_retries` | mutation меняет path |
| `test_execute_retries_on_retry_after_directive` | 429→RETRY_AFTER→200 |
| `test_execute_escalate_stops_retry_cycle` | ESCALATE → escalated=True |
| `test_execute_operation_alias_unknown_returns_spec_error` | неизвестный alias → INTERNAL_ERROR |
| `test_iter_pages_happy_path_masks_items` | страницы, password="***" в items |
| `test_iter_pages_normalizes_driver_error` | DriverError → TargetPageResult(ok=False) |
| `test_health_check_ok` | ok=True, latency_ms>=0 |
| `test_health_check_driver_error_maps_to_fault_and_code` | DriverError → TRANSIENT+INFRA_UNAVAILABLE |
| `test_reset_stats_resets_all_counters` | после reset все счётчики = 0 |

Тест мутации с `monkeypatch`:

```python
def test_execute_operation_alias_applies_resourceexists_mutation_and_retries(monkeypatch):
    monkeypatch.setattr(mutation_mod.uuid, "uuid4", lambda: "regen-123")
    driver = StubDriver(request_effects=[
        DriverResponse(ok=False, answer_code=409, error_reason="resourceexists", ...),
        DriverResponse(ok=True, answer_code=200, ...),
    ])
    gateway = _make_gateway(driver=driver, max_attempts=2)
    result = gateway.execute(RequestSpec.operation(
        alias="users.upsert", params={"target_id": "orig-001"}, ...
    ))
    assert result.ok is True
    assert driver.request_calls[0]["path"] == "/ankey/managed/user/orig-001"
    assert driver.request_calls[1]["path"] == "/ankey/managed/user/regen-123"
```

---

## 🔗 Связанные документы

| Файл / ресурс | Описание |
|---|---|
| [target-dsl.md](target-dsl.md) | Спецификация TargetSpec: модели, YAML-формат, загрузчик |
| [target-transport.md](target-transport.md) | Transport protocol, HTTP-транспорт, HOW-TO новый транспорт |
| [target-provider.md](target-provider.md) | TargetProvider Protocol, AnkeyTargetProvider, HOW-TO новый провайдер |
| [TARGET-DEC-001](../../adr/target/TARGET-DEC-001-target-runtime-target-spec-slice.md) | ADR: TargetRuntime как единая точка входа |
| [TARGET-DEC-003](../../adr/target/TARGET-DEC-003-target-core.md) | ADR: plugin-core модель |

**Исходные файлы ядра**:

| Файл | Роль |
|---|---|
| `connector/infra/target/core/kernel.py` | TargetKernel |
| `connector/infra/target/core/gateway.py` | TargetGateway |
| `connector/infra/target/core/runtime.py` | TargetRuntime Protocol + DefaultTargetRuntime |
| `connector/infra/target/core/factory.py` | build_target_runtime |
| `connector/infra/target/core/registry.py` | TargetProviderRegistry |
| `connector/infra/target/core/mutations.py` | TargetMutationRegistry |
| `connector/infra/target/core/transport_compiler.py` | TransportCompilerRegistry, CompiledOperation |
| `connector/infra/target/core/models.py` | TargetMeta, TargetStats, TargetCheckResult, TargetConnectionConfig |
| `connector/infra/target/core/engines/error_normalizer.py` | TargetErrorNormalizer |
| `connector/infra/target/core/engines/fault_handler.py` | TargetFaultHandler |
| `connector/infra/target/core/engines/result_builder.py` | TargetResultBuilder |
| `connector/infra/target/core/engines/retry_engine.py` | TargetRetryEngine |
| `connector/infra/target/core/engines/safe_logging.py` | TargetSafeLogger |
| `connector/infra/target/driver.py` | TargetDriver Protocol, DriverResponse, DriverError |
| `connector/domain/target_dsl/spec_models.py` | TargetSpec и все spec-модели |
| `connector/domain/ports/target/execution.py` | RequestSpec, ExecutionResult, RequestExecutorProtocol |
| `connector/domain/ports/target/read.py` | TargetPageResult, TargetPagedReaderProtocol |
| `tests/unit/infrastructure/test_target_kernel.py` | Unit-тесты TargetKernel |
| `tests/unit/infrastructure/test_target_gateway.py` | Unit-тесты TargetGateway |
| `tests/architecture/test_target_layer_boundaries.py` | Guard-тесты импортных границ |

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-28 | Cоздана документация Target Core | xORex-LC |
