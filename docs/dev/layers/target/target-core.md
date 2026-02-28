# Target Core — агностическое ядро целевого слоя

**Файлы**: `connector/infra/target/core/`
**ADR**: [TARGET-DEC-001](../../adr/target/TARGET-DEC-001-target-runtime-target-spec-slice.md),
[TARGET-DEC-003](../../adr/target/TARGET-DEC-003-target-core.md)
**Дата последнего обновления**: 2026-02-28

---

## Аннотация

Target Core — transport-agnostic ядро целевого слоя ETL-пайплайна. Ядро реализует
механики retry, классификации сбоев (fault classification), редакции секретных данных
(redaction) и разрешения операций (operation resolution) без какого-либо знания о
конкретном транспорте — httpx, REST, Ankey API или структуре URL.

Ключевой принцип: **mechanism in core / rules in spec**. Все поведенческие правила
(какие HTTP-статусы являются ошибкой THROTTLE, сколько раз ретраить, какие заголовки
маскировать) объявлены декларативно в `TargetSpec` и хранятся в YAML-файлах
провайдера. Ядро лишь исполняет эти правила, оставаясь полностью агностичным к
источнику их происхождения.

Весь путь от delivery-команды до единственного I/O-вызова проходит через четыре
слоя: `TargetRuntime` (facade) → `TargetGateway` (retry owner) → `TargetKernel`
(policy resolver) → `TargetDriver` (single-attempt I/O).

---

## 1. Роль ядра в архитектуре

### 1.1 Что ядро знает

- `TargetSpec` — декларативная спецификация: capabilities, fault_rules, retry_rules,
  redaction, operation catalog.
- `OperationSpec` — описание операции: alias, kind, expected_statuses, transport data
  (opaque для core).
- `RequestSpec` / `ExecutionResult` — доменные порты: что delivery передаёт и что
  получает обратно.
- `DriverResponse` / `DriverError` — результат одной I/O-попытки от Driver.
- `RetryDirective` — директива повтора: `NO_RETRY`, `RETRY_BACKOFF`, `RETRY_AFTER`,
  `ESCALATE`.
- `TargetFaultKind` — классификация сбоя: `AUTH`, `TRANSIENT`, `CONFLICT` и т.д.

### 1.2 Что ядро не знает

- httpx, requests или любой другой HTTP-клиент.
- Ankey API: ни URL-путей, ни заголовков `X-Ankey-*`, ни конкретных error codes вида
  `resourceexists`.
- Структуры URL и шаблонов пути — это зона ответственности transport compiler и
  провайдера.
- Логики пагинации — только интерфейс `iter_batches()`, реализация в Driver.
- Формата сериализации тел запросов/ответов.

### 1.3 Принцип mechanism vs rules

Из ADR TARGET-DEC-003:

> «Механика (retry loop, backoff, error normalization, safe logging) живёт в ядре.
>  Правила (какой статус = какой FaultKind, когда ретраить, какие поля маскировать)
>  описываются декларативно в TargetSpec провайдера.»

Это позволяет добавить новый target-провайдер, написав только YAML-спецификацию и
Driver — без правки ядра.

### 1.4 Ссылки на ADR

- **TARGET-DEC-001** — ввод TargetRuntime как единой точки входа для delivery;
  разделение Gateway/Driver; typed models (TargetMeta, TargetStats, TargetCheckResult).
- **TARGET-DEC-003** — plugin-core модель: зафиксированы контракты fault/retry v1,
  вынесены engine-подсистемы, удалён legacy-path, закреплён `core`-only runtime mode.

---

## 2. Архитектурная иерархия компонентов

```
Delivery (commands: import_apply, cache_refresh, check_api)
  |
  | build_target_runtime(api_settings, ...)
  v
TargetRuntime (Protocol — domain port, runtime.py)
  |
  v
DefaultTargetRuntime (production impl, runtime.py)
  |-- .executor  ──────────────────────────────────────┐
  |-- .reader    ──────────────────────────────────────┤
  |-- .check()   ──────────────────────────────────────┤
  |-- .meta()    (из TargetConnectionConfig)            |
  |-- .stats()   (из gateway.get_stats())               |
  |-- .reset()   ───────> gateway.reset_stats()         |
  `-- .close()   ───────> gateway.close()               |
                                                        |
  v                                                     v
TargetGateway (retry owner, gateway.py)  <─────────────┘
  |   Реализует RequestExecutorProtocol (.execute)
  |   Реализует TargetPagedReaderProtocol (.iter_pages)
  |
  |── TargetKernel (immutable classifier/resolver, kernel.py)
  |     |-- _fault_by_status: dict[int, TargetFaultKind]
  |     |-- _fault_by_range:  list[tuple[int, int, TargetFaultKind]]
  |     |-- _fault_by_code:   dict[str, TargetFaultKind]
  |     |-- _retry_rules:     tuple[RetryRule, ...]
  |     `-- _compiled_operations: dict[str, CompiledOperation]
  |
  |── TargetDriver (single-attempt I/O — Protocol, инжектируется провайдером)
  |     |-- execute(compiled_request, payload) -> DriverResponse
  |     |-- iter_batches(compiled_request, batch_size, max_batches) -> Iterator
  |     `-- close() -> None
  |
  |── Engines (connector/infra/target/core/engines/):
  |     |── TargetErrorNormalizer  (error_normalizer.py)
  |     |── TargetFaultHandler     (fault_handler.py)
  |     |── TargetResultBuilder    (result_builder.py)
  |     |── TargetRetryEngine      (retry_engine.py)
  |     `── TargetSafeLogger       (safe_logging.py)
  |
  `── TargetMutationRegistry (mutations.py)

TargetProviderRegistry (registry.py)
  `── register / get / get_default -> TargetProvider

build_target_runtime() / build_target_runtime_with_info() (factory.py)
  `── TargetRuntimeBuildResult(runtime, target_type, requested_mode, effective_mode)

TransportCompilerRegistry (transport_compiler.py)
  `── register(kind, compiler_fn) -> compile(op_spec) -> CompiledOperation
```

### Таблица ответственностей компонентов

| Компонент | Ответственность |
|---|---|
| `TargetKernel` | Классификация сбоев, разрешение retry-директив, redaction, компиляция операций, проверка capabilities |
| `TargetGateway` | Владеет retry loop, вызывает Driver, применяет мутации, собирает stats |
| `TargetDriver` | Единственная I/O попытка (транспорт-специфичный, инжектируется провайдером) |
| `TargetErrorNormalizer` | Перевод raw status/error_code → NormalizedFault(fault_kind, error_code) |
| `TargetFaultHandler` | Классификация DriverError/DriverResponse, сборка error_details с redaction |
| `TargetResultBuilder` | Конструктор всех вариантов ExecutionResult (ok, error, spec_error, unexpected) |
| `TargetRetryEngine` | Расчёт и исполнение задержек: экспоненциальный backoff с jitter (tenacity) |
| `TargetSafeLogger` | Безопасное логирование через structlog — все payload/headers проходят редакцию |
| `TargetMutationRegistry` | Реестр чистых функций-мутаций RequestSpec (применяется при retry с mutation hook) |
| `TransportCompilerRegistry` | Компиляция OperationSpec → CompiledOperation по transport kind |
| `DefaultTargetRuntime` | Тонкий фасад: выдаёт executor, reader, check, meta, stats наружу delivery |
| `TargetProviderRegistry` | Реестр провайдеров по target_type, выбор default |
| `build_target_runtime()` | Точка входа для сборки всего runtime через provider registry |

---

## 3. Domain Ports

Domain ports определены в `connector/domain/ports/target/` и являются единственным
контрактом между delivery/usecase и target-инфраструктурой.

### 3.1 RequestSpec (execution.py)

```python
@dataclass(frozen=True, slots=True)
class RequestSpec:
    operation_alias: str          # обязателен; alias из каталога OperationSpec
    payload: Any | None = None    # бизнес-данные операции (dict, list, None)
    operation_params: Mapping[str, Any] | None = None  # параметры alias (path-params и т.п.)
```

`RequestSpec` — это намерение (intent): delivery описывает, что нужно сделать
(`operation_alias`), с какими параметрами (`operation_params`) и с каким телом
(`payload`). Ядро не знает, что именно скрывается за alias — это определяется
OperationSpec в TargetSpec.

Конструктор `RequestSpec.operation(alias, *, payload, params)` — фабричный метод
для удобного создания. `__post_init__` гарантирует, что `operation_alias` не пустой,
и что `operation_params` сразу копируется в dict (чтобы избежать Mapping-сюрпризов
при мутациях).

### 3.2 ExecutionResult (execution.py)

```python
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

Ключевой инвариант: `execute()` в TargetGateway **никогда не бросает исключений
наружу**. Всегда возвращает `ExecutionResult`. Delivery работает только с этим
объектом и не перехватывает исключения из gateway.

### 3.3 RequestExecutorProtocol

```python
class RequestExecutorProtocol(Protocol):
    def execute(self, spec: RequestSpec) -> ExecutionResult: ...
```

Delivery-команда `import_apply` взаимодействует только с этим протоколом.
`TargetGateway` структурно удовлетворяет ему. Delivery получает executor через
`runtime.executor`.

### 3.4 TargetPageResult (read.py)

```python
@dataclass(frozen=True)
class TargetPageResult:
    ok: bool
    page: int
    items: list[dict[str, Any]] | None   # None при ok=False
    error_code: SystemErrorCode | None = None
    error_message: str | None = None
    error_details: dict[str, Any] | None = None
