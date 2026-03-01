# Target Transport — протокол транспортного слоя и HTTP-реализация

> **Назначение**: изолировать I/O-протокол от ядра. TargetGateway говорит «выполни операцию»,
> транспорт знает «как именно» — PUT на `/ankey/managed/user/{id}`, gRPC-вызов, SFTP-запись.
> Транспорт никогда не ретраит и не нормализует ошибки в domain-типы.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Место в стеке](#место-в-стеке)
  - [Структура HTTP Transport](#структура-http-transport)
  - [Поток данных внутри HTTP Transport](#поток-данных-внутри-http-transport)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
  - [TargetDriver Protocol](#targetdriver-protocol)
  - [DriverResponse и DriverError](#driverresponse-и-drivererror)
  - [CompiledOperation Protocol](#compiledoperation-protocol)
  - [TransportCompilerRegistry](#transportcompilerregistry)
- [🗂️ Модели данных](#️-модели-данных)
  - [HttpOperationDataModel](#httpoperationdatamodel)
  - [CompiledHttpOperation](#compiledhtttpoperation)
  - [HttpRequest](#httprequest)
  - [HttpOutcome и HttpNormalizedOutcome](#httpoutcome-и-httpnormalizedoutcome)
  - [HttpClientSettings](#httpclientsettings)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
  - [request_once() — атомарная функция](#request_once--атомарная-функция)
  - [normalize_http_outcome()](#normalize_http_outcome)
  - [build_http_request() и подстановка path](#build_http_request-и-подстановка-path)
  - [BaseHttpDriver.execute()](#basehttpdriverexecute)
  - [BaseHttpDriver.iter_batches()](#basehttpdriveritr_batches)
  - [HttpPagingStrategy Protocol](#httppagingstrategy-protocol)
  - [build_http_client()](#build_http_client)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [🛠️ HOW-TO: Создание нового транспорта](#️-how-to-создание-нового-транспорта)
  - [Шаг 1: CompiledMyOperation](#шаг-1-compiledmyoperation)
  - [Шаг 2: MyOperationDataModel](#шаг-2-myoperationdatamodel)
  - [Шаг 3: Компилятор](#шаг-3-компилятор)
  - [Шаг 4: MyDriver](#шаг-4-mydriver)
  - [Шаг 5: Регистрация в TransportCompilerRegistry](#шаг-5-регистрация-в-transportcompilerregistry)
  - [Шаг 6: YAML-спецификация с новым kind](#шаг-6-yaml-спецификация-с-новым-kind)
  - [Шаг 7: Тестирование](#шаг-7-тестирование)
  - [Чеклист нового транспорта](#чеклист-нового-транспорта)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
  - [🚨 Failure Modes](#-failure-modes)
  - [⚠️ Инварианты транспортного слоя](#️-инварианты-транспортного-слоя)
  - [⏱️ Performance заметки](#️-performance-заметки)
- [🧪 Тестовое покрытие](#-тестовое-покрытие)
- [❓ FAQ](#-faq)
- [🔗 Связанные документы](#-связанные-документы)
- [📝 История изменений](#-история-изменений)

---

## 📋 Обзор

**Назначение**: реализовывать единственную I/O-попытку для каждого вызова Gateway, полностью
изолируя протокол передачи данных от ядра.

**Ключевая ответственность**:
- Выполнять ровно одну I/O-попытку на каждый вызов `execute()` / шаг `iter_batches()`
- Маппировать транспортные сбои (таймаут, обрыв соединения) в `DriverError`
- Возвращать `DriverResponse` при любом ответе приложения (даже ошибочном)
- Поддерживать постраничное чтение через `HttpPagingStrategy`

**Что транспорт знает**:
- Протокол (HTTP, gRPC, SFTP и т.д.)
- Сетевые параметры (timeout, connection pool, TLS)
- Аутентификацию (через `httpx.Auth` или другой механизм)
- Алгоритм пагинации (конкретный для каждого провайдера)

**Что транспорт не знает**:
- Retry-политику, `RetryConfig`, `RetryRule`, `RetryDirective`
- `TargetFaultKind`, `SystemErrorCode`, domain-типы ошибок
- Бизнес-логику конкретного API (поля `items/data/users` — это зона провайдера)

**Расположение в кодовой базе**:

```
connector/
├── infra/
│   └── target/
│       ├── driver.py                    # TargetDriver Protocol, DriverResponse, DriverError
│       └── transports/
│           └── http/
│               ├── __init__.py          # Публичные экспорты (17 имён)
│               ├── op_models.py         # HttpOperationDataModel (Pydantic)
│               ├── compiler.py          # CompiledHttpOperation, compile_http_operation()
│               ├── request_builder.py   # HttpRequest, build_http_request()
│               ├── request_once.py      # HttpOutcome, request_once()
│               ├── normalizer.py        # HttpNormalizedOutcome, normalize_http_outcome()
│               ├── paging.py            # HttpPagingStrategy Protocol
│               ├── driver_base.py       # BaseHttpDriver, HttpRequestOncePort
│               └── client_factory.py    # HttpClientSettings, build_http_client()
```

---

## 🏗️ Архитектура слоя

### Место в стеке

```
┌─────────────────────────────────────────────────────────┐
│              Application / Use Cases                     │
└──────────────────────┬──────────────────────────────────┘
                       │ RequestSpec
┌──────────────────────▼──────────────────────────────────┐
│                   TargetGateway                          │
│  (retry-политика, классификация ошибок, redaction)       │
│  Единственный владелец логики повторных попыток          │
└──────────────────────┬──────────────────────────────────┘
                       │ compiled_request + payload
┌──────────────────────▼──────────────────────────────────┐
│                   TargetDriver                           │
│  ТРАНСПОРТНЫЙ СЛОЙ — одна I/O-попытка, никакого retry   │
│  HTTP / gRPC / SFTP / ...                                │
└──────────────────────┬──────────────────────────────────┘
                       │ httpx.Client / grpc.Channel / ...
┌──────────────────────▼──────────────────────────────────┐
│                  Сетевой стек ОС                         │
└─────────────────────────────────────────────────────────┘
```

Граница ответственности:

| Уровень | Ответственность |
|---|---|
| `TargetGateway` | Retry-политика, классификация fault-kind, redaction payload |
| `TargetKernel` | Компиляция операций, lookup-таблицы fault/retry |
| `TargetDriver` | Одна I/O-попытка, маппинг сетевых ошибок в `DriverError` |
| `httpx.Client` | TCP-соединения, TLS, connection pool |

### Структура HTTP Transport

```
connector/infra/target/transports/http/
  ├── __init__.py          — публичные экспорты
  ├── op_models.py         — HttpOperationDataModel (Pydantic)
  ├── compiler.py          — CompiledHttpOperation, compile_http_operation()
  ├── request_builder.py   — HttpRequest, build_http_request()
  ├── request_once.py      — HttpOutcome, request_once()
  ├── normalizer.py        — HttpNormalizedOutcome, normalize_http_outcome()
  ├── paging.py            — HttpPagingStrategy (Protocol)
  ├── driver_base.py       — BaseHttpDriver, HttpRequestOncePort
  └── client_factory.py    — HttpClientSettings, build_http_client()
```

Зависимости между модулями:

```
driver_base.py
  ├── depends: request_once.py   (HttpOutcome, request_once)
  ├── depends: normalizer.py     (normalize_http_outcome)
  ├── depends: paging.py         (HttpPagingStrategy)
  ├── depends: request_builder.py (HttpRequest)
  └── depends: driver.py         (DriverResponse, DriverError)

compiler.py
  ├── depends: op_models.py      (HttpOperationDataModel)
  ├── depends: request_builder.py (build_http_request)
  └── depends: spec_models.py    (OperationSpec)

request_once.py
  └── depends: request_builder.py (HttpRequest)

normalizer.py
  └── depends: request_once.py   (HttpOutcome)
```

### Поток данных внутри HTTP Transport

```
Startup (один раз при инициализации TargetKernel):
  OperationSpec ──► compile_http_operation() ──► CompiledHttpOperation

Per-request (каждый вызов execute):
  CompiledHttpOperation.build(alias, operation_params, ...)
    -> HttpRequest(method, path, query, headers, expected_statuses)
  driver.execute(HttpRequest, payload)
    -> replace(req, json=payload)
    -> request_once(client, req) -> HttpOutcome
    -> normalize_http_outcome(outcome) -> HttpNormalizedOutcome
    -> _resolve_error_reason(body) -> str | None
    -> DriverError (если error_code)
    -> DriverResponse(ok=status in expected_statuses, ...)

Per-page (каждый шаг iter_batches):
  paging.build_paged_request(base_req, page, batch_size)
    -> page_req (добавлены page/rows/... параметры)
  request_once(client, page_req) -> HttpOutcome
  normalize_http_outcome -> HttpNormalizedOutcome
  paging.extract_items(body) -> list[Any]
  yield (page, items)
  STOP: items пустой / len<batch_size / page > max_batches
```

---

## 🔑 Ключевые абстракции

### TargetDriver Protocol

**Файл**: `connector/infra/target/driver.py`

Структурный Protocol в стиле duck typing — явного наследования не требуется.

```python
TCompiledRequest = TypeVar("TCompiledRequest")

class TargetDriver(Protocol[TCompiledRequest]):
    def execute(
        self,
        compiled_request: TCompiledRequest,
        payload: Any | None = None,
    ) -> DriverResponse: ...
    # При транспортном сбое raises DriverError (не возвращает)

    def iter_batches(
        self,
        compiled_request: TCompiledRequest,
        batch_size: int,
        max_batches: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterator[tuple[int, list[Any]]]: ...
    # (page_number, items); при ошибке raises DriverError

    def close(self) -> None: ...
    # Освобождает ресурсы; должен быть idempotent
```

**`execute(compiled_request, payload)`** — ровно одна I/O-попытка. `compiled_request` — opaque объект,
передаётся из `CompiledOperation.build()` напрямую в Driver без распаковки ядром.

**`iter_batches(compiled_request, batch_size, max_batches, params)`** — постраничный итератор.
Каждый yield — `(page_number, items)`. `max_batches=None` — читать до конца.

**`close()`** — освобождает TCP connection pool, файловые дескрипторы и т.д.

### DriverResponse и DriverError

```python
# connector/infra/target/driver.py

@dataclass(frozen=True, slots=True)
class DriverResponse:
    ok: bool                               # True если status_code in expected_statuses
    answer_code: int | str | None = None   # HTTP-статус или transport code
    payload: Any = None                    # Тело ответа (parsed JSON или str)
    content_preview: str | None = None    # Первые N символов тела для логов
    payload_format: ResponsePayloadFormat = "none"
    error_reason: str | None = None        # Provider-specific причина ошибки
    retry_after_s: float | None = None    # Значение Retry-After в секундах

class DriverError(Exception):
    def __init__(
        self,
        message: str,
        code: str = "NETWORK_ERROR",
        *,
        answer_code: int | str | None = None,
        content_preview: str | None = None,
        details: dict[str, Any] | None = None,
        retry_after_s: float | None = None,
        error_reason: str | None = None,
    ) -> None: ...
```

Разница между `DriverResponse(ok=False)` и `DriverError`:

```
Timeout / TCP reset        -> DriverError(code="NETWORK_ERROR")  [исключение]
HTTP 200 (ожидался)        -> DriverResponse(ok=True)            [возврат]
HTTP 409 (не ожидался)     -> DriverResponse(ok=False)           [возврат]
HTTP 500 (не ожидался)     -> DriverResponse(ok=False)           [возврат]
```

Стандартные значения `DriverError.code`:

| code | Когда |
|---|---|
| `NETWORK_ERROR` | `httpx.TimeoutException`, `httpx.TransportError` |
| `HTTP_OUTCOME_EMPTY` | Нет ни response, ни error в HttpOutcome |
| `HTTP_{status}` | Неожиданный статус при `iter_batches` (например `HTTP_409`) |
| `INVALID_ITEMS_FORMAT` | `extract_items()` подняло `ValueError` |
| `GRPC_UNAVAILABLE` | gRPC UNAVAILABLE / DEADLINE_EXCEEDED |

`error_reason` — provider-specific строка (например, `"resourceexists"`), извлечённая из тела
ответа функцией `error_reason_fn`. Используется ядром для `match_reason` в `RetryRule`.

`payload_format` определяется автоматически через `infer_response_payload_format(payload)`:

```python
def infer_response_payload_format(payload: Any) -> ResponsePayloadFormat:
    if payload is None:                           return "none"
    if isinstance(payload, (dict, list)):         return "json"
    if isinstance(payload, str):                  return "text"
    if isinstance(payload, (bytes, bytearray)):   return "bytes"
    return "object"
```

### CompiledOperation Protocol

**Файл**: `connector/infra/target/core/transport_compiler.py`

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
```

`CompiledOperation` — фабрика transport-specific запросов. Создаётся один раз при инициализации
`TargetKernel` и переиспользуется для каждого вызова execute.

Lifecycle:

```
Startup (один раз):
  OperationSpec ──► compiler_fn() ──► CompiledHttpOperation
                                      (хранится в TargetKernel)

Per-request:
  CompiledHttpOperation.build(alias, operation_params, ...) ──► HttpRequest
  driver.execute(HttpRequest, payload) ──► DriverResponse
```

Разделение compilation (статическая валидация) и build (runtime-параметры) позволяет обнаруживать
ошибки конфигурации при старте, а не при первом запросе.

### TransportCompilerRegistry

```python
# connector/infra/target/core/transport_compiler.py

OperationCompiler = Callable[[OperationSpec], CompiledOperation[Any]]

class TransportCompilerRegistry:
    def register(self, kind: str, compiler: OperationCompiler) -> None:
        # kind нормализуется в lowercase; дубликаты не запрещены (перезаписывают)
        ...

    def compile(self, operation: OperationSpec) -> CompiledOperation[Any]:
        # Ищет компилятор по operation.kind; ValueError если не зарегистрирован
        ...
```

`TargetKernel.__init__` вызывает `registry.compile(operation)` для каждой операции при старте.
Если хотя бы одна операция имеет незарегистрированный `kind` — ядро не запустится.

Поток от YAML до I/O:

```
datasets/targets/ankey.yaml
    operations:
      users.upsert:
        kind: http          ◄── ключ реестра
        expected_statuses: [200, 201]
        data:
          method: PUT
          path_template: /ankey/managed/user/{target_id}
              │
              ▼ registry.compile(op_spec) -> compile_http_operation
              ▼
    CompiledHttpOperation(op_data=..., expected_statuses=(200, 201))
              │
              ▼ .build(alias="users.upsert", operation_params={"target_id": "u-1"})
              ▼
    HttpRequest(method="PUT", path="/ankey/managed/user/u-1", ...)
              │
              ▼ driver.execute(HttpRequest, payload)
              ▼
    HTTP PUT https://ankey.local/ankey/managed/user/u-1
```

---

## 🗂️ Модели данных

### HttpOperationDataModel

```python
# connector/infra/target/transports/http/op_models.py

class HttpOperationDataModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path_template: str           # Обязательно начинается с '/'
    query_defaults: dict[str, Any] = Field(default_factory=dict)
    header_defaults: dict[str, str] = Field(default_factory=dict)
```

Pydantic-модель, описывающая HTTP-специфику одной операции. Хранится в `OperationSpec.data`
как opaque dict — ядро не интерпретирует его содержимое.

| Поле | Описание |
|---|---|
| `method` | HTTP-метод. Только верхний регистр |
| `path_template` | Путь с `{param}` плейсхолдерами. Обязательно начинается с `/` |
| `query_defaults` | Query-параметры по умолчанию; перекрываются через `query_overrides` |
| `header_defaults` | HTTP-заголовки по умолчанию; перекрываются через `header_overrides` |

Пример в YAML:

```yaml
operations:
  users.upsert:
    kind: http
    expected_statuses: [200, 201]
    data:
      method: PUT
      path_template: /ankey/managed/user/{target_id}
      query_defaults: {}
      header_defaults:
        Content-Type: application/json
```

### CompiledHttpOperation

```python
# connector/infra/target/transports/http/compiler.py

@dataclass(frozen=True, slots=True)
class CompiledHttpOperation:
    op_data: HttpOperationDataModel
    expected_statuses: tuple[int, ...]   # из OperationSpec.expected_statuses

    def build(
        self, *, alias, operation_params=None, query_overrides=None, header_overrides=None,
    ) -> HttpRequest: ...
```

Функция компиляции:

```python
def compile_http_operation(operation: OperationSpec) -> CompiledHttpOperation:
    if operation.kind != "http":
        raise ValueError(f"operation {operation.alias!r} is not http")
    if not operation.data:
        raise ValueError(f"operation {operation.alias!r} requires transport payload")
    return CompiledHttpOperation(
        op_data=HttpOperationDataModel.model_validate(operation.data),
        expected_statuses=operation.expected_statuses,
    )
```

Что происходит при компиляции:
1. Проверяется `operation.kind == "http"` — иначе `ValueError` немедленно
2. Проверяется наличие `operation.data`
3. `HttpOperationDataModel.model_validate(operation.data)` — Pydantic валидирует структуру
4. `@model_validator` проверяет `path_template.startswith("/")`
5. Результат — frozen dataclass, готовый к многократному `build()`

### HttpRequest

```python
# connector/infra/target/transports/http/request_builder.py

@dataclass(frozen=True, slots=True)
class HttpRequest:
    method: str
    path: str                           # Resolved path (без плейсхолдеров)
    query: dict[str, Any]               # Смёрженные query-параметры
    headers: dict[str, str]             # Смёрженные заголовки
    json: Any | None = None             # Тело запроса (устанавливается в BaseHttpDriver)
    timeout_s: float | None = None      # None → httpx.USE_CLIENT_DEFAULT
    expected_statuses: tuple[int, ...] = (200,)
```

Финальный transport-DTO перед отправкой. `json=None` при `execute()` — тело не отправляется.
Поле `json` устанавливается в `BaseHttpDriver.execute()` через `replace(req, json=payload)`.

### HttpOutcome и HttpNormalizedOutcome

```python
# connector/infra/target/transports/http/request_once.py

@dataclass(frozen=True, slots=True)
class HttpResponsePayload:
    status_code: int
    headers: dict[str, str]      # Все HTTP-заголовки ответа
    body: Any | None             # JSON-объект или str
    body_snippet: str | None     # Первые 200 символов строкового тела

@dataclass(frozen=True, slots=True)
class HttpErrorPayload:
    code: str                    # Категория: "NETWORK_ERROR"
    message: str
    details: dict[str, Any] | None = None

@dataclass(frozen=True, slots=True)
class HttpOutcome:
    response: HttpResponsePayload | None = None
    error: HttpErrorPayload | None = None
    # Инвариант: ровно одно из двух не-None

# connector/infra/target/transports/http/normalizer.py
@dataclass(frozen=True, slots=True)
class HttpNormalizedOutcome:
    status_code: int | None      # None при сетевой ошибке
    body: Any | None
    body_snippet: str | None
    error_code: str | None       # None при успешном HTTP-ответе
    error_message: str | None
    retry_after_s: float | None  # Из заголовка Retry-After
```

### HttpClientSettings

```python
# connector/infra/target/transports/http/client_factory.py

@dataclass(frozen=True, slots=True)
class HttpClientSettings:
    base_url: str

    # Таймауты
    timeout_seconds: float = 20.0
    connect_timeout_seconds: float | None = None
    read_timeout_seconds: float | None = None
    write_timeout_seconds: float | None = None
    pool_timeout_seconds: float | None = None

    # Connection pool
    max_connections: int = 100
    max_keepalive_connections: int = 20
    keepalive_expiry_seconds: float | None = 5.0

    # TLS
    tls_skip_verify: bool = False
    ca_file: str | None = None

    # Инжекция (для тестов)
    transport: httpx.BaseTransport | None = None

    # Дополнительно
    default_headers: dict[str, str] = field(default_factory=dict)
    event_hooks: HttpEventHooks | None = None
    auth: httpx.Auth | None = None
    proxy: str | None = None
```

---

## 📊 Ключевые методы и алгоритмы

### request_once() — атомарная функция

**Файл**: `connector/infra/target/transports/http/request_once.py`

`request_once` — сердце транспортного слоя. Одна функция, одна попытка, никакого retry.

```python
_BODY_SNIPPET_LIMIT = 200

def request_once(client: httpx.Client, req: HttpRequest) -> HttpOutcome:
    try:
        response = client.request(
            req.method, req.path,
            params=req.query or None,
            headers=req.headers or None,
            json=req.json,
            timeout=req.timeout_s if req.timeout_s is not None else httpx.USE_CLIENT_DEFAULT,
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        return HttpOutcome(error=HttpErrorPayload(code="NETWORK_ERROR", message=str(exc)))

    body, body_snippet = _parse_body(response)
    return HttpOutcome(response=HttpResponsePayload(
        status_code=response.status_code,
        headers=dict(response.headers),
        body=body,
        body_snippet=body_snippet,
    ))
```

Логика парсинга тела:
1. Берётся `response.text` (строка)
2. `body_snippet` = первые 200 символов строки
3. Если `response.json()` успешно — `body` = dict/list
4. Иначе fallback — `body` = текст as-is

Что перехватывается:

| Исключение httpx | Результат |
|---|---|
| `httpx.TimeoutException` | `HttpErrorPayload(code="NETWORK_ERROR")` |
| `httpx.TransportError` | `HttpErrorPayload(code="NETWORK_ERROR")` |
| Любое другое | **Не перехватывается** — всплывает наверх как unexpected |

`httpx.InvalidURL` и подобные намеренно не перехватываются — они сигнализируют о программной
ошибке конфигурации, а не о сетевом сбое.

### normalize_http_outcome()

**Файл**: `connector/infra/target/transports/http/normalizer.py`

Переводит `HttpOutcome` в стабильный `HttpNormalizedOutcome`.

```python
def normalize_http_outcome(outcome: HttpOutcome) -> HttpNormalizedOutcome:
    if outcome.error is not None:
        # Сетевая ошибка: нет status_code, нет body
        return HttpNormalizedOutcome(
            status_code=None, body=None, body_snippet=None,
            error_code=outcome.error.code,
            error_message=outcome.error.message,
            retry_after_s=None,
        )
    if outcome.response is None:
        # Защитная ветка: пустой outcome
        return HttpNormalizedOutcome(
            status_code=None, body=None, body_snippet=None,
            error_code="HTTP_OUTCOME_EMPTY",
            error_message="empty http outcome",
            retry_after_s=None,
        )

    retry_after_s = _parse_retry_after(
        _header_value_case_insensitive(outcome.response.headers, "Retry-After")
    )
    return HttpNormalizedOutcome(
        status_code=outcome.response.status_code,
        body=outcome.response.body,
        body_snippet=outcome.response.body_snippet,
        error_code=None,       # Нормализатор не оценивает статус — это делает Driver
        error_message=None,
        retry_after_s=retry_after_s,
    )
```

**Важно**: нормализатор не оценивает `status_code`. Решение `ok/not ok` принимает `BaseHttpDriver`,
который знает `expected_statuses` из `HttpRequest`.

Парсинг `Retry-After` (case-insensitive):

```python
def _parse_retry_after(value: str | None) -> float | None:
    if not value: return None
    candidate = value.strip()
    # Вариант 1: число секунд ("5", "30.0")
    try:
        seconds = float(candidate)
        return seconds if seconds >= 0 else None
    except ValueError:
        pass
    # Вариант 2: HTTP-date формат ("Wed, 01 Jan 2025 12:00:00 GMT")
    try:
        when = parsedate_to_datetime(candidate)
        delta = (when - datetime.now(timezone.utc)).total_seconds()
        return delta if delta > 0 else 0.0
    except (TypeError, ValueError):
        return None
```

### build_http_request() и подстановка path

**Файл**: `connector/infra/target/transports/http/request_builder.py`

```python
def build_http_request(
    *, alias, op_data, operation_params=None, query_overrides=None, header_overrides=None,
) -> HttpRequest:
    path = _render_path_template(alias=alias, path_template=op_data.path_template, params=operation_params)
    query = dict(op_data.query_defaults)
    if query_overrides:
        query.update(query_overrides)      # override имеет приоритет
    headers = dict(op_data.header_defaults)
    if header_overrides:
        headers.update(header_overrides)   # override имеет приоритет
    return HttpRequest(method=op_data.method, path=path, query=query, headers=headers)
```

Алгоритм подстановки path (`{param}` синтаксис):

```python
_PATH_TEMPLATE_PARAM_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

def _render_path_template(*, alias, path_template, params) -> str:
    params = params or {}
    required = _PATH_TEMPLATE_PARAM_RE.findall(path_template)
    missing = [name for name in required if name not in params]
    if missing:
        raise ValueError(f"operation {alias!r} missing path params: {', '.join(sorted(missing))}")
    return path_template.format(**params)
```

Примеры подстановки:

| path_template | operation_params | Результат |
|---|---|---|
| `/ankey/managed/user/{target_id}` | `{"target_id": "u-42"}` | `/ankey/managed/user/u-42` |
| `/ankey/managed/user/{target_id}` | `{}` | `ValueError: missing path params: target_id` |
| `/ankey/managed/user` | `{"target_id": "u-42"}` | `/ankey/managed/user` (лишние игнорируются) |
| `/org/{org_id}/user/{user_id}` | `{"org_id": "o-1"}` | `ValueError: missing: user_id` |

Порядок merge для query и headers:

```
query_defaults (из op_data YAML)   ←   query_overrides (runtime, страницы и т.п.)
header_defaults (из op_data YAML)  ←   header_overrides (runtime)
        override перекрывает defaults
```

### BaseHttpDriver.execute()

**Файл**: `connector/infra/target/transports/http/driver_base.py`

```python
class BaseHttpDriver:
    def __init__(
        self, client, paging, *,
        error_reason_fn=None,
        request_fn=request_once,  # Инжектируется в тестах
    ) -> None: ...

    def execute(self, compiled_request, payload=None) -> DriverResponse:
        req: HttpRequest = compiled_request
        outcome = self._request_fn(self._client, replace(req, json=payload))
        normalized = normalize_http_outcome(outcome)
        error_reason = self._resolve_error_reason(normalized.body, normalized.body_snippet)

        if normalized.error_code is not None:
            raise DriverError(
                normalized.error_message or normalized.error_code,
                code=normalized.error_code,
                answer_code=normalized.status_code,
                content_preview=normalized.body_snippet,
                retry_after_s=normalized.retry_after_s,
                error_reason=error_reason,
            )
        if normalized.status_code is None:
            raise DriverError("empty http response", code="HTTP_OUTCOME_EMPTY")

        return DriverResponse(
            ok=normalized.status_code in req.expected_statuses,
            answer_code=normalized.status_code,
            payload=normalized.body,
            content_preview=normalized.body_snippet,
            payload_format=infer_response_payload_format(normalized.body),
            error_reason=error_reason,
            retry_after_s=normalized.retry_after_s,
        )
```

`HttpRequestOncePort` — Protocol для инжекции `request_fn` в тестах:

```python
class HttpRequestOncePort(Protocol):
    def __call__(self, client: httpx.Client, req: HttpRequest) -> HttpOutcome: ...
```

### BaseHttpDriver.iter_batches()

```python
def iter_batches(self, compiled_request, batch_size, max_batches, params=None):
    req: HttpRequest = compiled_request
    base_req = replace(req, query={**req.query, **params}) if params else req

    page = 1
    while True:
        if max_batches is not None and page > max_batches:
            break

        page_req = self._paging.build_paged_request(base_req, page, batch_size)
        outcome = self._request_fn(self._client, page_req)
        normalized = normalize_http_outcome(outcome)
        error_reason = self._resolve_error_reason(normalized.body, normalized.body_snippet)

        if normalized.error_code is not None:
            raise DriverError(normalized.error_message or normalized.error_code, ...)
        if normalized.status_code not in req.expected_statuses:
            raise DriverError(f"target answer {normalized.status_code}", code=f"HTTP_{normalized.status_code}", ...)

        try:
            items = self._paging.extract_items(normalized.body)
        except ValueError as exc:
            raise DriverError(str(exc), code="INVALID_ITEMS_FORMAT") from exc

        if not items:
            break                   # Пустая страница — конец данных
        yield page, items
        if len(items) < batch_size:
            break                   # Неполная страница — конец данных
        page += 1
```

Условия остановки итерации:

| Условие | Действие |
|---|---|
| `page > max_batches` | `break` |
| Сетевая ошибка | `raise DriverError` |
| `status_code not in expected_statuses` | `raise DriverError(code="HTTP_{status}")` |
| `extract_items()` подняло `ValueError` | `raise DriverError(code="INVALID_ITEMS_FORMAT")` |
| `len(items) == 0` | `break` (сервер вернул пустую страницу) |
| `len(items) < batch_size` | `break` (последняя неполная страница) |

**Ключевое отличие от `execute()`**: при `iter_batches` неожиданный статус → `DriverError`,
а не `DriverResponse(ok=False)`. Итерация не может продолжаться с частичными данными.

### HttpPagingStrategy Protocol

**Файл**: `connector/infra/target/transports/http/paging.py`

```python
class HttpPagingStrategy(Protocol):
    def build_paged_request(self, base_req: HttpRequest, page: int, batch_size: int) -> HttpRequest:
        # Добавить page/size параметры. НЕ мутирует base_req (frozen dataclass)
        ...

    def extract_items(self, body: Any) -> list[Any]:
        # Вернуть список элементов из body.
        # Пустой список [] — валидный сигнал конца данных.
        # Raises: ValueError если формат не распознан
        ...
```

Эталонная реализация `AnkeyPagingStrategy` (из `providers/ankey_rest/driver.py`):

```python
class AnkeyPagingStrategy:
    _ITEMS_KEYS = ("items", "data", "users", "organizations", "orgs", "result")

    def build_paged_request(self, base_req, page, batch_size) -> HttpRequest:
        query = {**base_req.query, "page": page, "rows": batch_size}
        query.setdefault("_queryFilter", "true")
        return replace(base_req, query=query)   # dataclasses.replace — не мутирует

    def extract_items(self, body) -> list[Any]:
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            for key in self._ITEMS_KEYS:
                if key in body and isinstance(body[key], list):
                    return body[key]
        raise ValueError("Unexpected response format: no items array")
```

`build_paged_request()` должен возвращать **новый** `HttpRequest` через `dataclasses.replace()`.

### build_http_client()

```python
# connector/infra/target/transports/http/client_factory.py

def build_http_client(settings: HttpClientSettings) -> httpx.Client:
    verify = False if settings.tls_skip_verify else (settings.ca_file or True)

    timeout = httpx.Timeout(
        settings.timeout_seconds,
        connect=settings.connect_timeout_seconds or settings.timeout_seconds,
        read=settings.read_timeout_seconds or settings.timeout_seconds,
        write=settings.write_timeout_seconds or settings.timeout_seconds,
        pool=settings.pool_timeout_seconds or settings.timeout_seconds,
    )
    limits = httpx.Limits(
        max_connections=settings.max_connections,
        max_keepalive_connections=settings.max_keepalive_connections,
        keepalive_expiry=settings.keepalive_expiry_seconds,
    )
    return httpx.Client(
        base_url=settings.base_url.rstrip("/"),
        timeout=timeout, verify=verify, limits=limits,
        transport=settings.transport,          # None в prod, MockTransport в тестах
        headers=dict(settings.default_headers),
        event_hooks=settings.event_hooks,
        auth=settings.auth,
        proxy=settings.proxy,
    )
```

`transport=settings.transport` используется для инжекции `httpx.MockTransport` в тестах.

**Почему httpx.Client не содержит retry**: retry управляется на уровне `TargetGateway`.
Retry в httpx был бы невидим для Gateway, нарушил бы подсчёт попыток, задержки по
`Retry-After` и мутации payload между повторами.

---

## 🔄 Взаимодействие с другими слоями

**Транспорт ↔ Провайдер**:

```
Транспорт (HTTP, gRPC):
  - Знает: протокол, сериализацию, TCP-параметры
  - Не знает: бизнес-логику, retry-правила, конкретный API

Провайдер (Ankey, MyGrpc):
  - Создаёт транспортный клиент (httpx.Client с нужными настройками)
  - Регистрирует компилятор (registry.register("http", compile_http_operation))
  - Реализует HttpPagingStrategy (Ankey-специфичные ключи items/data/users/...)
  - Реализует error_reason_fn (детектит "resourceexists" из тела)
  - Настраивает auth (AnkeyAuth с Basic Auth credentials)
  - Передаёт Driver в TargetGateway
```

Пример сборки `AnkeyHttpDriver` (из провайдера):

```python
def build_core_runtime(self, *, transport=None, include_reader=True):
    from connector.domain.target_dsl import load_target_spec   # lazy import
    spec = load_target_spec("ankey")
    spec = apply_retry_overrides(spec, api)

    kernel = TargetKernel(spec, compiler_registry=build_transport_compiler_registry())
    # ^ build_transport_compiler_registry регистрирует compile_http_operation для "http"

    client = build_http_client(HttpClientSettings(
        base_url=base_url, timeout_seconds=api.timeout_seconds,
        tls_skip_verify=api.tls_skip_verify,
        transport=transport,
        auth=AnkeyAuth(username=api.username, password=api.password),
    ))
    driver = AnkeyHttpDriver(client)  # BaseHttpDriver + AnkeyPagingStrategy + error_reason_fn
    gateway = TargetGateway(driver, kernel, mutation_registry=...)
    return DefaultTargetRuntime(gateway=gateway, ...)
```

Один провайдер может регистрировать несколько `kind` — основные операции через HTTP,
streaming-чтение через gRPC. `driver` в этом случае обрабатывает оба типа `compiled_request`.

**Публичные экспорты пакета** (`transports/http/__init__.py`):

| Имя | Источник |
|---|---|
| `BaseHttpDriver`, `HttpRequestOncePort` | `driver_base.py` |
| `HttpClientSettings`, `build_http_client` | `client_factory.py` |
| `CompiledHttpOperation`, `compile_http_operation`, `compile_http_operation_data` | `compiler.py` |
| `HttpNormalizedOutcome`, `normalize_http_outcome` | `normalizer.py` |
| `HttpOperationDataModel` | `op_models.py` |
| `HttpPagingStrategy` | `paging.py` |
| `HttpRequest`, `build_http_request` | `request_builder.py` |
| `HttpErrorPayload`, `HttpOutcome`, `HttpResponsePayload`, `request_once` | `request_once.py` |

Провайдеры и тесты должны импортировать из этого пакета, а не из внутренних модулей.

---

## 🔌 Контракты и границы

**Импортные ограничения транспорта**:

| Запрет | Причина |
|---|---|
| NO import из `connector.domain.ports` | Нарушение boundary; domain ports — для delivery |
| NO import `tenacity` | Retry принадлежит Gateway, не транспорту |
| NO retry-логика в `execute()` | Нарушает подсчёт Gateway, ломает мутации |
| NO нормализация в domain-типы | `DriverResponse` и `DriverError` — граница транспорта |

**Контракт `DriverError` vs `DriverResponse(ok=False)`**:

```
DriverResponse(ok=False, answer_code=409):
  - Соединение состоялось
  - Сервер получил запрос
  - Сервер вернул HTTP-ответ (409 Conflict)
  - Gateway: classify_fault(status_code=409) → CONFLICT → retry по правилам

DriverError(code="NETWORK_ERROR"):
  - Соединение не состоялось (TCP timeout, SSL failure, etc.)
  - Нет HTTP-ответа вообще
  - Gateway: classify_fault(error_code="NETWORK_ERROR") → TRANSIENT → retry
```

Оба случая могут привести к retry — но через разные пути классификации в `TargetKernel`.

---

## 🛠️ HOW-TO: Создание нового транспорта

Пошаговое руководство для добавления нового транспорта (пример: gRPC).

### Шаг 1: CompiledMyOperation

Создайте frozen dataclass для transport-specific запроса и скомпилированной операции:

```python
# connector/infra/target/transports/grpc/compiled.py

@dataclass(frozen=True, slots=True)
class GrpcCompiledRequest:
    service: str
    method: str
    expected_statuses: tuple[int, ...]    # gRPC: 0 = OK

@dataclass(frozen=True, slots=True)
class CompiledGrpcOperation:
    service: str
    method: str
    expected_statuses: tuple[int, ...]

    def build(
        self, *, alias, operation_params=None, query_overrides=None, header_overrides=None,
    ) -> GrpcCompiledRequest:
        # gRPC не использует query/header overrides в том же смысле,
        # но сигнатура ДОЛЖНА совпадать с CompiledOperation Protocol
        return GrpcCompiledRequest(
            service=self.service, method=self.method,
            expected_statuses=self.expected_statuses,
        )
```

Требования:
- `frozen=True` — объект создаётся один раз и переиспользуется
- `build()` принимает runtime-параметры, возвращает transport-specific request
- Возвращаемый тип `build()` — opaque для ядра

### Шаг 2: MyOperationDataModel

Pydantic-модель, интерпретирующая `OperationSpec.data`:

```python
# connector/infra/target/transports/grpc/op_models.py

class GrpcOperationDataModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    service: str    # Полное имя gRPC-сервиса ("UserService")
    method: str     # Имя метода ("UpsertUser")
```

### Шаг 3: Компилятор

```python
# connector/infra/target/transports/grpc/compiler.py

def compile_grpc_operation(operation: OperationSpec) -> CompiledGrpcOperation:
    if operation.kind != "grpc":
        raise ValueError(f"operation {operation.alias!r}: ожидался kind='grpc'")
    if not operation.data:
        raise ValueError(f"operation {operation.alias!r}: требуется поле data")
    data = GrpcOperationDataModel.model_validate(operation.data)
    return CompiledGrpcOperation(
        service=data.service, method=data.method,
        expected_statuses=operation.expected_statuses,
    )
```

### Шаг 4: MyDriver

```python
# connector/infra/target/transports/grpc/driver.py

class GrpcDriver:
    def __init__(self, channel: grpc.Channel) -> None:
        self._channel = channel

    def execute(self, compiled_request: GrpcCompiledRequest, payload=None) -> DriverResponse:
        """Ровно один gRPC-вызов. Никакого retry."""
        try:
            stub = self._get_stub(compiled_request.service)
            method = getattr(stub, compiled_request.method)
            result = method(self._build_grpc_request(payload))
            return DriverResponse(
                ok=grpc.StatusCode.OK.value[0] in compiled_request.expected_statuses,
                answer_code=grpc.StatusCode.OK.value[0],
                payload=self._parse_response(result),
            )
        except grpc.RpcError as exc:
            status_code = exc.code().value[0]
            if exc.code() in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                raise DriverError(str(exc.details()), code="GRPC_UNAVAILABLE", answer_code=status_code)
            return DriverResponse(ok=False, answer_code=status_code, error_reason=exc.details())
        except Exception as exc:
            raise DriverError(str(exc), code="GRPC_ERROR") from exc

    def iter_batches(self, compiled_request, batch_size, max_batches, params=None):
        page = 1
        while True:
            if max_batches is not None and page > max_batches:
                break
            try:
                items = self._fetch_page(compiled_request, page, batch_size, params)
            except grpc.RpcError as exc:
                raise DriverError(str(exc), code="GRPC_ERROR") from exc
            if not items:
                break
            yield page, items
            if len(items) < batch_size:
                break
            page += 1

    def close(self) -> None:
        self._channel.close()
```

**Обязательные инварианты**:
- Ровно одна I/O-попытка в `execute()` — никаких `for attempt`, никакого tenacity
- Транспортный сбой → `raise DriverError(...)`
- Приложение ответило (с любым кодом) → `return DriverResponse(ok=...)`
- `close()` должен быть idempotent

### Шаг 5: Регистрация в TransportCompilerRegistry

```python
# connector/infra/target/providers/my_grpc/provider.py

def build_grpc_compiler_registry() -> TransportCompilerRegistry:
    registry = TransportCompilerRegistry()
    registry.register("grpc", compile_grpc_operation)
    return registry

class MyGrpcTargetProvider:
    target_type = "my_grpc"

    def build_core_runtime(self, *, transport=None, include_reader=True):
        from connector.domain.target_dsl import load_target_spec   # lazy: circular import
        spec = load_target_spec("my_grpc")
        channel = grpc.secure_channel(self._address, grpc.ssl_channel_credentials())
        driver = GrpcDriver(channel)
        kernel = TargetKernel(spec, compiler_registry=build_grpc_compiler_registry())
        gateway = TargetGateway(driver, kernel)
        return DefaultTargetRuntime(gateway=gateway, ...)
```

### Шаг 6: YAML-спецификация с новым kind

Создайте `datasets/targets/my_grpc.yaml`:

```yaml
target_type: my_grpc
capabilities:
  - execute
  - read_paged

fault_rules:
  - match_error_code: GRPC_UNAVAILABLE
    fault_kind: TRANSIENT
  - match_error_code: GRPC_ERROR
    fault_kind: UNKNOWN

retry_rules:
  - match_fault: TRANSIENT
    directive: RETRY_BACKOFF

retry_config:
  max_attempts: 3
  backoff_base: 1.0

redaction:
  forbidden_metadata_keys: []
  forbidden_fields: [password, token]
  body_mode: truncated

health:
  operation_alias: health.ping

operations:
  health.ping:
    kind: grpc
    expected_statuses: [0]   # gRPC OK = 0
    data:
      service: HealthService
      method: Check

  users.upsert:
    kind: grpc
    expected_statuses: [0]
    data:
      service: UserService
      method: UpsertUser
```

Зарегистрируйте в `datasets/registry.yml`:

```yaml
targets:
  ankey: datasets/targets/ankey.yaml
  my_grpc: datasets/targets/my_grpc.yaml   # ← новый провайдер
```

### Шаг 7: Тестирование

**Unit-тест компилятора**:

```python
def test_compile_grpc_operation_valid():
    op = OperationSpec(alias="users.upsert", kind="grpc",
                       expected_statuses=(0,), data={"service": "UserService", "method": "UpsertUser"})
    compiled = compile_grpc_operation(op)
    assert compiled.service == "UserService"
    assert compiled.method == "UpsertUser"

def test_compile_grpc_operation_wrong_kind():
    with pytest.raises(ValueError, match="ожидался kind='grpc'"):
        compile_grpc_operation(OperationSpec(..., kind="http", ...))
```

**Паттерн `httpx.MockTransport`** (для HTTP-транспорта):

```python
def _make_client(transport: httpx.BaseTransport) -> httpx.Client:
    return build_http_client(HttpClientSettings(
        base_url="https://ankey.local",
        transport=transport,   # ← Инжекция mock
    ))

def test_request_once_200():
    def responder(request): return httpx.Response(200, json={"ok": True})
    client = _make_client(httpx.MockTransport(responder))
    outcome = request_once(client, HttpRequest(method="GET", path="/test", ...))
    assert outcome.response.status_code == 200
```

**Инжекция `request_fn`** (для `BaseHttpDriver` без httpx):

```python
def mock_request_fn(client, req) -> HttpOutcome:
    return HttpOutcome(response=HttpResponsePayload(status_code=200, headers={}, body={"ok": True}, body_snippet='...'))

driver = BaseHttpDriver(client=MagicMock(), paging=SomePagingStrategy(), request_fn=mock_request_fn)
```

**Сквозной тест через `TargetGateway`**:

```python
def test_gateway_with_mock_driver():
    mock_driver = MagicMock()
    mock_driver.execute.return_value = DriverResponse(ok=True, answer_code=0)
    # gateway = TargetGateway(mock_driver, kernel)
    # result = gateway.execute(RequestSpec(...))
    # assert result.ok is True
```

### Чеклист нового транспорта

| Пункт | Обязательно | Файл |
|---|:---:|---|
| `GrpcCompiledRequest` dataclass (transport-specific request) | ✓ | `transports/grpc/compiled.py` |
| `CompiledGrpcOperation` с методом `build()` | ✓ | `transports/grpc/compiled.py` |
| `GrpcOperationDataModel` (`extra="forbid"`, `frozen=True`) | ✓ | `transports/grpc/op_models.py` |
| `compile_grpc_operation(op_spec) -> CompiledGrpcOperation` | ✓ | `transports/grpc/compiler.py` |
| `GrpcDriver` — реализует `TargetDriver` Protocol | ✓ | `transports/grpc/driver.py` |
| `execute()`: ровно одна попытка, никакого retry | ✓ | `transports/grpc/driver.py` |
| `execute()`: транспортный сбой → `raise DriverError` | ✓ | `transports/grpc/driver.py` |
| `execute()`: приложение ответило → `return DriverResponse` | ✓ | `transports/grpc/driver.py` |
| `iter_batches()` если capability `read_paged` | — | `transports/grpc/driver.py` |
| `close()` освобождает ресурсы (idempotent) | ✓ | `transports/grpc/driver.py` |
| Регистрация в `TransportCompilerRegistry` | ✓ | `providers/my_grpc/provider.py` |
| YAML target spec с `kind: grpc` в операциях | ✓ | `datasets/targets/my_grpc.yaml` |
| Запись в `datasets/registry.yml` | ✓ | `datasets/registry.yml` |
| Unit-тест компилятора (valid / wrong kind / missing data) | ✓ | `tests/unit/infrastructure/` |
| Unit-тест Driver.execute() с mock | ✓ | `tests/unit/infrastructure/` |
| NO import из `connector.domain.ports` в транспорте | ✓ | — |
| NO import `tenacity` в транспорте | ✓ | — |

---

## 💡 Типичные сценарии

**Успешный HTTP PUT**:

```
execute(HttpRequest(method="PUT", path="/ankey/managed/user/u-1"), payload={"name": "Alice"})
  -> replace(req, json={"name": "Alice"})
  -> request_once(client, req)
     <- HTTP 200 {"id": "u-1", "name": "Alice"}
  -> HttpOutcome(response=HttpResponsePayload(status_code=200, body={...}))
  -> normalize_http_outcome -> HttpNormalizedOutcome(status_code=200, error_code=None)
  -> ok=(200 in expected_statuses=(200, 201)) = True
  -> DriverResponse(ok=True, answer_code=200, payload={...})
```

**Сетевой сбой (TCP timeout)**:

```
execute(HttpRequest(...), payload=...)
  -> request_once(client, req)
     <- httpx.TimeoutException
  -> HttpOutcome(error=HttpErrorPayload(code="NETWORK_ERROR", message="..."))
  -> normalize_http_outcome -> HttpNormalizedOutcome(status_code=None, error_code="NETWORK_ERROR")
  -> raise DriverError("...", code="NETWORK_ERROR")
```

**Неожиданный статус при iter_batches**:

```
iter_batches(compiled_request, batch_size=100, max_batches=5)
  page=2:
    request_once -> HTTP 409 (неожиданный)
    normalized.status_code=409 not in expected_statuses=(200,)
    raise DriverError("target answer 409", code="HTTP_409")
```

**Пагинация Ankey (3 страницы)**:

```
iter_batches("users.list", page_size=100, max_batches=3)
  page=1: AnkeyPagingStrategy.build_paged_request -> ?page=1&rows=100&_queryFilter=true
          -> 100 items; yield (1, [...100...])
  page=2: -> 100 items; yield (2, [...100...])
  page=3: -> 73 items;  yield (3, [...73...])
          len(73) < batch_size(100) -> break (последняя страница)
```

---

## 📌 Важные детали

### 🚨 Failure Modes

| Режим отказа | Причина | Результат |
|---|---|---|
| `httpx.TimeoutException` | TCP timeout | `DriverError(code="NETWORK_ERROR")` |
| `httpx.TransportError` | SSL failure, разрыв | `DriverError(code="NETWORK_ERROR")` |
| Другие httpx exceptions | Программная ошибка config | **Не перехватываются** → Gateway → unexpected_failure |
| `extract_items()` → `ValueError` | Неожиданный формат тела | `DriverError(code="INVALID_ITEMS_FORMAT")` |
| Пустой `HttpOutcome` | Защитная ветка | `DriverError(code="HTTP_OUTCOME_EMPTY")` |
| Неожиданный status в `iter_batches` | API ответил не тем кодом | `DriverError(code="HTTP_{status}")` |

### ⚠️ Инварианты транспортного слоя

| # | Инвариант |
|---|---|
| 1 | Driver НИКОГДА не ретраит — ровно одна I/O-попытка на вызов |
| 2 | Driver НИКОГДА не нормализует ошибки в domain-типы (`TargetFaultKind`, `SystemErrorCode`) |
| 3 | Driver НИКОГДА не читает `RetryConfig`, `RetryRule`, `RetryDirective` |
| 4 | Транспортный сбой → `raise DriverError`; ответ приложения (любой код) → `return DriverResponse` |
| 5 | `build_paged_request()` возвращает новый `HttpRequest` — не мутирует `base_req` |
| 6 | `extract_items()` поднимает `ValueError` при непонятном формате, но не при пустом списке |
| 7 | `close()` должен быть idempotent (безопасно вызвать дважды) |
| 8 | Компилятор валидирует `OperationSpec` при старте; ошибки конфигурации обнаруживаются сразу |

### ⏱️ Performance заметки

- **Connection pool** — `max_connections=100`, `max_keepalive_connections=20` по умолчанию
- **Keepalive expiry** — 5.0 сек; настраивается через `HttpClientSettings.keepalive_expiry_seconds`
- **body_snippet** — всегда первые 200 символов строки, независимо от успешного JSON-парсинга
- **Compilation** — `CompiledHttpOperation` создаётся один раз при инициализации `TargetKernel`
- **`dataclasses.replace()`** в `build_paged_request` — lightweight copy без полного клонирования

---

## 🧪 Тестовое покрытие

### test_http_transport_request_once.py

**Файл**: `tests/unit/infrastructure/test_http_transport_request_once.py`

Покрывает атомарную функцию `request_once()` и нормализатор:

| Тест | Что проверяется |
|---|---|
| `test_request_once_sends_json_payload` | JSON payload корректно сериализуется; метод POST, путь и тело совпадают с HttpRequest |
| `test_request_once_returns_text_when_invalid_json` | Не-JSON тело → `body="not-json"`, `body_snippet="not-json"`, `error_code=None` |
| `test_request_once_maps_network_error_to_transport_error` | `httpx.TransportError` → `HttpErrorPayload(code="NETWORK_ERROR")`; `status_code=None` после нормализации |

Паттерн тестирования: `httpx.MockTransport(responder)` + `build_http_client()`. Тестирует
весь стек без реального сервера. Этот helper следует копировать в тестах новых транспортов:

```python
def _make_client(transport: httpx.BaseTransport) -> httpx.Client:
    return build_http_client(HttpClientSettings(
        base_url="https://ankey.local", transport=transport,
    ))
```

### test_target_ankey_driver.py

**Файл**: `tests/unit/infrastructure/test_target_ankey_driver.py`

Покрывает `AnkeyHttpDriver` (BaseHttpDriver + AnkeyPagingStrategy + `_detect_ankey_error_reason`):

| Тест | Что проверяется |
|---|---|
| `test_execute_non_ok_extracts_provider_reason_and_retry_after` | HTTP 409 + `{"message": "Resource exists"}` + `Retry-After: 2` → `ok=False`, `error_reason="resourceexists"`, `retry_after_s=2.0` |
| `test_iter_batches_stops_when_max_batches_reached` | `max_batches=1` → ровно один HTTP-запрос |
| `test_iter_batches_error_keeps_provider_reason` | HTTP 409 в iter_batches → `DriverError` с `error_reason="resourceexists"` |

Эти тесты демонстрируют два ключевых поведения:
1. **error_reason propagation** — `_detect_ankey_error_reason()` детектит `"resourceexists"` для `match_reason` в `RetryRule`
2. **iter_batches как DriverError** — в отличие от execute(), неожиданный статус в iter_batches → `DriverError`

### Смежные тесты

| Модуль | Вид тестирования |
|---|---|
| `normalizer.py` | Через `test_request_once_*` (интеграционно); отдельные unit для `_parse_retry_after` |
| `request_builder.py` | Unit-тесты path template rendering, merge query/headers |
| `compiler.py` | Unit-тесты compile с валидными и невалидными `OperationSpec` |
| `paging.py` | Unit-тесты `AnkeyPagingStrategy.extract_items()` с разными форматами |
| `client_factory.py` | Через `test_request_once_*` (инжекция transport) |

Принцип тестирования «снизу вверх»: сначала атомарные функции (`request_once`, `build_http_request`),
затем driver (`BaseHttpDriver`, `AnkeyHttpDriver`), наконец сквозные тесты через `TargetGateway`.

---

## ❓ FAQ

**Q: Почему Driver не должен ретраить?**

Потому что retry — это политика, а не механизм. Retry зависит от `FaultKind`, `RetryRule`,
количества попыток, задержки `Retry-After` и мутаций payload — всё это знает `TargetGateway`.
Если Driver ретраит сам, Gateway не сможет применить правильную политику, отобразить
корректную статистику или вернуть `retry_after_s` наверх.

**Q: Как добавить кастомную аутентификацию?**

Создайте класс, реализующий `httpx.Auth`, и передайте в `HttpClientSettings.auth`:

```python
class BearerTokenAuth(httpx.Auth):
    def __init__(self, token: str) -> None:
        self._token = token
    def auth_flow(self, request: httpx.Request):
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request

settings = HttpClientSettings(base_url="...", auth=BearerTokenAuth("my-token"))
```

Для OAuth2 с автообновлением — `auth_flow` делает дополнительный запрос на `/token`.

**Q: Можно ли одному провайдеру использовать несколько транспортов?**

Да. `TransportCompilerRegistry` поддерживает любое количество `kind`:

```python
registry.register("http", compile_http_operation)
registry.register("grpc", compile_grpc_operation)
```

Driver в этом случае проверяет тип `compiled_request`:

```python
def execute(self, compiled_request, payload=None):
    if isinstance(compiled_request, HttpRequest):
        return self._execute_http(compiled_request, payload)
    elif isinstance(compiled_request, GrpcCompiledRequest):
        return self._execute_grpc(compiled_request, payload)
    raise DriverError("unknown request type", code="CONFIG_ERROR")
```

**Q: Что произойдёт если `extract_items()` вернёт пустой список?**

`BaseHttpDriver.iter_batches()` увидит `not items == True` и выполнит `break`. Итерация
завершится нормально — это стандартный способ для сервера сообщить «всё выдано».
`ValueError` поднимается только если _формат_ ответа не распознан.

**Q: Как добавить request interceptor для трейсинга?**

Используйте `HttpClientSettings.event_hooks`:

```python
settings = HttpClientSettings(
    base_url="https://ankey.local",
    event_hooks={
        "request": [lambda req: logger.debug("-> %s %s", req.method, req.url)],
        "response": [lambda resp: logger.debug("<- %s", resp.status_code)],
    },
)
```

Для OpenTelemetry — `opentelemetry-instrumentation-httpx` добавляет хуки автоматически.

---

## 🔗 Связанные документы

| Файл / ресурс | Описание |
|---|---|
| [target-dsl.md](target-dsl.md) | DSL-спецификация TargetSpec, OperationSpec, kind |
| [target-core.md](target-core.md) | TargetKernel, TargetGateway, retry loop, redaction |
| [target-provider.md](target-provider.md) | AnkeyTargetProvider, AnkeyPagingStrategy, HOW-TO новый провайдер |

**Исходные файлы**:

| Файл | Роль |
|---|---|
| `connector/infra/target/driver.py` | TargetDriver Protocol, DriverResponse, DriverError |
| `connector/infra/target/transports/http/driver_base.py` | BaseHttpDriver |
| `connector/infra/target/transports/http/request_once.py` | Атомарная HTTP-попытка |
| `connector/infra/target/transports/http/request_builder.py` | HttpRequest, path template rendering |
| `connector/infra/target/transports/http/compiler.py` | CompiledHttpOperation, compile_http_operation |
| `connector/infra/target/transports/http/normalizer.py` | normalize_http_outcome, Retry-After parsing |
| `connector/infra/target/transports/http/paging.py` | HttpPagingStrategy Protocol |
| `connector/infra/target/transports/http/client_factory.py` | HttpClientSettings, build_http_client |
| `connector/infra/target/transports/http/op_models.py` | HttpOperationDataModel |
| `connector/infra/target/core/transport_compiler.py` | TransportCompilerRegistry, CompiledOperation |
| `connector/infra/target/providers/ankey_rest/driver.py` | AnkeyHttpDriver, AnkeyPagingStrategy |
| `tests/unit/infrastructure/test_http_transport_request_once.py` | Unit-тесты request_once |
| `tests/unit/infrastructure/test_target_ankey_driver.py` | Unit-тесты AnkeyHttpDriver |

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-28 | Первоначальное создание документа | xORex-LC |