```

При `ok=True` — `items` содержит список записей текущей страницы (после maskSecretsInObject).
При `ok=False` — `items=None` и заполнены `error_*` поля. Gateway гарантирует,
что в итераторе никогда не будет непойманных исключений.

### 3.5 TargetPagedReaderProtocol

```python
class TargetPagedReaderProtocol(Protocol):
    def iter_pages(
        self,
        operation_alias: str,
        page_size: int,
        max_pages: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterable[TargetPageResult]: ...
```

Используется в `cache_refresh` для постраничного чтения существующих записей из
target-системы. `TargetGateway` структурно удовлетворяет этому протоколу.

---

## 4. TargetKernel — детальный разбор

`TargetKernel` (`connector/infra/target/core/kernel.py`) — иммутабельный резолвер
политик. Создаётся один раз при сборке runtime и никогда не изменяется.

### 4.1 Инициализация и lookup-таблицы

```python
class TargetKernel:
    def __init__(
        self,
        spec: TargetSpec,
        compiler_registry: TransportCompilerRegistry,
    ) -> None:
```

При инициализации из `spec.fault_rules` строятся три независимые lookup-структуры
для O(1) / O(N) доступа при классификации ошибок:

```python
# Точный матч по HTTP-статусу -> O(1)
self._fault_by_status: dict[int, TargetFaultKind] = {
    r.match_status: r.fault_kind
    for r in spec.fault_rules
    if r.match_status is not None
}

# Диапазонный матч (например, 500-599) -> O(N диапазонов)
self._fault_by_range: list[tuple[int, int, TargetFaultKind]] = [
    (*r.match_status_range, r.fault_kind)
    for r in spec.fault_rules
    if r.match_status_range is not None
]

# Матч по error_code строки (например, "NETWORK_ERROR") -> O(1)
self._fault_by_code: dict[str, TargetFaultKind] = {
    r.match_error_code: r.fault_kind
    for r in spec.fault_rules
    if r.match_error_code is not None
}
```

Retry-правила сохраняются как кортеж для гарантии порядка применения:

```python
self._retry_rules: tuple[RetryRule, ...] = spec.retry_rules
self._capabilities: frozenset[TargetCapability] = spec.capabilities
```

Каждая операция из `spec.operations` немедленно компилируется через
`compiler_registry`:

```python
for key, operation in spec.operations.items():
    if key != operation.alias:
        raise ValueError(f"operation alias key mismatch: ...")
    self._compiled_operations[key] = compiler_registry.compile(operation)
    self._operations[key] = operation
```

Если ключ словаря не совпадает с `alias` операции — `ValueError` немедленно при
инициализации. Таким образом, нелегитимная `TargetSpec` никогда не попадёт в
production.

### 4.2 classify_fault(status_code, error_code) → TargetFaultKind

```python
def classify_fault(
    self,
    *,
    status_code: int | None = None,
    error_code: str | None = None,
) -> TargetFaultKind:
```

Алгоритм применяется строго в следующем порядке приоритетов:

```
1. error_code задан И присутствует в _fault_by_code
   -> вернуть fault по error_code (error_code побеждает над status)

2. status_code задан И присутствует в _fault_by_status (точный матч)
   -> вернуть fault по статусу

3. status_code задан И попадает в один из диапазонов _fault_by_range
   -> вернуть fault первого совпавшего диапазона

4. Ни одно правило не сработало
   -> вернуть "UNKNOWN"
```

Приоритет `error_code` над `status_code` критически важен: при сетевой ошибке
(NETWORK_ERROR) `status_code` обычно `None`, поэтому `error_code` является
единственным источником классификации. Но даже при наличии обоих параметров
`error_code` выигрывает — это сознательный дизайн.

Таблица примеров (для ankey.target.yaml):

| Аргументы | Результат | Путь |
|---|---|---|
| `status_code=401` | `AUTH` | `_fault_by_status[401]` |
| `status_code=403` | `PERMISSION` | `_fault_by_status[403]` |
| `status_code=400` | `DATA` | `_fault_by_status[400]` |
| `status_code=422` | `DATA` | `_fault_by_status[422]` |
| `status_code=404` | `NOT_FOUND` | `_fault_by_status[404]` |
| `status_code=409` | `CONFLICT` | `_fault_by_status[409]` |
| `status_code=429` | `THROTTLE` | `_fault_by_status[429]` |
| `status_code=500` | `TRANSIENT` | `_fault_by_range` (диапазон 500-599) |
| `status_code=503` | `TRANSIENT` | `_fault_by_range` (диапазон 500-599) |
| `status_code=599` | `TRANSIENT` | `_fault_by_range` (диапазон 500-599) |
| `error_code="NETWORK_ERROR"` | `TRANSIENT` | `_fault_by_code["NETWORK_ERROR"]` |
| `status_code=401, error_code="NETWORK_ERROR"` | `TRANSIENT` | error_code побеждает |
| `status_code=418` | `UNKNOWN` | fallback |
| _(нет аргументов)_ | `UNKNOWN` | fallback |

### 4.3 resolve_retry_action(fault_kind, status_code, error_reason) → ResolvedRetryAction

```python
@dataclass(frozen=True, slots=True)
class ResolvedRetryAction:
    directive: RetryDirective    # "NO_RETRY" | "RETRY_BACKOFF" | "RETRY_AFTER" | "ESCALATE"
    mutation: str | None = None  # имя мутации из TargetMutationRegistry (или None)

def resolve_retry_action(
    self,
    *,
    fault_kind: TargetFaultKind,
    status_code: int | None = None,
    error_reason: str | None = None,
) -> ResolvedRetryAction:
```

Алгоритм линейного поиска по `_retry_rules` с ранним выходом:

```
normalized_reason = error_reason.strip().lower() если error_reason это str

для каждого rule в retry_rules (по порядку объявления в spec):
    если rule.match_fault задан И не совпадает с fault_kind -> пропустить rule
    если rule.match_status задан И не совпадает с status_code -> пропустить rule
    если rule.match_reason задан И не совпадает с normalized_reason -> пропустить rule
    -> вернуть ResolvedRetryAction(directive=rule.directive, mutation=rule.mutation)

нет совпавшего rule -> вернуть ResolvedRetryAction(directive="NO_RETRY", mutation=None)
```

Важные детали реализации:
- `match_reason` всегда хранится в lowercase (нормализуется при парсинге `RetryRule`).
- `error_reason` из ответа нормализуется `.strip().lower()` перед сравнением.
- Порядок правил в YAML имеет значение — выигрывает первое совпавшее правило.
- Нет совпадения = `NO_RETRY` (conservative default).

Совместимый API `retry_directive(fault_kind)` — тонкая обёртка:

```python
def retry_directive(self, fault_kind: TargetFaultKind) -> RetryDirective:
    return self.resolve_retry_action(fault_kind=fault_kind).directive
```

Примеры для ankey.target.yaml:

| fault_kind | status_code | error_reason | directive | mutation |
|---|---|---|---|---|
| `TRANSIENT` | 503 | — | `RETRY_BACKOFF` | None |
| `THROTTLE` | 429 | — | `RETRY_AFTER` | None |
| `CONFLICT` | 409 | `resourceexists` | `RETRY_BACKOFF` | `regenerate_target_id` |
| `CONFLICT` | 409 | None | `NO_RETRY` | None |
| `AUTH` | 401 | — | `NO_RETRY` | None |
| `PERMISSION` | 403 | — | `NO_RETRY` | None |
| `DATA` | 400 | — | `NO_RETRY` | None |
| `NOT_FOUND` | 404 | — | `NO_RETRY` | None |
| `UNKNOWN` | 418 | — | `NO_RETRY` | None |

Сценарий `CONFLICT + resourceexists` — центральный пример мутации при retry:
UUID записи уже занят в target, нужно сгенерировать новый перед повтором.

### 4.4 system_error_code(fault_kind) → SystemErrorCode

Табличный маппинг `TargetFaultKind → SystemErrorCode` для domain-диагностик.
Определён как модульная константа `_FAULT_TO_SYSTEM`:

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

Таблица маппинга:

| TargetFaultKind | SystemErrorCode | Семантика |
|---|---|---|
| `AUTH` | `AUTH_UNAUTHORIZED` | 401 — нет или неверные credentials |
| `PERMISSION` | `AUTH_FORBIDDEN` | 403 — авторизован, но нет прав |
| `DATA` | `DATA_INVALID` | 400/422 — данные отклонены target |
| `NOT_FOUND` | `DATA_INVALID` | 404 — запись не существует |
| `CONFLICT` | `CONFLICT` | 409 — дублирование или конфликт |
| `THROTTLE` | `INFRA_UNAVAILABLE` | 429 — rate limit |
| `TRANSIENT` | `INFRA_UNAVAILABLE` | 5xx или сетевые сбои |
| `SPEC` | `INTERNAL_ERROR` | ошибка конфигурации |
| `UNKNOWN` | `INTERNAL_ERROR` | неизвестный тип сбоя |

Заметно, что `NOT_FOUND` маппируется в `DATA_INVALID` — это намеренно: в контексте
ETL-пайплайна «запись не найдена» семантически означает проблему с входными данными
(пытаемся работать с записью, которой нет).

### 4.5 resolve_operation(alias) и get_compiled_operation(alias)

```python
def resolve_operation(self, alias: str) -> OperationSpec:
    operation = self._operations.get(alias)
    if operation is None:
        raise ValueError(f"unknown operation alias: {alias}")
    return operation

def get_compiled_operation(
    self, alias: str
) -> tuple[OperationSpec, CompiledOperation[Any]]:
    operation = self.resolve_operation(alias)
    compiled = self._compiled_operations.get(alias)
    if compiled is None:
        raise ValueError(f"operation {alias!r} is not compiled")
    return operation, compiled
```

`resolve_operation` — O(1) словарный поиск. `ValueError` при неизвестном alias
перехватывается в Gateway и транслируется в `ExecutionResult(ok=False, SPEC)`.

`get_compiled_operation` возвращает пару `(OperationSpec, CompiledOperation)`.
`CompiledOperation` — opaque для Gateway: это Protocol-объект, умеющий строить
transport-специфичный запрос через метод `build(...)`. Gateway не распаковывает его —
передаёт в Driver напрямую.

Пример из теста:

```python
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

### 4.6 has_capability / require_capability

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

`TargetCapability` — это `Literal["check", "execute", "read_paged"]`.

Когда проверяется:
- `"execute"` — в начале каждого `TargetGateway.execute()`.
- `"read_paged"` — в начале каждого `TargetGateway.iter_pages()`.
- `"check"` — в начале `TargetGateway.health_check()`.

`ValueError` от `require_capability` в `execute()` и `iter_pages()` перехватывается
внутри Gateway и транслируется в `ExecutionResult(ok=False)` или
`TargetPageResult(ok=False)` соответственно, не пробиваясь наружу.

### 4.7 health_operation_alias()

```python
def health_operation_alias(self) -> str:
    return self._spec.health.operation_alias
```

Возвращает alias health-операции из `TargetSpec.health`. Для Ankey-провайдера это
`"health.check"`. Gateway использует этот alias для компиляции и выполнения
health-check.

### 4.8 Redaction — методы безопасного представления данных

#### redact_headers(headers) → dict[str, str]

```python
def redact_headers(self, headers: dict[str, str]) -> dict[str, str]:
    forbidden = self._spec.redaction.forbidden_metadata_keys
    return {
        k: ("***" if k.lower() in forbidden else v)
        for k, v in headers.items()
    }
```

Сравнение ведётся по lowercase-ключу заголовка против `frozenset` запрещённых
имён. Значение по умолчанию для `RedactionSpec.forbidden_metadata_keys`:
`{"authorization", "cookie", "set-cookie", "x-api-key", "x-ankey-password"}`.

Пример:

```python
kernel.redact_headers({
    "Content-Type": "application/json",
    "Authorization": "Bearer token123",    # -> "***"
    "X-Ankey-Password": "secret",          # -> "***"
    "X-Api-Key": "key123",                 # -> "***"
})
# -> {"Content-Type": "application/json", "Authorization": "***",
#     "X-Ankey-Password": "***", "X-Api-Key": "***"}
```

#### redact_payload(payload) → Any

```python
def redact_payload(self, payload: Any) -> Any:
    return maskSecretsInObject(payload)
```

Делегирует в `connector.common.sanitize.maskSecretsInObject`. Эта функция рекурсивно
обходит dict/list и заменяет значения ключей из внутреннего стоп-списка на `"***"`.
Для не-dict объектов возвращает as-is. `RedactionSpec.forbidden_fields`:
`{"password", "token", "secret", "api_key"}`.

#### safe_body(body, redaction=None) → Any

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

Три режима:

| `body_mode` | Поведение | Применение |
|---|---|---|
| `"none"` | всегда `None` | максимальная секретность — ничего не логировать |
| `"keys_only"` | для dict → список ключей; для str → `truncateText(body)` | видно схему, но не значения |
| `"truncated"` | `maskSecretsInObject(body)` | дефолт: маскирует секреты, сохраняет остальное |

Опциональный параметр `redaction` позволяет переопределить режим для конкретного
вызова (например, при построении error_details использует иной профиль, чем при
логировании ответа).

---

## 5. Engines subsystem — детальный разбор

Engines — специализированные компоненты внутри `connector/infra/target/core/engines/`.
Все они получают `TargetKernel` через конструктор и инкапсулируют одну конкретную
подзадачу. `TargetGateway` создаёт их в своём `__init__` и хранит как приватные поля.

### 5.1 TargetErrorNormalizer (error_normalizer.py)

```python
@dataclass(frozen=True, slots=True)
class NormalizedFault:
    fault_kind: TargetFaultKind    # категория сбоя
    error_code: SystemErrorCode    # доменный код для диагностик

class TargetErrorNormalizer:
    def __init__(self, kernel: TargetKernel) -> None: ...

    def from_status(self, status_code: int | None) -> NormalizedFault: ...
    def from_error_code(self, error_code: str | None) -> NormalizedFault: ...
    def from_status_or_code(
        self, *, status_code: int | None = None, error_code: str | None = None
    ) -> NormalizedFault: ...
```

Тонкий адаптер: вызывает `kernel.classify_fault(...)` и `kernel.system_error_code()`
и упаковывает результат в `NormalizedFault`. Мост между raw транспортными данными
(HTTP-статус, error-код) и domain error vocabulary.

- `from_status` — только по статус-коду (используется для `DriverResponse`).
- `from_error_code` — только по строковому коду ошибки.
- `from_status_or_code` — оба параметра; `error_code` побеждает (делегирует логику в kernel).

### 5.2 TargetFaultHandler (fault_handler.py)

```python
class TargetFaultHandler:
    def __init__(
        self,
        kernel: TargetKernel,
        normalizer: TargetErrorNormalizer,
        safe_logger: TargetSafeLogger,
    ) -> None: ...
```

Центральный обработчик ошибок в Gateway. Инкапсулирует:
- Классификацию `DriverError` и `DriverResponse` в `(NormalizedFault, ResolvedRetryAction)`.
- Сборку `error_details` с redaction и метаданными.

```python
def from_driver_error(
    self, exc: DriverError
) -> tuple[NormalizedFault, ResolvedRetryAction]:
    status_code = self.as_status_code(exc.answer_code)
    normalized = self._normalizer.from_status_or_code(
        status_code=status_code, error_code=exc.code,
    )
    retry_action = self._kernel.resolve_retry_action(
        fault_kind=normalized.fault_kind,
        status_code=status_code,
        error_reason=exc.error_reason,
    )
    return normalized, retry_action

def from_driver_response(
    self, resp: DriverResponse
) -> tuple[NormalizedFault, ResolvedRetryAction]:
    status_code = self.as_status_code(resp.answer_code)
    normalized = self._normalizer.from_status(status_code)
    retry_action = self._kernel.resolve_retry_action(
        fault_kind=normalized.fault_kind,
        status_code=status_code,
        error_reason=resp.error_reason,
    )
    return normalized, retry_action
```

Для `DriverError` используется `from_status_or_code` (error_code может присутствовать
через `exc.code`). Для `DriverResponse` — только статус-код через `from_status`
(response body не является source of truth для классификации fault).

Сборка `error_details`:

```python
def build_exc_details(
    self, exc: DriverError, retry_action: ResolvedRetryAction
) -> dict[str, Any] | None:
    # 1. Берём exc.details (если dict) -> пропускаем через safe_body для redaction
    # 2. Добавляем content_preview (truncated до 500 символов)
    # 3. Добавляем error_reason если есть
    # 4. Если directive == "ESCALATE" -> добавляем {"escalated": True}

def build_resp_details(
    self, resp: DriverResponse, retry_action: ResolvedRetryAction
) -> dict[str, Any] | None:
    # 1. Через safe_logger.build_error_details(payload, content_preview)
    # 2. Добавляем error_reason если есть
    # 3. Если directive == "ESCALATE" -> добавляем {"escalated": True}
```

Статический метод `as_status_code(answer_code)` извлекает `int` из `answer_code`
только если `type(answer_code) is int` (строгая проверка типа, не `isinstance`).

`mark_escalated(details)` добавляет `"escalated": True` в словарь details — delivery
использует этот флаг для диагностик критических сбоев.

### 5.3 TargetResultBuilder (result_builder.py)

```python
class TargetResultBuilder:
    def __init__(self, kernel: TargetKernel, safe_logger: TargetSafeLogger) -> None: ...
```

Конструктор всех вариантов `ExecutionResult`. Инкапсулирует все пути создания:

```python
def execute_success(self, resp: DriverResponse) -> ExecutionResult:
    safe_payload = self._safe_logger.safe_body(resp.payload)
    return ExecutionResult(
        ok=True,
        answer_code=resp.answer_code,
        response_payload=safe_payload,
        response_format=resp.payload_format,
    )
```

Успешный ответ: payload проходит через `safe_body` (redaction) перед включением
в результат. `response_payload` в `ExecutionResult` **всегда redacted**.

```python
def from_driver_error(
    self, exc: DriverError, normalized: NormalizedFault,
    error_details: dict[str, Any] | None,
) -> ExecutionResult:
    return ExecutionResult(
        ok=False,
        answer_code=exc.answer_code,
        error_code=normalized.error_code,
        error_message=truncateText(str(exc)),
        error_reason=exc.error_reason,
        error_details=error_details,
    )

def from_response_error(
    self, resp: DriverResponse, normalized: NormalizedFault,
    error_details: dict[str, Any] | None,
) -> ExecutionResult:
    safe_payload = error_details.get("response_payload") if isinstance(error_details, dict) else None
    return ExecutionResult(
        ok=False,
        answer_code=resp.answer_code,
        response_payload=safe_payload,
        response_format=resp.payload_format if safe_payload is not None else "none",
        error_code=normalized.error_code,
        error_message=TargetFaultHandler.format_answer_failure(resp.answer_code),
        error_reason=resp.error_reason,
        error_details=error_details,
    )

def unexpected_failure(self, exc: Exception) -> ExecutionResult:
    return ExecutionResult(
        ok=False,
        error_code=SystemErrorCode.INFRA_UNAVAILABLE,
        error_message=truncateText(str(exc)),
    )

def spec_error(self, message: str) -> ExecutionResult:
    return ExecutionResult(
        ok=False,
        error_code=self._kernel.system_error_code("SPEC"),
        error_message=truncateText(message),
    )
```

Для `spec_error` используется `kernel.system_error_code("SPEC")` → `INTERNAL_ERROR`.
Для `unexpected_failure` — фиксированный `INFRA_UNAVAILABLE` (неожиданное исключение
считается инфраструктурным сбоем).

### 5.4 TargetRetryEngine (retry_engine.py)

```python
class TargetRetryEngine:
    def __init__(
        self,
        config: RetryConfig,
        *,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
```

Обёртка над механизмом backoff/jitter из библиотеки `tenacity`. Принимает
инжектируемую `sleep_fn` (что упрощает тестирование без реальных задержек).

Конфигурация `RetryConfig`:

```python
class RetryConfig(_SpecModel):
    max_attempts: int = 3        # бюджет повторов (без учёта первой попытки)
    backoff_base: float = 0.5   # базовая задержка в секундах
    backoff_max: float = 30.0   # максимальная задержка в секундах
    jitter: bool = True          # добавлять ли случайный разброс
```

Инициализация стратегии ожидания:

```python
if config.jitter:
    self._wait_strategy = wait_exponential_jitter(
        initial=config.backoff_base,
        max=config.backoff_max,
        jitter=config.backoff_base,    # добавочный jitter = backoff_base
    )
else:
    self._wait_strategy = wait_exponential(
        multiplier=config.backoff_base,
        min=config.backoff_base,
        max=config.backoff_max,
    )
```

```python
@property
def max_retries(self) -> int:
    return self._config.max_attempts

def can_retry(self, retries_used: int) -> bool:
    return retries_used < self._config.max_attempts

def sleep_before_retry(self, retries_used: int) -> float:
    attempt_number = max(1, retries_used)
    delay = float(self._wait_strategy(_RetryAttemptState(attempt_number=attempt_number)))
    if delay > 0:
        self._sleep_fn(delay)
    return delay

def sleep_exact(self, delay_s: float | None) -> float:
    if delay_s is None:
        return 0.0
    delay = max(0.0, float(delay_s))
    if delay > 0:
        self._sleep_fn(delay)
    return delay
```

- `can_retry(retries_used)` — `retries_used=0` до первого повтора. При бюджете
  `max_attempts=3` разрешены повторы 1, 2, 3.
- `sleep_before_retry(retries_used)` — рассчитывает и исполняет задержку; возвращает
  фактическую задержку для логирования.
- `sleep_exact(delay_s)` — используется для `RETRY_AFTER` директивы; спит ровно
  указанное количество секунд из заголовка `Retry-After`.

Задержки для конфигурации по умолчанию (backoff_base=0.5, backoff_max=30.0, no jitter):

| retries_used | attempt_number tenacity | Примерная задержка |
|---|---|---|
| 1 (первый retry) | 1 | ~0.5 сек |
| 2 | 2 | ~1.0 сек |
| 3 | 3 | ~2.0 сек |
| 4 | 4 | ~4.0 сек |
| 5+ | 5+ | <= 30.0 сек |

С `jitter=True` к базовому времени добавляется случайная составляющая в диапазоне
`[0, backoff_base)`, что снижает thundering herd при одновременном retry множества
операций.

### 5.5 TargetSafeLogger (safe_logging.py)

```python
class TargetSafeLogger:
    def __init__(self, kernel: TargetKernel, *, logger_name: str = __name__) -> None:
        self._kernel = kernel
        self._logger = structlog.get_logger(logger_name) if structlog else None
```

structlog-based логгер с гарантированной редакцией перед любой записью.
Если `structlog` не установлен — все методы становятся no-op (защитный импорт
в блоке try/except).

```python
def redact_headers(self, headers: dict[str, str] | None) -> dict[str, str] | None:
    if headers is None:
        return None
    return self._kernel.redact_headers(headers)

def redact_payload(self, payload: Any) -> Any:
    return self._kernel.redact_payload(payload)

def safe_body(self, body: Any) -> Any:
    return self._kernel.safe_body(body)
```

Методы логирования:

```python
def log_response_error(
    self, *, operation: str, answer_code: int | str | None,
    fault_kind: str, payload: Any, content_preview: str | None,
) -> None:
    # WARNING уровень; payload -> safe_body; content_preview -> truncateText
    self._logger.warning("target request failed", **log_data)

def debug_retry(
    self, *, operation: str, fault_kind: str, retries_used: int,
    max_retries: int, delay_s: float, mutation: str | None = None,
) -> None:
    # DEBUG уровень; delay_s округляется до 3 знаков
    self._logger.debug("запланирован повтор target-операции", ...)
```

```python
def build_error_details(
    self, *, payload: Any, content_preview: str | None,
) -> dict[str, Any] | None:
    # content_preview -> truncateText
    # payload (dict/list) -> safe_body -> "response_payload" в details
    # если ни payload ни preview нет -> None
```

Инвариант: ни один вызов этого класса не пропускает credentials или секретные данные
в структурированный лог. Весь payload проходит через `kernel.safe_body()` перед
включением в любой log event.

---

## 6. TargetGateway — полный разбор

`TargetGateway` (`connector/infra/target/core/gateway.py`) — единственный владелец
retry-политики. Это самый сложный компонент ядра.

### 6.1 Контракты и зависимости

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
        self._requests_total: int = 0
        self._retries_total: int = 0
        self._failures_total: int = 0
```

- Реализует структурно: `RequestExecutorProtocol` (метод `execute`).
- Реализует структурно: `TargetPagedReaderProtocol` (метод `iter_pages`).
- Создаётся провайдером (`AnkeyTargetProvider.build_core_runtime`).
- Передаётся в `DefaultTargetRuntime`.

### 6.2 execute(spec: RequestSpec) → ExecutionResult

**Контракт: никогда не бросает исключений наружу.**

```python
def execute(self, spec: RequestSpec) -> ExecutionResult:
    _OP = "execute"
    try:
        self._kernel.require_capability(_OP)
    except ValueError as exc:
        self._failures_total += 1
        return self._result_builder.spec_error(str(exc))

    retries_used = 0
    current_spec = spec   # мутации создают новый объект, не изменяют оригинал

    while True:
        # --- ФАЗА 1: Компиляция операции ---
        try:
            _, compiled = self._kernel.get_compiled_operation(current_spec.operation_alias)
            compiled_request = compiled.build(
                alias=current_spec.operation_alias,
                operation_params=current_spec.operation_params,
            )
        except ValueError as exc:
            self._failures_total += 1
            return self._result_builder.spec_error(str(exc))
        except Exception as exc:
            self._failures_total += 1
            return self._result_builder.unexpected_failure(exc)

        self._requests_total += 1

        # --- ФАЗА 2: I/O попытка через Driver ---
        try:
            resp = self._driver.execute(compiled_request, current_spec.payload)
        except DriverError as exc:
            normalized, retry_action = self._fault_handler.from_driver_error(exc)
            retry_after_s: float | None = exc.retry_after_s
            captured = exc
            make_error = lambda: self._result_builder.from_driver_error(
                captured, normalized, self._fault_handler.build_exc_details(captured, retry_action)
            )
        except Exception as exc:
            self._failures_total += 1
            return self._result_builder.unexpected_failure(exc)
        else:
            if resp.ok:
                return self._result_builder.execute_success(resp)
            normalized, retry_action = self._fault_handler.from_driver_response(resp)
            retry_after_s = resp.retry_after_s
            make_error = lambda: self._result_builder.from_response_error(
                resp, normalized, self._fault_handler.build_resp_details(resp, retry_action)
            )
            self._safe_logger.log_response_error(
                operation=_OP, answer_code=resp.answer_code,
                fault_kind=normalized.fault_kind, payload=resp.payload,
                content_preview=resp.content_preview,
            )

        # --- ФАЗА 3: Retry-решение ---
        try:
            should_retry, retries_used, current_spec = self._apply_execute_retry(
                operation=_OP, fault_kind=normalized.fault_kind,
                retry_action=retry_action, retries_used=retries_used,
                current_spec=current_spec, retry_after_s=retry_after_s,
            )
        except ValueError as mutation_error:
            self._failures_total += 1
            return self._result_builder.spec_error(str(mutation_error))

        if should_retry:
            continue

        self._failures_total += 1
        return make_error()
```

ASCII flow diagram retry loop:

```
execute(spec)
  |
  +--> require_capability("execute")
  |      ValueError? -> spec_error, failures++, RETURN
  |
  +===[ RETRY LOOP ]===========================================================+
  |                                                                             |
  +--> get_compiled_operation(alias) + compiled.build(params)                  |
  |      ValueError? -> spec_error, failures++, RETURN                         |
  |      Exception?  -> unexpected_failure, failures++, RETURN                 |
  |      requests_total++                                                       |
  |                                                                             |
  +--> driver.execute(compiled_request, payload)                               |
  |      |                                                                      |
  |      +--> resp.ok == True                                                   |
  |      |      -> execute_success(resp) -> RETURN (success)                   |
  |      |                                                                      |
  |      +--> resp.ok == False                                                  |
  |      |      normalized, retry_action = from_driver_response(resp)          |
  |      |      log_response_error(...)                                         |
  |      |                                                                      |
  |      +--> DriverError raised                                                |
  |      |      normalized, retry_action = from_driver_error(exc)              |
  |      |                                                                      |
  |      +--> Exception raised (unexpected)                                     |
  |             -> unexpected_failure, failures++, RETURN                      |
  |                                                                             |
  +--> _apply_execute_retry(fault_kind, retry_action, retries_used, ...)       |
  |      ValueError (mutation failed)? -> spec_error, failures++, RETURN       |
  |                                                                             |
  |      directive NOT in {RETRY_BACKOFF, RETRY_AFTER}?                        |
  |        -> should_retry=False (NO_RETRY или ESCALATE)                       |
  |                                                                             |
  |      retries_used >= max_attempts?                                          |
  |        -> should_retry=False (бюджет исчерпан)                             |
  |                                                                             |
  |      иначе:                                                                 |
  |        mutation? -> current_spec = mutations.apply(name, current_spec)     |
  |        retries_used++, retries_total++                                      |
  |        delay = compute_retry_delay(directive, retry_after_s)               |
  |        safe_logger.debug_retry(...)                                         |
  |        -> should_retry=True                                                 |
  |                                                                             |
  +--> should_retry == True -> continue LOOP ──────────────────────────────────+
  |
  +--> should_retry == False
         failures_total++
         make_error() -> RETURN (failure ExecutionResult)
```

Важная деталь реализации: переменная замыкания `make_error` (lambda) создаётся
после получения результата от Driver (ошибочный ответ или DriverError). Это
позволяет отложить создание `ExecutionResult` до тех пор, пока не станет ясно,
будет ли повтор. Ссылка `captured = exc` сохраняется явно, потому что Python
очищает переменную из `except as` после блока исключения.

### 6.3 _apply_execute_retry (внутренний метод)

```python
def _apply_execute_retry(
    self, *, operation: str, fault_kind: str,
    retry_action: ResolvedRetryAction, retries_used: int,
    current_spec: RequestSpec, retry_after_s: float | None = None,
) -> tuple[bool, int, RequestSpec]:
    directive = retry_action.directive
    if directive not in {"RETRY_BACKOFF", "RETRY_AFTER"}:
        return False, retries_used, current_spec
    if not self._retry_engine.can_retry(retries_used):
        return False, retries_used, current_spec

    if retry_action.mutation is not None:
        current_spec = self._mutations.apply(retry_action.mutation, current_spec)

    retries_used += 1
    self._retries_total += 1
    delay = self._compute_retry_delay(directive, retry_after_s, retries_used)
    self._safe_logger.debug_retry(
        operation=operation, fault_kind=fault_kind,
        retries_used=retries_used, max_retries=self._retry_engine.max_retries,
        delay_s=delay, mutation=retry_action.mutation,
    )
    return True, retries_used, current_spec
```

Возвращает `(should_retry, updated_retries_used, updated_spec)`. Мутация применяется
**до** инкремента `retries_used`. Если мутация не зарегистрирована — поднимает
`ValueError`, который перехватывается в `execute()`.

`ESCALATE` не входит в `{"RETRY_BACKOFF", "RETRY_AFTER"}`, поэтому `should_retry=False`
немедленно. Это принципиальное отличие от `NO_RETRY`: при `ESCALATE` в `error_details`
добавляется флаг `{"escalated": True}` через `TargetFaultHandler.mark_escalated()`.

### 6.4 _compute_retry_delay (внутренний метод)

```python
def _compute_retry_delay(
    self, directive: str, retry_after_s: float | None, retries_used: int,
) -> float:
    if directive == "RETRY_AFTER" and retry_after_s is not None:
        return self._retry_engine.sleep_exact(retry_after_s)
    return self._retry_engine.sleep_before_retry(retries_used)
```

Для `RETRY_AFTER` — использует значение из заголовка ответа (`Retry-After`).
Для `RETRY_BACKOFF` — экспоненциальный backoff с jitter.

### 6.5 iter_pages(operation_alias, page_size, max_pages, params) → Iterable[TargetPageResult]

```python
def iter_pages(
    self,
    operation_alias: str,
    page_size: int,
    max_pages: int | None,
    params: dict[str, Any] | None = None,
) -> Iterable[TargetPageResult]:
```

**Ключевое архитектурное решение**: retry при пагинации выполняется **только** если
ни одна страница ещё не была выдана (`last_page == 0`). Если данные уже начали
поступать — повтор опасен для идемпотентности (данные могут дублироваться
в кэше). После выдачи хотя бы одной страницы — ошибка сразу транслируется в
`TargetPageResult(ok=False)`.

```
iter_pages(alias, page_size, max_pages, params):
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

Мутации в `_apply_read_retry` **не поддерживаются**: `operation_params` для read
не меняются при повторе — нечего мутировать (нет UUID-конфликта при чтении).

Items каждой страницы немедленно проходят через `maskSecretsInObject` — данные из
target-системы могут содержать поля `password`, `token` и т.п.

Пример потока страниц (happy path):

```
iter_pages("users.list", page_size=100, max_pages=3)
  -> TargetPageResult(ok=True, page=1, items=[...100 records...])
  -> TargetPageResult(ok=True, page=2, items=[...100 records...])
  -> TargetPageResult(ok=True, page=3, items=[...73 records...])
  (driver.iter_batches завершился)
```

### 6.6 health_check() → TargetCheckResult

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
    try:
        resp = self._driver.execute(compiled_request, None)
    except DriverError as exc:
        driver_exc = exc
    except Exception as exc:
        unexpected_exc = exc

    latency_ms = int((time.monotonic() - start) * 1000)

    if driver_exc is not None:
        normalized, _ = self._fault_handler.from_driver_error(driver_exc)
        return TargetCheckResult(ok=False, latency_ms=latency_ms, ...)
    if unexpected_exc is not None:
        return TargetCheckResult(ok=False, latency_ms=latency_ms, fault_kind="TRANSIENT", ...)
    if resp.ok:
        return TargetCheckResult(ok=True, latency_ms=latency_ms)
    normalized, _ = self._fault_handler.from_driver_response(resp)
    return TargetCheckResult(ok=False, latency_ms=latency_ms, ...)
```

Health-check **не ретраит**: одна попытка, latency замеряется через `time.monotonic()`.
Неожиданные `Exception` классифицируются как `TRANSIENT` / `INFRA_UNAVAILABLE`.

Для Ankey-провайдера `health_operation_alias()` возвращает `"health.check"`, которая
компилируется в `GET /ankey/managed/user` (проверка доступности endpoint'а списка
пользователей).

### 6.7 Stats и lifecycle

```python
def get_stats(self) -> tuple[int, int, int]:
    return (self._requests_total, self._retries_total, self._failures_total)

def reset_stats(self) -> None:
    self._requests_total = 0
    self._retries_total = 0
    self._failures_total = 0

def close(self) -> None:
    self._driver.close()
```

Семантика счётчиков:

| Счётчик | Что считает |
|---|---|
| `requests_total` | Число попыток `driver.execute()` + успешно выданных страниц read |
| `retries_total` | Число повторов (только успешно запланированных) |
| `failures_total` | Число завершившихся неуспехом операций (не попыток!) |

Пример для сценария `503 → 503 → 200`:

```
requests_total=3  (3 попытки driver.execute)
retries_total=2   (2 повтора)
failures_total=0  (операция в итоге завершилась успехом)
```

Пример для сценария `NETWORK_ERROR × 3` (бюджет=2):

```
requests_total=3  (3 попытки driver.execute)
retries_total=2   (2 повтора)
failures_total=1  (операция завершилась неуспехом)
```

`close()` делегирует в `driver.close()` — освобождает HTTP connection pool (httpx.Client)
или другой ресурс транспорта. Вызывается из `DefaultTargetRuntime.close()`.

---

## 7. TargetMutationRegistry

`connector/infra/target/core/mutations.py`

```python
TargetMutation = Callable[[RequestSpec], RequestSpec]

class TargetMutationRegistry:
    def __init__(self, mutations: Mapping[str, TargetMutation] | None = None) -> None:
        self._mutations: dict[str, TargetMutation] = dict(mutations or {})

    def register(self, name: str, mutation: TargetMutation) -> None:
        normalized = name.strip()
        if normalized == "":
            raise ValueError("mutation name must not be empty")
        if normalized in self._mutations:
            raise ValueError(f"mutation already registered: {normalized}")
        self._mutations[normalized] = mutation

    def apply(self, name: str, request_spec: RequestSpec) -> RequestSpec:
        mutation = self._mutations.get(name)
        if mutation is None:
            raise ValueError(f"unknown mutation: {name}")
        return mutation(request_spec)
```

Мутация — **чистая функция**: принимает `RequestSpec`, возвращает новый `RequestSpec`.
Оригинальный `spec` никогда не изменяется. В Gateway `current_spec` заменяется
на результат мутации:

```python
current_spec = self._mutations.apply(retry_action.mutation, current_spec)
```

Создаётся провайдером (например, `build_ankey_mutations()`) и передаётся в
конструктор `TargetGateway`. Если мутации не нужны — `TargetMutationRegistry()`
(пустой реестр).

Пример мутации `regenerate_target_id` (из Ankey-провайдера):

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

При retry с `CONFLICT + resourceexists`: UUID записи уже занят в target (возможно,
запись создавалась параллельным процессом). Мутация генерирует новый UUID → Gateway
повторяет запрос с другим path-параметром → `compiled_request` будет указывать
на `PUT /ankey/managed/user/<new-uuid>`.

Из теста:

```python
# До мутации:
driver.request_calls[0]["path"] == "/ankey/managed/user/orig-001"
# После мутации + retry:
driver.request_calls[1]["path"] == "/ankey/managed/user/regen-123"
```

---

## 8. TransportCompilerRegistry

`connector/infra/target/core/transport_compiler.py`

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

OperationCompiler = Callable[[OperationSpec], CompiledOperation[Any]]

class TransportCompilerRegistry:
    def __init__(self) -> None:
        self._compilers: dict[str, OperationCompiler] = {}

    def register(self, kind: str, compiler: OperationCompiler) -> None:
        normalized = kind.strip().lower()
        if normalized == "":
            raise ValueError("kind транспорта не должен быть пустым")
        self._compilers[normalized] = compiler

    def compile(self, operation: OperationSpec) -> CompiledOperation[Any]:
        compiler = self._compilers.get(operation.kind)
        if compiler is None:
            raise ValueError(
                f"для operation.kind={operation.kind!r} не зарегистрирован компилятор",
            )
        return compiler(operation)
```

Реестр компиляторов: `operation.kind` → функция-компилятор. Разделяет ядро от
конкретного транспорта. HTTP-компилятор регистрируется провайдером:

```python
# Анки-провайдер (build_transport_compiler_registry):
registry = TransportCompilerRegistry()
registry.register("http", compile_http_operation)
```

`compile(operation)` при инициализации `TargetKernel` для каждой операции вызывает
соответствующий компилятор. Результат (объект типа `CompiledOperation`) хранится в
`_compiled_operations` ядра и передаётся в Driver при каждом вызове.

Что такое `CompiledOperation` для HTTP-транспорта: это объект, умеющий через `build()`
принять runtime-параметры (path params, query overrides) и вернуть конкретный
`CompiledHttpRequest` с заполненными `method`, `path`, `query`, `headers`,
`expected_statuses`. Driver получает этот объект и выполняет HTTP-запрос.

Что передаётся в `build()`:

| Параметр | Источник | Назначение |
|---|---|---|
| `alias` | `RequestSpec.operation_alias` | идентификатор операции |
| `operation_params` | `RequestSpec.operation_params` | подстановка в path template (`{target_id}`) |
| `query_overrides` | `params` из `iter_pages` | дополнительные query параметры |
| `header_overrides` | опционально | переопределение заголовков |

---

## 9. TargetRuntime и DefaultTargetRuntime

### 9.1 TargetRuntime Protocol (domain port)

`connector/infra/target/core/runtime.py`

```python
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

`TargetRuntime` — граница зависимости для delivery. Delivery-команды работают
только с этим Protocol'ом и никогда не импортируют `DefaultTargetRuntime` напрямую.
Это обеспечивает возможность подстановки stub/mock runtime в тестах без патчинга
конкретных классов инфраструктуры.

### 9.2 DefaultTargetRuntime

```python
class DefaultTargetRuntime:
    def __init__(
        self,
        *,
        gateway: TargetGateway,
        config: TargetConnectionConfig,
        has_reader: bool = True,
    ) -> None:
        self._gateway = gateway
        self._config = config
        self._has_reader = has_reader

    @property
    def executor(self) -> RequestExecutorProtocol:
        return self._gateway  # структурное соответствие

    @property
    def reader(self) -> TargetPagedReaderProtocol | None:
        return self._gateway if self._has_reader else None  # структурное соответствие

    def check(self) -> TargetCheckResult:
        return self._gateway.health_check()

    def meta(self) -> TargetMeta:
        return TargetMeta(
            target_type=self._config.target_type,
            transport=self._config.transport,
            endpoint=self._config.endpoint,
        )

    def stats(self) -> TargetStats:
        req, ret, fail = self._gateway.get_stats()
        return TargetStats(
            requests_total=req,
            retries_total=ret,
            failures_total=fail,
        )

    def reset(self) -> None:
        self._gateway.reset_stats()

    def close(self) -> None:
        self._gateway.close()
```

`DefaultTargetRuntime` — тонкая обёртка. Вся логика в Gateway. Runtime только
маршрутизирует вызовы и конструирует typed response objects (`TargetMeta`, `TargetStats`).

Флаг `has_reader=True` управляет тем, возвращает ли `runtime.reader` gateway
(для режима с чтением из target-системы) или `None` (только write-режим).

---

## 10. TargetProviderRegistry

`connector/infra/target/core/registry.py`

```python
class MissingTargetProviderError(LookupError): ...

class TargetProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, TargetProvider] = {}
        self._default_target_type: str | None = None

    def register(self, provider: TargetProvider, *, default: bool = False) -> None:
        target_type = provider.target_type
        if target_type in self._providers:
            raise ValueError(f"Target provider already registered: {target_type}")
        self._providers[target_type] = provider
        if default or self._default_target_type is None:
            self._default_target_type = target_type

    def get(self, target_type: str) -> TargetProvider:
        provider = self._providers.get(target_type)
        if provider is None:
            known = ", ".join(sorted(self._providers)) or "<none>"
            raise MissingTargetProviderError(
                f"Target provider '{target_type}' is not registered. Known providers: {known}",
            )
        return provider

    def get_default(self) -> TargetProvider:
        if self._default_target_type is None:
            raise MissingTargetProviderError("No default target provider is registered")
        return self.get(self._default_target_type)
```

Первый зарегистрированный provider автоматически становится default (если не установлен явно).
Попытка зарегистрировать дубликат → `ValueError`. Запрос несуществующего provider →
`MissingTargetProviderError`.

В production-конфигурации реестр содержит единственный provider: `ankey`.

---

## 11. Factory: build_target_runtime()

`connector/infra/target/core/factory.py`

```python
def build_target_runtime(
    api_settings: ApiSettings,
    *,
    transport: object | None = None,
    include_reader: bool = True,
    runtime_mode: str | None = None,
    target_type: str | None = None,
) -> TargetRuntime:

def build_target_runtime_with_info(
    api_settings: ApiSettings,
    *,
    transport: object | None = None,
    include_reader: bool = True,
    runtime_mode: str | None = None,
    target_type: str | None = None,
) -> TargetRuntimeBuildResult:
```

`build_target_runtime` — упрощённый фасад, возвращает только `TargetRuntime`.
`build_target_runtime_with_info` — полная версия с метаданными выбора.

Алгоритм `build_target_runtime_with_info`:

```
1. _resolve_runtime_mode(runtime_mode)
   -> нормализует строку (strip + lower)
   -> проверяет допустимые значения: {"core"} (единственный режим)
   -> ValueError если передан неизвестный режим

2. build_default_target_provider_registry(api_settings)
   -> строит реестр с AnkeyTargetProvider (default)

3. target_type задан?
   -> registry.get(target_type)   # MissingTargetProviderError если не найден
   иначе:
   -> registry.get_default()       # MissingTargetProviderError если нет default

4. provider.build_core_runtime(transport=transport, include_reader=include_reader)
   -> DefaultTargetRuntime (gateway + kernel + driver + engines + mutations)

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
    requested_mode: TargetRuntimeMode          # "core" (единственный)
    effective_mode: EffectiveTargetRuntimeMode # "core" (всегда)
```

`TargetRuntimeMode = Literal["core"]` и `EffectiveTargetRuntimeMode = Literal["core"]`
— на текущем этапе единственный поддерживаемый режим. Отдельные типы сохраняют
возможность расширения в будущем без изменения сигнатур.

Параметр `transport` позволяет инжектировать внешний transport-объект (например,
тестовый httpx.Client) вместо создания нового. При `transport=None` провайдер
создаёт transport самостоятельно.

---

## 12. Модели ядра (models.py)

`connector/infra/target/core/models.py`

```python
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
    principal: str = ""   # идентификатор principal/service account (для метаданных)
```

Все модели `frozen=True` — immutable dataclasses. `slots=True` — оптимизация памяти.
Используются на границе `runtime ↔ delivery` для типизированной передачи метаданных
и статистики без раскрытия внутренних деталей gateway.

---

## 13. Spec-модели (spec_models.py / domain/target_dsl/spec_models.py)

Source of truth для spec-моделей — `connector/domain/target_dsl/spec_models.py`.
Файл `connector/infra/target/core/spec_models.py` — compatibility re-export для
исторических import-путей.

Все spec-модели наследуют `_SpecModel(BaseModel)`:

```python
class _SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
```

`extra="forbid"` — незнакомые поля в YAML вызывают ошибку парсинга.
`frozen=True` — spec immutable после создания.

Ключевые типы:

```python
TargetFaultKind = Literal[
    "SPEC", "AUTH", "PERMISSION", "DATA", "NOT_FOUND",
    "CONFLICT", "THROTTLE", "TRANSIENT", "UNKNOWN",
]
TargetCapability = Literal["check", "execute", "read_paged"]
RetryDirective = Literal["NO_RETRY", "RETRY_BACKOFF", "RETRY_AFTER", "ESCALATE"]

class FaultRule(_SpecModel):
    fault_kind: TargetFaultKind
    match_status: int | None = None              # точный статус
    match_status_range: tuple[int, int] | None   # диапазон [low, high]
    match_error_code: str | None = None          # строковый код ошибки

class RetryRule(_SpecModel):
    directive: RetryDirective
    match_fault: TargetFaultKind | None = None
    match_status: int | None = None
    match_reason: str | None = None   # нормализуется в lowercase
    mutation: str | None = None       # имя мутации (или None)

class RetryConfig(_SpecModel):
    max_attempts: int = 3         # бюджет повторов
    backoff_base: float = 0.5    # базовая задержка сек
    backoff_max: float = 30.0    # максимальная задержка сек
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

`TargetSpec._validate_spec_integrity()` проверяет инварианты целостности при Pydantic
парсинге: health требует capability `check`; health alias должен быть в catalog
operations; ключи `operations` должны совпадать с `alias` внутри.

---

## 14. Инварианты ядра

Из TARGET-DEC-001 и TARGET-DEC-003:

**Инвариант 1**: Delivery-команды не импортируют `connector.infra.http.*`, `httpx`,
`tenacity`, `structlog` напрямую. Только через `TargetRuntime` Protocol.

**Инвариант 2**: Ядро не содержит provider-specific литералов. Нет `"ankey"`,
`"resourceexists"`, `"X-Ankey-*"` внутри `core/`. Все провайдер-специфичные правила
определяются в YAML и попадают в ядро только через `TargetSpec`.

**Инвариант 3**: Driver — всегда single-attempt. Gateway — всегда retry owner.
Никогда не ретраить внутри Driver. Нарушение этого инварианта приводит к двойному
счёту попыток и некорректной логике мутаций.

**Инвариант 4**: Все пути `execute()` возвращают `ExecutionResult`, никогда не
бросают исключений наружу из Gateway. Это проверяется unit-тестами для каждого
сценария (DriverError, unexpected Exception, spec error, capability error).

**Инвариант 5**: Kernel создаётся один раз при сборке runtime и immutable после
инициализации. Lookup-таблицы `_fault_by_status`, `_fault_by_range`, `_fault_by_code`
не изменяются. Это гарантирует thread-safety при concurrent execution.

**Инвариант 6**: Все payload и headers логируются только через `TargetSafeLogger`.
Прямые `logger.info(payload)` или `print(headers)` в core запрещены — redaction
гарантируется только через метод `safe_body()` / `redact_headers()`.

**Инвариант 7**: Мутация при retry — чистая функция. Оригинальный `RequestSpec`
не изменяется. Gateway хранит `current_spec` и заменяет его результатом мутации.

**Инвариант 8**: `TargetSpec` валидируется при загрузке (Pydantic). Некорректная
спецификация не достигает production runtime — ошибка возникает при инициализации.

**Инвариант 9**: Factory принимает только `runtime_mode='core'` (единственный
поддерживаемый режим). Любое другое значение → `ValueError` на старте.

**Инвариант 10**: Operation aliases являются публичным контрактом. Изменение aliases
в `TargetSpec` YAML — breaking change, требует синхронного обновления всех
использований в delivery/usecase.

---

## 15. Полная диаграмма потока данных

```
Delivery-команда (import_apply / cache_refresh / check_api)
  |
  | runtime = build_target_runtime(api_settings, ...)
  | runtime.executor / runtime.reader / runtime.check()
  v

DefaultTargetRuntime
  |
  v

TargetGateway.execute(RequestSpec(alias, params, payload))
  |
  +--> kernel.require_capability("execute")
  |      ValueError -> ExecutionResult(ok=False, SPEC)
  |
  +--> kernel.get_compiled_operation(alias)
  |      ValueError -> ExecutionResult(ok=False, SPEC)
  |
  +--> compiled.build(alias, operation_params)
  |      ValueError -> ExecutionResult(ok=False, SPEC)
  |      Exception  -> ExecutionResult(ok=False, INFRA_UNAVAILABLE)
  |
  | [RETRY LOOP]
  |
  +--> driver.execute(compiled_request, payload)
  |      |
  |      +--> DriverResponse(ok=True)
  |      |      result_builder.execute_success(resp)
  |      |        -> safe_body(resp.payload)  [REDACTION]
  |      |      -> ExecutionResult(ok=True, answer_code, response_payload)
  |      |         RETURN (success)
  |      |
  |      +--> DriverResponse(ok=False)
  |      |      fault_handler.from_driver_response(resp)
  |      |        -> normalizer.from_status(status_code)
  |      |             -> kernel.classify_fault(status_code)
  |      |             -> NormalizedFault(fault_kind, error_code)
  |      |        -> kernel.resolve_retry_action(fault_kind, status, reason)
  |      |             -> ResolvedRetryAction(directive, mutation)
  |      |      safe_logger.log_response_error(...)  [WARNING лог с редакцией]
  |      |
  |      +--> DriverError
  |      |      fault_handler.from_driver_error(exc)
  |      |        -> normalizer.from_status_or_code(status, error_code)
  |      |             -> kernel.classify_fault(status, error_code)
  |      |             -> NormalizedFault(fault_kind, error_code)
  |      |        -> kernel.resolve_retry_action(fault_kind, status, reason)
  |      |             -> ResolvedRetryAction(directive, mutation)
  |      |
  |      +--> Exception (unexpected)
  |             -> ExecutionResult(ok=False, INFRA_UNAVAILABLE)
  |                RETURN (unexpected failure)
  |
  +--> _apply_execute_retry(fault_kind, retry_action, retries_used, current_spec)
  |
  |    directive == "ESCALATE"?
  |      -> should_retry=False
  |         make_error(): error_details["escalated"]=True
  |         RETURN (escalated failure)
  |
  |    directive == "NO_RETRY"?
  |      -> should_retry=False
  |         make_error(): обычный error
  |         RETURN (terminal failure)
  |
  |    retries_used >= max_attempts?
  |      -> should_retry=False
  |         make_error(): budget exhausted
  |         RETURN (exhausted failure)
  |
  |    directive in {"RETRY_BACKOFF", "RETRY_AFTER"}:
  |      mutation?
  |        -> mutations.apply(name, current_spec)
  |             ValueError -> ExecutionResult(ok=False, SPEC)
  |      retries_used++, retries_total++
  |      directive=="RETRY_AFTER"? -> sleep_exact(retry_after_s)
  |      directive=="RETRY_BACKOFF"? -> sleep_before_retry(retries_used) [backoff+jitter]
  |      safe_logger.debug_retry(...)  [DEBUG лог]
  |      -> should_retry=True -> continue LOOP
  |
  v

ExecutionResult(ok, answer_code, response_payload, error_code, error_details, ...)
  |
  v
Delivery-команда
```

---

## 16. Примеры сценариев (end-to-end)

### Сценарий 1: Успешный upsert (200 OK)

```
RequestSpec(alias="users.upsert", params={"target_id": "u-42"}, payload={"name": "Alice"})
  |
  gateway.execute(spec)
    -> kernel.get_compiled_operation("users.upsert")
       compiled.build(alias, operation_params={"target_id": "u-42"})
       -> CompiledHttpRequest(method="PUT", path="/ankey/managed/user/u-42", ...)
    -> requests_total=1
    -> driver.execute(compiled_request, {"name": "Alice"})
       -> HTTP PUT /ankey/managed/user/u-42
       <- HTTP 200 {"id": "u-42", "name": "Alice"}
       DriverResponse(ok=True, answer_code=200, payload={...})
    -> result_builder.execute_success(resp)
       safe_body(resp.payload) -> {"id": "u-42", "name": "Alice"}  (нет секретов)
  |
  ExecutionResult(ok=True, answer_code=200, response_payload={"id": "u-42", "name": "Alice"})
  stats: (1, 0, 0)
```

### Сценарий 2: Retry при TRANSIENT (503 → 503 → 200)

```
RequestSpec(alias="users.upsert", params={"target_id": "u-42"}, ...)
  |
  gateway.execute(spec)  [max_attempts=3, backoff_base=0.5]

  -- Попытка 1 --
  requests_total=1
  driver.execute(...) <- HTTP 503 {"error": "service unavailable"}
  DriverResponse(ok=False, answer_code=503, ...)
  fault_handler.from_driver_response -> fault_kind="TRANSIENT"
  kernel.resolve_retry_action(TRANSIENT) -> RETRY_BACKOFF
  _apply_execute_retry: retries_used=0 < 3 -> can_retry=True
  retries_used=1, retries_total=1
  sleep_before_retry(1) ~0.5 сек

  -- Попытка 2 --
  requests_total=2
  driver.execute(...) <- HTTP 503 {"error": "still unavailable"}
  DriverResponse(ok=False, answer_code=503, ...)
  retries_used=1 < 3 -> can_retry=True
  retries_used=2, retries_total=2
  sleep_before_retry(2) ~1.0 сек

  -- Попытка 3 --
  requests_total=3
  driver.execute(...) <- HTTP 200 {"id": "u-42", "name": "Alice"}
  DriverResponse(ok=True, answer_code=200, ...)
  result_builder.execute_success(resp)
  |
  ExecutionResult(ok=True, answer_code=200, ...)
  stats: (3, 2, 0)
```

### Сценарий 3: Конфликт UUID с мутацией (409 resourceexists → regenerate → 200)

```
RequestSpec(alias="users.upsert", params={"target_id": "orig-001"}, payload={"name": "Bob"})
  |
  gateway.execute(spec)

  -- Попытка 1 --
  compiled.build(params={"target_id": "orig-001"})
  -> path="/ankey/managed/user/orig-001"
  requests_total=1
  driver.execute(...) <- HTTP 409 {"message": "resourceexists"}
  DriverResponse(ok=False, answer_code=409, error_reason="resourceexists", ...)
  fault_handler.from_driver_response -> fault_kind="CONFLICT"
  kernel.resolve_retry_action(
    fault_kind="CONFLICT", status_code=409, error_reason="resourceexists"
  )
  RetryRule(match_fault="CONFLICT", match_status=409, match_reason="resourceexists")
  -> ResolvedRetryAction(directive="RETRY_BACKOFF", mutation="regenerate_target_id")

  _apply_execute_retry:
    mutation "regenerate_target_id" применяется:
      new_params = {"target_id": "regen-uuid-5678"}
      current_spec = RequestSpec(alias="users.upsert", params={"target_id": "regen-uuid-5678"}, ...)
    retries_used=1, retries_total=1
    sleep_before_retry(1) ~0.5 сек

  -- Попытка 2 --
  compiled.build(params={"target_id": "regen-uuid-5678"})
  -> path="/ankey/managed/user/regen-uuid-5678"
  requests_total=2
  driver.execute(...) <- HTTP 200 {"id": "regen-uuid-5678", "name": "Bob"}
  DriverResponse(ok=True, answer_code=200, ...)
  result_builder.execute_success(resp)
  |
  ExecutionResult(ok=True, answer_code=200, ...)
  stats: (2, 1, 0)
```

### Сценарий 4: Throttle с Retry-After (429 → sleep → 200)

```
RequestSpec(alias="users.upsert", params={"target_id": "u-99"}, ...)
  |
  gateway.execute(spec)

  -- Попытка 1 --
  requests_total=1
  driver.execute(...) <- HTTP 429 {"error": "rate limited"}
  DriverResponse(ok=False, answer_code=429, retry_after_s=5.0, ...)
  fault_handler.from_driver_response -> fault_kind="THROTTLE"
  kernel.resolve_retry_action(THROTTLE) -> RETRY_AFTER

  _apply_execute_retry:
    directive="RETRY_AFTER" -> _compute_retry_delay:
      retry_engine.sleep_exact(5.0)  <- спит ровно 5 секунд
    retries_used=1, retries_total=1

  -- Попытка 2 --
  requests_total=2
  driver.execute(...) <- HTTP 200 {"id": "u-99", "name": "..."}
  DriverResponse(ok=True, answer_code=200, ...)
  result_builder.execute_success(resp)
  |
  ExecutionResult(ok=True, answer_code=200, ...)
  stats: (2, 1, 0)
```

### Сценарий 5: ESCALATE — немедленная остановка без retry

```
gateway с RetryRule(directive="ESCALATE", match_fault="TRANSIENT")

-- Попытка 1 --
requests_total=1
driver.execute(...) -> DriverError("network down")
fault_handler.from_driver_error -> fault_kind="TRANSIENT"
kernel.resolve_retry_action(TRANSIENT) -> ResolvedRetryAction(directive="ESCALATE")

_apply_execute_retry:
  directive "ESCALATE" not in {"RETRY_BACKOFF", "RETRY_AFTER"}
  -> should_retry=False (НЕМЕДЛЕННО, без проверки бюджета)

build_exc_details:
  mark_escalated(details) -> details["escalated"] = True

failures_total=1
ExecutionResult(ok=False, error_code=INFRA_UNAVAILABLE,
                error_details={"escalated": True, ...})
stats: (1, 0, 1)
```

---

## 17. Тестовое покрытие

### test_target_kernel.py

Файл: `tests/unit/infrastructure/test_target_kernel.py`

Структура тестов организована по классам (один класс = одна группа функциональности):

| Класс / функция | Что проверяется |
|---|---|
| `TestClassifyFault` | 10 тестов: точные статусы (401, 403, 400, 422, 404, 409, 429), диапазоны 5xx, error_code="NETWORK_ERROR", UNKNOWN, приоритет error_code над status |
| `TestRetryDirective` | 9 тестов: все FaultKind → RetryDirective; CONFLICT+resourceexists → mutation; CONFLICT без reason → NO_RETRY |
| `TestSystemErrorCode` | 6 тестов: маппинг AUTH→UNAUTHORIZED, PERMISSION→FORBIDDEN, DATA→DATA_INVALID, CONFLICT→CONFLICT, TRANSIENT→UNAVAILABLE, UNKNOWN→INTERNAL |
| `TestRedactHeaders` | 4 теста: Authorization, X-Ankey-Password, безопасные заголовки, смешанные |
| `TestRedactPayload` | 2 теста: поле password → "***", не-dict → as-is |
| `TestSafeBody` | 3 теста: режимы none, keys_only, truncated |
| Функции | spec property, resolve_operation, health alias, get_compiled_operation |

Особого внимания заслуживает тест `test_error_code_takes_priority_over_status`:

```python
def test_error_code_takes_priority_over_status(self, kernel: TargetKernel) -> None:
    result = kernel.classify_fault(status_code=401, error_code="NETWORK_ERROR")
    assert result == "TRANSIENT"  # error_code побеждает над статусом 401 (AUTH)
```

И тест компиляции операции с path-params:

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

Файл: `tests/unit/infrastructure/test_target_gateway.py`

Используется `StubDriver` — stub-реализация `TargetDriver`, принимающая список
`request_effects` (DriverResponse или Exception) для детерминированного управления
поведением.

`_make_gateway()` — фабрика: загружает реальный `ankey` spec через `load_target_spec`,
применяет overrides через `model_copy` (Pydantic v2), создаёт `TargetKernel` и
`TargetGateway` с `build_ankey_mutations()`.

| Тест | Что проверяется |
|---|---|
| `test_execute_happy_path_returns_ok_and_masks_response` | ok=True, response_payload redacted, stats=(1,0,0) |
| `test_execute_retries_on_transient_and_then_succeeds` | 503→200, stats=(2,1,0) |
| `test_execute_no_retry_on_auth_error` | 401→NO_RETRY, error_code=AUTH_UNAUTHORIZED, stats=(1,0,1) |
| `test_execute_retries_on_driver_error_and_exhausts` | 3xDriverError с бюджетом 2, stats=(3,2,1) |
| `test_execute_detects_resourceexists_reason` | 409+reason="resourceexists" → error_reason в результате |
| `test_execute_operation_alias_applies_resourceexists_mutation_and_retries` | mutation меняет path при retry |
| `test_execute_retries_on_retry_after_directive` | 429→RETRY_AFTER→200 |
| `test_execute_escalate_stops_retry_cycle` | ESCALATE → immediate failure, escalated=True в details |
| `test_execute_operation_alias_uses_spec_mapping` | path="/ankey/managed/user/user-42", method=PUT |
| `test_execute_operation_alias_unknown_returns_spec_error` | неизвестный alias → INTERNAL_ERROR, no I/O |
| `test_execute_operation_alias_missing_param_returns_spec_error` | отсутствие target_id → INTERNAL_ERROR |
| `test_iter_pages_happy_path_masks_items` | страницы, password="***" в items |
| `test_iter_pages_normalizes_driver_error` | DriverError → TargetPageResult(ok=False) |
| `test_iter_pages_normalizes_driver_error_and_sanitizes_details` | redaction details, truncation |
| `test_health_check_ok` | ok=True, latency_ms>=0 |
| `test_health_check_driver_error_maps_to_fault_and_code` | DriverError → TRANSIENT + INFRA_UNAVAILABLE |
| `test_health_check_unexpected_error_maps_to_transient` | RuntimeError → TRANSIENT |
| `test_health_check_uses_operation_catalog_alias` | path="/ankey/managed/user" |
| `test_reset_stats_resets_all_counters` | после reset все счётчики = 0 |
| `test_iter_pages_unknown_alias_returns_spec_error` | неизвестный alias → INTERNAL_ERROR |

Тест мутации с `monkeypatch.setattr` для детерминированного UUID:

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

## 18. FAQ

**Q: Почему ядро не знает об HTTP?**

A: Принцип `mechanism vs rules`. Ядро реализует универсальные механики: retry loop,
классификацию сбоев, редакцию, разрешение операций. HTTP — это конкретный транспорт.
Разделение позволяет добавить новый target-тип (например, gRPC или LDAP), написав
только новый Driver и зарегистрировав `OperationCompiler` для нового `kind`. Ядро при
этом не меняется. Инвариант закреплён в архитектурных guard-тестах.

**Q: Как добавить новый FaultKind?**

A: Новый `FaultKind` — это breaking change в контракте ядра. Необходимо:
1. Добавить значение в `TargetFaultKind = Literal[..., "NEW_KIND"]` в
   `connector/domain/target_dsl/spec_models.py`.
2. Добавить маппинг в `_FAULT_TO_SYSTEM` в `kernel.py`.
3. Обновить `FaultRule` в YAML-спецификации провайдеров где нужно.
4. Обновить тесты в `test_target_kernel.py`.
5. Проверить `RetryRule` — нужно ли добавить retry-правило для нового kind.

**Q: Что если Driver бросил неожиданное исключение (не DriverError)?**

A: В `execute()` есть блок `except Exception as exc` после `except DriverError`:

```python
except Exception as exc:
    self._failures_total += 1
    return self._result_builder.unexpected_failure(exc)
```

`unexpected_failure` возвращает `ExecutionResult(ok=False, error_code=INFRA_UNAVAILABLE,
error_message=truncateText(str(exc)))`. Исключение не пробивается наружу.

Аналогично в `iter_pages`:

```python
except Exception as exc:
    self._failures_total += 1
    yield _fail_page(SystemErrorCode.INFRA_UNAVAILABLE, truncateText(str(exc)))
    return
```

**Q: Как работает mutation при RETRY? Изменяется ли оригинальный RequestSpec?**

A: Нет. Мутация — чистая функция. `mutations.apply(name, spec)` возвращает новый
`RequestSpec`. Gateway заменяет `current_spec = mutations.apply(name, current_spec)`.
Оригинальный `spec`, переданный в `execute()`, не изменяется. `RequestSpec` является
frozen dataclass (`@dataclass(frozen=True)`).

**Q: Что значит ESCALATE в отличие от NO_RETRY?**

A: Оба приводят к `should_retry=False`, но:
- `NO_RETRY` — штатная ситуация: retry не предусмотрен для данного fault (например,
  AUTH-ошибка не имеет смысла ретраить без смены credentials).
- `ESCALATE` — критический сигнал: нужно немедленно прекратить retry и передать
  управление наверх с явным маркером. В `error_details` добавляется `{"escalated": True}`.
  Delivery может использовать этот флаг для специальной обработки (алерт, abort
  пайплайна и т.п.). Применяется для сценариев, когда retry противопоказан по бизнес-
  логике (например, критическая ошибка авторизации инфраструктуры).

**Q: Когда stats.failures_total инкрементируется?**

A: `failures_total` растёт при **любом** завершении операции неуспехом:
- `require_capability` вернул ошибку.
- Компиляция операции (`get_compiled_operation` / `compiled.build`) не удалась.
- `driver.execute()` бросил неожиданный `Exception` (не DriverError).
- Retry-бюджет исчерпан — `make_error()` вызван.
- `NO_RETRY` — операция завершена без повтора.
- `ESCALATE` — операция эскалирована.
- Мутация не зарегистрирована (spec error).

`failures_total` считает **операции** (единицы работы), а не попытки. Если была
503→503→200 — это 0 failures. Если 503→503→503 (budget exhausted) — это 1 failure.

**Q: Почему iter_pages не ретраит при ошибке после начала чтения?**

A: Идемпотентность. Если первые N страниц уже переданы в cache-refresh use-case,
повтор начнёт отдавать страницы с начала — данные продублируются в кэше. Безопаснее
выдать `TargetPageResult(ok=False)` и дать верхнему уровню решить, как обработать
частичный результат. Retry разрешён только на этапе до первой выданной страницы
(`last_page == 0`), когда никаких данных ещё не было передано.

**Q: Как structlog интегрируется с редакцией?**

A: `TargetSafeLogger` не пишет ни одно значение в лог без предварительного прохода
через redaction. Метод `log_response_error` применяет `safe_body(payload)` к
payload-у перед добавлением в log record. `debug_retry` не включает в лог никаких
бизнес-данных — только операционные метрики (fault_kind, delay, mutation_name).
Если structlog не установлен — все методы становятся no-op.

---

## 19. Связанные файлы

| Файл | Роль |
|---|---|
| `connector/infra/target/core/kernel.py` | TargetKernel — классификатор/резолвер |
| `connector/infra/target/core/gateway.py` | TargetGateway — retry owner |
| `connector/infra/target/core/runtime.py` | TargetRuntime Protocol + DefaultTargetRuntime |
| `connector/infra/target/core/factory.py` | build_target_runtime / build_target_runtime_with_info |
| `connector/infra/target/core/registry.py` | TargetProviderRegistry |
| `connector/infra/target/core/mutations.py` | TargetMutationRegistry + TargetMutation |
| `connector/infra/target/core/transport_compiler.py` | TransportCompilerRegistry + CompiledOperation |
| `connector/infra/target/core/models.py` | TargetMeta, TargetStats, TargetCheckResult, TargetConnectionConfig, TargetFaultKind |
| `connector/infra/target/core/spec_models.py` | re-export compatibility; source in domain/target_dsl |
| `connector/infra/target/core/engines/error_normalizer.py` | NormalizedFault, TargetErrorNormalizer |
| `connector/infra/target/core/engines/fault_handler.py` | TargetFaultHandler |
| `connector/infra/target/core/engines/result_builder.py` | TargetResultBuilder |
| `connector/infra/target/core/engines/retry_engine.py` | TargetRetryEngine (tenacity) |
| `connector/infra/target/core/engines/safe_logging.py` | TargetSafeLogger (structlog) |
| `connector/infra/target/driver.py` | TargetDriver Protocol, DriverResponse, DriverError |
| `connector/domain/target_dsl/spec_models.py` | TargetSpec, FaultRule, RetryRule, RetryConfig, OperationSpec, RedactionSpec |
| `connector/domain/ports/target/execution.py` | RequestSpec, ExecutionResult, RequestExecutorProtocol |
| `connector/domain/ports/target/read.py` | TargetPageResult, TargetPagedReaderProtocol |
| `connector/infra/target/providers/ankey_rest/` | AnkeyTargetProvider, AnkeyDriver, ankey mutations |
| `tests/unit/infrastructure/test_target_kernel.py` | unit-тесты TargetKernel |
| `tests/unit/infrastructure/test_target_gateway.py` | unit-тесты TargetGateway |
| `tests/architecture/test_target_layer_boundaries.py` | guard-тесты импортных границ |
| `docs/adr/target/TARGET-DEC-001-target-runtime-target-spec-slice.md` | ADR: TargetRuntime |
| `docs/adr/target/TARGET-DEC-003-target-core.md` | ADR: plugin-core модель |
