# Target Transport — протокол транспортного слоя и HTTP-реализация

## Содержание

1. [Роль транспортного слоя](#1-роль-транспортного-слоя)
2. [Transport Contract — TargetDriver Protocol](#2-transport-contract--targetdriver-protocol)
   - 2.1 [TargetDriver Protocol](#21-targetdriver-protocol)
   - 2.2 [Возвращаемые типы](#22-возвращаемые-типы)
   - 2.3 [CompiledOperation Protocol](#23-compiledoperation-protocol)
3. [TransportCompilerRegistry](#3-transportcompilerregistry)
   - 3.1 [Регистрация компиляторов](#31-регистрация-компиляторов)
   - 3.2 [Диспетчеризация](#32-диспетчеризация)
4. [HTTP Transport — полная реализация](#4-http-transport--полная-реализация)
   - 4.1 [Архитектура HTTP transport](#41-архитектура-http-transport)
   - 4.2 [HttpOperationDataModel](#42-httpoperationdatamodel)
   - 4.3 [CompiledHttpOperation](#43-compiledHttpoperation)
   - 4.4 [HttpRequest и build_http_request()](#44-httprequest-и-build_http_request)
   - 4.5 [request_once()](#45-request_once--атомарная-функция)
   - 4.6 [normalize_http_outcome()](#46-normalize_http_outcome)
   - 4.7 [BaseHttpDriver](#47-basehttpdriver)
   - 4.8 [HttpPagingStrategy Protocol](#48-httppagingstrategy-protocol)
   - 4.9 [HttpClientSettings и build_http_client()](#49-httpclientsettings-и-build_http_client)
   - 4.10 [Публичные экспорты](#410-публичные-экспорты)
5. [HOW-TO: Создание нового транспорта](#5-how-to-создание-нового-транспорта)
   - Шаг 1: [Определить CompiledMyOperation](#шаг-1-определить-compiledmyoperation)
   - Шаг 2: [Создать MyOperationDataModel](#шаг-2-создать-myoperationdatamodel)
   - Шаг 3: [Создать компилятор](#шаг-3-создать-компилятор)
   - Шаг 4: [Реализовать MyDriver](#шаг-4-реализовать-mydriver)
   - Шаг 5: [Зарегистрировать в TransportCompilerRegistry](#шаг-5-зарегистрировать-в-transportcompilerregistry)
   - Шаг 6: [Добавить kind в YAML-операциях](#шаг-6-добавить-kind-в-yaml-операциях)
   - Шаг 7: [Тестирование](#шаг-7-тестирование)
6. [Чеклист для нового транспорта](#6-чеклист-для-нового-транспорта)
7. [Взаимосвязь транспорта и провайдера](#7-взаимосвязь-транспорта-и-провайдера)
8. [FAQ](#8-faq)
9. [Тестовое покрытие HTTP transport](#9-тестовое-покрытие-http-transport)

---

## 1. Роль транспортного слоя

### Место в архитектуре

Target-слой состоит из нескольких уровней ответственности. Транспорт — самый нижний из них: он знает только о I/O-протоколе и ни о чём более.

```
┌─────────────────────────────────────────────────────────────┐
│                    Application / Use Cases                   │
└───────────────────────────┬─────────────────────────────────┘
                            │ RequestSpec
┌───────────────────────────▼─────────────────────────────────┐
│                      TargetGateway                           │
│  (retry-политика, классификация ошибок, redaction)           │
│  Единственный владелец логики повторных попыток              │
└───────────────────────────┬─────────────────────────────────┘
                            │ compiled_request + payload
┌───────────────────────────▼─────────────────────────────────┐
│                      TargetDriver                            │
│  ТРАНСПОРТНЫЙ СЛОЙ                                           │
│  (одна I/O-попытка, никакого retry)                          │
│  HTTP / gRPC / SFTP / ...                                    │
└───────────────────────────┬─────────────────────────────────┘
                            │ httpx.Client / grpc.Channel / ...
┌───────────────────────────▼─────────────────────────────────┐
│                   Сетевой стек ОС                            │
└─────────────────────────────────────────────────────────────┘
```

### Принцип изоляции

Транспортный слой полностью изолирует I/O-протокол от ядра. TargetGateway говорит: "выполни операцию X с payload Y". Транспорт знает: "как именно" — PUT на `/ankey/managed/user/{id}`, gRPC-вызов `UserService.UpsertUser`, запись файла по SFTP и т.д.

**Граница ответственности:**

| Уровень | Ответственность |
|---------|----------------|
| TargetGateway | retry-политика, классификация fault-kind, redaction payload |
| TargetKernel | компиляция операций, lookup-таблицы fault/retry |
| TargetDriver (транспорт) | одна I/O-попытка, маппинг сетевых ошибок в DriverError |
| httpx.Client | управление TCP-соединениями, TLS, connection pool |

### Ключевые инварианты транспорта

1. **Транспорт НИКОГДА не ретраит.** Ни одного `for attempt in range(n)`, ни `tenacity`, ни рекурсивных вызовов. Одна попытка — один вызов `execute()` или один шаг `iter_batches()`.

2. **Транспорт НИКОГДА не нормализует ошибки в domain-типы.** Результат — `DriverResponse` или исключение `DriverError`. Перевод в `ExecutionResult`, `SystemErrorCode`, `TargetFaultKind` — задача ядра.

3. **Транспорт НИКОГДА не читает конфигурацию retry.** Он не знает о `RetryConfig`, `RetryRule`, `RetryDirective`. Это opaque для него.

4. **Транспорт может поднять `DriverError` для транспортных сбоев** (таймаут, разрыв соединения, ошибка протокола). HTTP-ответ с кодом 409 — это _не_ сетевой сбой: транспорт вернёт `DriverResponse(ok=False)`.

---

## 2. Transport Contract — TargetDriver Protocol

### 2.1 TargetDriver Protocol

Протокол определён в `connector/infra/target/driver.py`. Это структурный Protocol в стиле duck typing — ни одна реализация не обязана наследоваться от `TargetDriver` явно.

```python
# connector/infra/target/driver.py

TCompiledRequest = TypeVar("TCompiledRequest")

class TargetDriver(Protocol[TCompiledRequest]):
    """Транспорт-агностичный протокол с одной попыткой I/O."""

    def execute(
        self,
        compiled_request: TCompiledRequest,
        payload: Any | None = None,
    ) -> DriverResponse: ...

    def iter_batches(
        self,
        compiled_request: TCompiledRequest,
        batch_size: int,
        max_batches: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterator[tuple[int, list[Any]]]: ...

    def close(self) -> None: ...
```

Разберём каждый метод.

**`execute(compiled_request, payload)`**

Выполняет ровно одну I/O-попытку. `compiled_request` — opaque объект: TargetGateway не знает его внутреннего устройства, он лишь передаёт его из `CompiledOperation.build()` напрямую в `driver.execute()`. `payload` — тело запроса (dict, list, None).

Метод либо возвращает `DriverResponse`, либо поднимает `DriverError`. Исключений других типов быть не должно — они будут пойманы в Gateway как неожиданные сбои.

**`iter_batches(compiled_request, batch_size, max_batches, params)`**

Постраничный итератор для операций чтения (`read_paged` capability). Каждая итерация соответствует одному HTTP-запросу (одной странице). Возвращает `tuple[int, list[Any]]` — номер страницы и список элементов. При ошибке любой страницы поднимает `DriverError` (Gateway обработает).

`max_batches=None` означает "читать до конца". `params` — дополнительные query-параметры для фильтрации (например, `{"_queryFilter": "active eq true"}`).

**`close()`**

Освобождает ресурсы транспортного клиента (TCP connection pool, файловые дескрипторы и т.д.). Вызывается Gateway при завершении работы.

### 2.2 Возвращаемые типы

#### DriverResponse

```python
@dataclass(frozen=True, slots=True)
class DriverResponse:
    """Результат одной I/O попытки."""

    ok: bool                               # Драйвер определяет успех
    answer_code: int | str | None = None   # Код ответа (HTTP status, gRPC status)
    payload: Any = None                    # Тело ответа
    content_preview: str | None = None    # Первые N символов для логирования
    payload_format: ResponsePayloadFormat = "none"  # "json" | "text" | "bytes" | "object" | "none"
    error_reason: str | None = None        # Provider-specific причина ошибки
    retry_after_s: float | None = None    # Подсказка к задержке retry
```

Поле `ok` — ключевое: для HTTP это означает, что `status_code` входит в `expected_statuses` данной операции. Ответ 409 при `expected_statuses=(200, 201)` даст `ok=False`, но это не `DriverError` — соединение состоялось, сервер ответил.

`error_reason` — provider-specific строка (например, `"resourceexists"`), извлечённая из тела ответа функцией `error_reason_fn`. Используется ядром для тонкой настройки retry-правил через `match_reason` в `RetryRule`.

`payload_format` автоматически выводится из типа `payload` через функцию `infer_response_payload_format()`:

```python
def infer_response_payload_format(payload: Any) -> ResponsePayloadFormat:
    if payload is None:         return "none"
    if isinstance(payload, (dict, list)): return "json"
    if isinstance(payload, str):          return "text"
    if isinstance(payload, (bytes, bytearray, memoryview)): return "bytes"
    return "object"
```

#### DriverError

```python
class DriverError(Exception):
    """Транспортная/протокольная ошибка одной попытки I/O."""

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

`DriverError` — это исключение для **транспортных сбоев**: таймаут TCP, разрыв соединения, невалидный HTTP-ответ, пустой outcome. Это не доменное исключение — его поднимает транспорт, ловит Gateway.

Стандартные значения `code`:

| code | Когда |
|------|-------|
| `NETWORK_ERROR` | `httpx.TimeoutException`, `httpx.TransportError` |
| `HTTP_OUTCOME_EMPTY` | Нет ни response, ни error в HttpOutcome |
| `HTTP_{status}` | Неожиданный HTTP-статус при iter_batches (например `HTTP_409`) |
| `INVALID_ITEMS_FORMAT` | `extract_items()` подняло `ValueError` |

**Ключевой инвариант:** `DriverError` — сетевой/протокольный сбой. `DriverResponse(ok=False)` — приложение ответило, но не так как ожидалось. Gateway обрабатывает оба случая, но через разные ветки логики.

#### iter_batches return type

`iter_batches` — это `Iterator[tuple[int, list[Any]]]`. Каждый yield — `(page_number, items)`:

- `page_number`: 1-based номер страницы
- `items`: список элементов данной страницы (непустой — иначе итератор завершается)

При ошибке поднимается `DriverError` — не yield с ошибкой.

### 2.3 CompiledOperation Protocol

`CompiledOperation` определён в `connector/infra/target/core/transport_compiler.py`:

```python
class CompiledOperation(Protocol[TCompiledRequest]):
    """Скомпилированная операция конкретного транспорта."""

    def build(
        self,
        *,
        alias: str,
        operation_params: dict[str, Any] | None = None,
        query_overrides: dict[str, Any] | None = None,
        header_overrides: dict[str, str] | None = None,
    ) -> TCompiledRequest: ...
```

`CompiledOperation` — это фабрика transport-specific запросов. Она создаётся один раз при инициализации ядра (`TargetKernel.__init__`) и переиспользуется для каждого вызова.

Метод `build()` принимает runtime-параметры и возвращает `TCompiledRequest` — opaque объект для ядра. Для HTTP-транспорта это `HttpRequest` dataclass. TargetGateway не знает и не должен знать о внутренностях объекта, возвращаемого `build()`.

**Lifecycle объекта:**

```
Startup (один раз):
  OperationSpec ──► compile_http_operation() ──► CompiledHttpOperation
                                                  (хранится в TargetKernel)

Per-request (каждый вызов execute/iter_pages):
  CompiledHttpOperation.build(alias, operation_params, ...) ──► HttpRequest
  driver.execute(HttpRequest, payload) ──► DriverResponse
```

Разделение compilation (статическая валидация) и build (runtime-параметры) позволяет обнаруживать ошибки конфигурации при старте, а не при первом запросе.

---

## 3. TransportCompilerRegistry

### 3.1 Регистрация компиляторов

`TransportCompilerRegistry` — это простой dict-реестр, развязывающий `TargetKernel` от конкретных транспортных реализаций.

```python
class TransportCompilerRegistry:
    """Реестр компиляторов по operation.kind."""

    def __init__(self) -> None:
        self._compilers: dict[str, OperationCompiler] = {}

    def register(self, kind: str, compiler: OperationCompiler) -> None:
        """Зарегистрировать compiler для transport kind."""
        normalized = kind.strip().lower()
        if normalized == "":
            raise ValueError("kind транспорта не должен быть пустым")
        self._compilers[normalized] = compiler
```

`OperationCompiler` — это тип `Callable[[OperationSpec], CompiledOperation[Any]]`. Регистрируется провайдером при сборке runtime. Ключ — значение `kind` из YAML-декларации операции, нормализованное в lowercase.

Пример регистрации (из `AnkeyTargetProvider`):

```python
def build_transport_compiler_registry() -> TransportCompilerRegistry:
    registry = TransportCompilerRegistry()
    registry.register("http", compile_http_operation)
    return registry
```

### 3.2 Диспетчеризация

```python
def compile(self, operation: OperationSpec) -> CompiledOperation[Any]:
    """Скомпилировать operation в transport-specific объект."""
    compiler = self._compilers.get(operation.kind)
    if compiler is None:
        raise ValueError(
            f"для operation.kind={operation.kind!r} не зарегистрирован компилятор",
        )
    return compiler(operation)
```

`TargetKernel.__init__` вызывает `registry.compile(operation)` для каждой операции из `TargetSpec.operations` — это происходит при старте приложения. Если хоть одна операция имеет незарегистрированный `kind`, ядро не запустится.

**Поток от YAML до I/O:**

```
datasets/targets/ankey.yaml
    operations:
      users.upsert:
        kind: http          ◄── ключ реестра
        expected_statuses: [200, 201]
        data:
          method: PUT
          path_template: /ankey/managed/user/{target_id}
          ...
          │
          ▼
    OperationSpec(
        alias="users.upsert",
        kind="http",
        expected_statuses=(200, 201),
        data={method: PUT, path_template: ...}
    )
          │
          ▼ registry.compile(op_spec)
          │ (поиск по kind="http" → compile_http_operation)
          ▼
    CompiledHttpOperation(
        op_data=HttpOperationDataModel(...),
        expected_statuses=(200, 201)
    )
          │
          ▼ .build(alias="users.upsert", operation_params={"target_id": "u-1"})
          ▼
    HttpRequest(
        method="PUT",
        path="/ankey/managed/user/u-1",
        query={},
        headers={},
        expected_statuses=(200, 201)
    )
          │
          ▼ driver.execute(HttpRequest, payload)
          ▼
    HTTP PUT https://ankey.local/ankey/managed/user/u-1
```

---

## 4. HTTP Transport — полная реализация

### 4.1 Архитектура HTTP transport

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

**Диаграмма потока данных внутри HTTP transport:**

```
                    ┌─────────────────────────────────────────────┐
                    │              BaseHttpDriver                  │
                    │                                             │
  execute()         │  1. compiled_request (HttpRequest)          │
  ─────────────►    │  2. replace(req, json=payload)              │
                    │  3. request_fn(client, req) ──► HttpOutcome │
                    │  4. normalize_http_outcome()                │
                    │  5. _resolve_error_reason()                 │
                    │  6. DriverError (если error_code)           │
                    │     или DriverResponse(ok=...)              │
                    └─────────────────────────────────────────────┘

  iter_batches()    ┌─────────────────────────────────────────────┐
  ─────────────►    │  1. base_req = replace(req, query=+params)  │
                    │  LOOP (page=1, 2, ...):                     │
                    │    2. paging.build_paged_request(req, page) │
                    │    3. request_fn(client, page_req)          │
                    │    4. normalize_http_outcome()              │
                    │    5. paging.extract_items(body)            │
                    │    6. yield (page, items)                   │
                    │    STOP: items пустой / len<batch_size /    │
                    │          page > max_batches                 │
                    └─────────────────────────────────────────────┘

Compilation (один раз при старте):
OperationSpec ──► compile_http_operation() ──► CompiledHttpOperation
                                              .build() ──► HttpRequest
```

**Зависимости между модулями:**

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

### 4.2 HttpOperationDataModel

Pydantic-модель, описывающая HTTP-специфику одной операции. Живёт в `OperationSpec.data` как opaque dict — ядро не интерпретирует его содержимое.

```python
# connector/infra/target/transports/http/op_models.py

class HttpOperationDataModel(BaseModel):
    """Транспортное описание HTTP-операции."""

    model_config = ConfigDict(
        extra="forbid",   # Неизвестные ключи — ошибка валидации
        frozen=True,      # Неизменяема после создания
    )

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path_template: str           # Должен начинаться с '/'
    query_defaults: dict[str, Any] = Field(default_factory=dict)
    header_defaults: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_path_template(self) -> "HttpOperationDataModel":
        if not self.path_template.startswith("/"):
            raise ValueError("path_template must start with '/'")
        return self
```

**Поля:**

| Поле | Тип | Описание |
|------|-----|----------|
| `method` | Literal | HTTP-метод. Только верхний регистр |
| `path_template` | str | Путь с `{param}` плейсхолдерами. Обязательно начинается с `/` |
| `query_defaults` | dict | Query-параметры по умолчанию. Перекрываются через `query_overrides` |
| `header_defaults` | dict | HTTP-заголовки по умолчанию. Перекрываются через `header_overrides` |

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

### 4.3 CompiledHttpOperation

```python
# connector/infra/target/transports/http/compiler.py

@dataclass(frozen=True, slots=True)
class CompiledHttpOperation:
    """Скомпилированная HTTP-операция с валидированными transport-данными."""

    op_data: HttpOperationDataModel
    expected_statuses: tuple[int, ...]   # из OperationSpec.expected_statuses

    def build(
        self,
        *,
        alias: str,
        operation_params: dict[str, Any] | None = None,
        query_overrides: dict[str, Any] | None = None,
        header_overrides: dict[str, str] | None = None,
    ) -> HttpRequest:
        """Собрать готовый HttpRequest с merged runtime-overrides."""
        req = build_http_request(
            alias=alias,
            op_data=self.op_data,
            operation_params=operation_params,
            query_overrides=query_overrides,
            header_overrides=header_overrides,
        )
        return HttpRequest(
            method=req.method,
            path=req.path,
            query=req.query,
            headers=req.headers,
            json=req.json,
            timeout_s=req.timeout_s,
            expected_statuses=self.expected_statuses,  # ← берётся из spec, не из op_data
        )
```

Функция компиляции:

```python
def compile_http_operation(operation: OperationSpec) -> CompiledHttpOperation:
    if operation.kind != "http":
        raise ValueError(f"operation {operation.alias!r} is not http")
    if not operation.data:
        raise ValueError(f"operation {operation.alias!r} requires transport payload")
    return CompiledHttpOperation(
        op_data=compile_http_operation_data(operation.data),
        expected_statuses=operation.expected_statuses,
    )

def compile_http_operation_data(raw_data: dict[str, Any]) -> HttpOperationDataModel:
    return HttpOperationDataModel.model_validate(raw_data)
```

Обе функции публично доступны через `from connector.infra.target.transports.http import compile_http_operation, compile_http_operation_data`.

**Что происходит при компиляции:**

1. Проверяется `operation.kind == "http"` — если нет, `ValueError` немедленно.
2. Проверяется наличие `operation.data` — без него HTTP-операция бессмысленна.
3. `HttpOperationDataModel.model_validate(operation.data)` — Pydantic валидирует структуру.
4. `@model_validator` проверяет `path_template.startswith("/")`.
5. Результат — frozen dataclass, готовый к многократному `build()`.

### 4.4 HttpRequest и build_http_request()

`HttpRequest` — финальный transport-DTO перед отправкой:

```python
# connector/infra/target/transports/http/request_builder.py

@dataclass(frozen=True, slots=True)
class HttpRequest:
    """Транспортный DTO HTTP-запроса для однократного исполнения."""

    method: str
    path: str                           # Resolved path (без плейсхолдеров)
    query: dict[str, Any]               # Смёрженные query-параметры
    headers: dict[str, str]             # Смёрженные заголовки
    json: Any | None = None             # Тело запроса (передаётся как JSON)
    timeout_s: float | None = None      # None → httpx.USE_CLIENT_DEFAULT
    expected_statuses: tuple[int, ...] = (200,)  # Статусы, считающиеся успехом
```

`json=None` при `execute()` — тело не отправляется. Поле `json` устанавливается в `BaseHttpDriver.execute()` через `replace(req, json=payload)`.

**Функция `build_http_request()`:**

```python
def build_http_request(
    *,
    alias: str,
    op_data: HttpOperationDataModel,
    operation_params: dict[str, Any] | None = None,
    query_overrides: dict[str, Any] | None = None,
    header_overrides: dict[str, str] | None = None,
) -> HttpRequest:
    path = _render_path_template(
        alias=alias,
        path_template=op_data.path_template,
        params=operation_params,
    )
    query = dict(op_data.query_defaults)
    if query_overrides:
        query.update(query_overrides)       # override имеет приоритет
    headers = dict(op_data.header_defaults)
    if header_overrides:
        headers.update(header_overrides)    # override имеет приоритет
    return HttpRequest(
        method=op_data.method,
        path=path,
        query=query,
        headers=headers,
        # json, timeout_s, expected_statuses — устанавливаются позже
    )
```

**Алгоритм подстановки path:**

```python
_PATH_TEMPLATE_PARAM_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

def _render_path_template(*, alias, path_template, params) -> str:
    params = params or {}
    required = _PATH_TEMPLATE_PARAM_RE.findall(path_template)
    missing = [name for name in required if name not in params]
    if missing:
        joined = ", ".join(sorted(missing))
        raise ValueError(f"operation {alias!r} missing path params: {joined}")
    try:
        return path_template.format(**params)
    except KeyError as exc:
        raise ValueError(f"operation {alias!r} missing path param: {exc}") from exc
```

Примеры подстановки:

| path_template | operation_params | Результат |
|---------------|-----------------|-----------|
| `/ankey/managed/user/{target_id}` | `{"target_id": "u-42"}` | `/ankey/managed/user/u-42` |
| `/ankey/managed/user/{target_id}` | `{}` | `ValueError: missing path params: target_id` |
| `/ankey/managed/user` | `{"target_id": "u-42"}` | `/ankey/managed/user` (лишние params игнорируются) |
| `/org/{org_id}/user/{user_id}` | `{"org_id": "o-1"}` | `ValueError: missing path params: user_id` |

Важно: регулярное выражение `{([a-zA-Z_][a-zA-Z0-9_]*)}` — стандартный Python `.format()` синтаксис. Только буквы, цифры, подчёркивание, первый символ — не цифра.

**Порядок merge для query и headers:**

```
query_defaults (из op_data)
    +
query_overrides (runtime, например page params от Gateway)
    ↓
итоговый query  ← override перекрывает defaults
```

Это позволяет провайдеру задать `_queryFilter=true` в `query_defaults`, а `iter_pages()` добавить `page=2&rows=100` через `query_overrides`.

### 4.5 request_once() — атомарная функция

`request_once` — это сердце транспортного слоя. Одна функция, одна попытка, никакого retry.

```python
# connector/infra/target/transports/http/request_once.py

_BODY_SNIPPET_LIMIT = 200

def request_once(client: httpx.Client, req: HttpRequest) -> HttpOutcome:
    """Выполнить одну HTTP-попытку без retry/backoff."""
    try:
        response = client.request(
            req.method,
            req.path,
            params=req.query or None,
            headers=req.headers or None,
            json=req.json,
            timeout=req.timeout_s if req.timeout_s is not None else httpx.USE_CLIENT_DEFAULT,
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        return HttpOutcome(
            error=HttpErrorPayload(
                code="NETWORK_ERROR",
                message=str(exc),
            ),
        )

    body, body_snippet = _parse_body(response)
    return HttpOutcome(
        response=HttpResponsePayload(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=body,
            body_snippet=body_snippet,
        ),
    )
```

**Возвращаемые типы:**

```python
@dataclass(frozen=True, slots=True)
class HttpResponsePayload:
    status_code: int
    headers: dict[str, str]      # Все HTTP-заголовки ответа (для Retry-After и т.д.)
    body: Any | None             # JSON-объект или str
    body_snippet: str | None     # Первые 200 символов строкового тела

@dataclass(frozen=True, slots=True)
class HttpErrorPayload:
    code: str                    # Категория: "NETWORK_ERROR"
    message: str                 # Строка исключения для диагностики
    details: dict[str, Any] | None = None

@dataclass(frozen=True, slots=True)
class HttpOutcome:
    response: HttpResponsePayload | None = None
    error: HttpErrorPayload | None = None
    # Инвариант: ровно одно из двух не-None
```

**Логика парсинга тела:**

```python
def _parse_body(response: httpx.Response) -> tuple[Any | None, str | None]:
    text = response.text if response.text else None
    body_snippet = text[:_BODY_SNIPPET_LIMIT] if text else None
    if not text:
        return None, body_snippet
    try:
        return response.json(), body_snippet  # Приоритет JSON
    except ValueError:
        return text, body_snippet              # Fallback: текст как есть
```

Snippet (`body_snippet`) — это всегда первые 200 символов _строкового_ тела, независимо от того, удалось распарсить JSON или нет. Используется для безопасного логирования (не надо сериализовывать весь body).

**Что перехватывается:**

| Исключение httpx | Результат |
|------------------|-----------|
| `httpx.TimeoutException` | `HttpErrorPayload(code="NETWORK_ERROR")` |
| `httpx.TransportError` | `HttpErrorPayload(code="NETWORK_ERROR")` |
| Любое другое исключение | НЕ перехватывается — всплывает наверх |

Намеренно не перехватываются другие исключения httpx (например `httpx.InvalidURL`), поскольку они сигнализируют о программной ошибке конфигурации, а не о сетевом сбое.

### 4.6 normalize_http_outcome()

`normalize_http_outcome` переводит низкоуровневый `HttpOutcome` в стабильный `HttpNormalizedOutcome`, который может обрабатывать `BaseHttpDriver`.

```python
# connector/infra/target/transports/http/normalizer.py

@dataclass(frozen=True, slots=True)
class HttpNormalizedOutcome:
    status_code: int | None      # None при сетевой ошибке
    body: Any | None
    body_snippet: str | None
    error_code: str | None       # None при успешном ответе
    error_message: str | None    # None при успешном ответе
    retry_after_s: float | None  # Из заголовка Retry-After

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
        # Защитная ветка: пустой outcome (не должен возникать в norm. условиях)
        return HttpNormalizedOutcome(
            status_code=None, body=None, body_snippet=None,
            error_code="HTTP_OUTCOME_EMPTY",
            error_message="empty http outcome",
            retry_after_s=None,
        )

    headers = outcome.response.headers
    retry_after_raw = _header_value_case_insensitive(headers, "Retry-After")
    retry_after_s = _parse_retry_after(retry_after_raw)
    return HttpNormalizedOutcome(
        status_code=outcome.response.status_code,
        body=outcome.response.body,
        body_snippet=outcome.response.body_snippet,
        error_code=None,       # Нормализатор не оценивает статус — это делает driver
        error_message=None,
        retry_after_s=retry_after_s,
    )
```

**Парсинг Retry-After:**

```python
def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    candidate = value.strip()
    # Вариант 1: число секунд
    try:
        seconds = float(candidate)
        return seconds if seconds >= 0 else None
    except ValueError:
        pass
    # Вариант 2: HTTP-date формат ("Wed, 01 Jan 2025 12:00:00 GMT")
    try:
        when = parsedate_to_datetime(candidate)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta = (when - datetime.now(timezone.utc)).total_seconds()
    return delta if delta > 0 else 0.0  # Уже прошедшая дата → 0.0, не None
```

Поиск заголовка `Retry-After` — case-insensitive: `"retry-after"`, `"Retry-After"`, `"RETRY-AFTER"` — всё обработается.

**Важно:** нормализатор не оценивает `status_code` (не решает, "ok" это или нет). Это задача `BaseHttpDriver`, который знает `expected_statuses` из `HttpRequest`.

### 4.7 BaseHttpDriver

`BaseHttpDriver` — конкретная реализация протокола `TargetDriver` для HTTP. Он параметрически настраивается через инжектирование зависимостей.

```python
# connector/infra/target/transports/http/driver_base.py

class BaseHttpDriver:
    def __init__(
        self,
        client: httpx.Client,
        paging: HttpPagingStrategy,
        *,
        error_reason_fn: Callable[[Any, str | None], str | None] | None = None,
        request_fn: HttpRequestOncePort = request_once,
    ) -> None:
        self._client = client
        self._paging = paging
        self._error_reason_fn = error_reason_fn
        self._request_fn = request_fn  # Инжектируется в тестах (mock)
```

`HttpRequestOncePort` — это Protocol для `request_fn`:

```python
class HttpRequestOncePort(Protocol):
    def __call__(self, client: httpx.Client, req: HttpRequest) -> HttpOutcome: ...
```

Инжекция `request_fn` позволяет тестировать `BaseHttpDriver` без реального HTTP, подставив любой callable с нужной сигнатурой.

**Метод `execute()`:**

```python
def execute(
    self,
    compiled_request: Any,
    payload: Any | None = None,
) -> DriverResponse:
    req: HttpRequest = compiled_request
    outcome = self._request_fn(self._client, replace(req, json=payload))
    normalized = normalize_http_outcome(outcome)
    error_reason = self._resolve_error_reason(normalized.body, normalized.body_snippet)

    if normalized.error_code is not None:
        # Сетевая ошибка → DriverError (исключение)
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

    # HTTP-ответ получен (даже если статус "неожиданный")
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

Разница между `DriverError` и `DriverResponse(ok=False)`:

```
Timeout / TCP reset → DriverError(code="NETWORK_ERROR")   [исключение]
HTTP 200 (ожидался) → DriverResponse(ok=True)              [возврат]
HTTP 409 (не ожидался) → DriverResponse(ok=False)          [возврат]
HTTP 500 (не ожидался) → DriverResponse(ok=False)          [возврат]
```

**Метод `iter_batches()`:**

```python
def iter_batches(
    self,
    compiled_request: Any,
    batch_size: int,
    max_batches: int | None,
    params: dict[str, Any] | None = None,
) -> Iterator[tuple[int, list[Any]]]:
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
            raise DriverError(
                normalized.error_message or normalized.error_code,
                code=normalized.error_code,
                ...
            )
        if normalized.status_code not in req.expected_statuses:
            raise DriverError(
                f"target answer {normalized.status_code}",
                code=f"HTTP_{normalized.status_code}",
                ...
            )

        try:
            items = self._paging.extract_items(normalized.body)
        except ValueError as exc:
            raise DriverError(str(exc), code="INVALID_ITEMS_FORMAT") from exc

        if not items:
            break                          # Пустая страница — конец данных
        yield page, items
        if len(items) < batch_size:
            break                          # Неполная страница — конец данных
        page += 1
```

Условия остановки итерации:

| Условие | Действие |
|---------|---------|
| `page > max_batches` | `break` (достигнут лимит) |
| `normalized.error_code is not None` | `raise DriverError` |
| `status_code not in expected_statuses` | `raise DriverError` |
| `extract_items()` подняло `ValueError` | `raise DriverError(code="INVALID_ITEMS_FORMAT")` |
| `len(items) == 0` | `break` (сервер вернул пустую страницу) |
| `len(items) < batch_size` | `break` (последняя неполная страница) |

Заметим: при `iter_batches` неожиданный статус — это `DriverError`, а не `DriverResponse(ok=False)`. Это принципиальное отличие от `execute()`: в режиме чтения нет смысла возвращать "неудачный ответ" — итерация не может продолжаться с частичными данными.

### 4.8 HttpPagingStrategy Protocol

```python
# connector/infra/target/transports/http/paging.py

class HttpPagingStrategy(Protocol):
    """Стратегия постраничного чтения для HTTP-транспорта."""

    def build_paged_request(
        self,
        base_req: HttpRequest,
        page: int,
        batch_size: int,
    ) -> HttpRequest:
        """Добавить page/size параметры. Не мутирует base_req."""
        ...

    def extract_items(self, body: Any) -> list[Any]:
        """Вернуть список элементов из body. Raises: ValueError."""
        ...
```

Пример реализации — `AnkeyPagingStrategy` из `connector/infra/target/providers/ankey_rest/driver.py`:

```python
class AnkeyPagingStrategy:
    """Стратегия пагинации для Ankey REST API (page/rows параметры)."""

    _ITEMS_KEYS: tuple[str, ...] = (
        "items", "data", "users", "organizations", "orgs", "result"
    )

    def build_paged_request(
        self,
        base_req: HttpRequest,
        page: int,
        batch_size: int,
    ) -> HttpRequest:
        query = {**base_req.query, "page": page, "rows": batch_size}
        query.setdefault("_queryFilter", "true")
        return replace(base_req, query=query)   # Не мутирует base_req

    def extract_items(self, body: Any) -> list[Any]:
        if isinstance(body, list):
            return body                          # Тело сразу список
        if isinstance(body, dict):
            for key in self._ITEMS_KEYS:
                if key in body and isinstance(body[key], list):
                    return body[key]             # Найден ключ items/data/users/...
        raise ValueError("Unexpected response format: no items array")
```

**Контракт `extract_items()`:**

- Возвращает `list[Any]` — всегда список, может быть пустым.
- Пустой список (`[]`) — корректный сигнал конца данных. `BaseHttpDriver` остановит итерацию.
- `ValueError` — формат ответа не распознан. `BaseHttpDriver` преобразует в `DriverError(code="INVALID_ITEMS_FORMAT")`.

**Важно:** `build_paged_request()` должен возвращать новый `HttpRequest`, не мутируя `base_req`. `HttpRequest` — frozen dataclass, поэтому используется `dataclasses.replace()`.

### 4.9 HttpClientSettings и build_http_client()

`HttpClientSettings` — полная конфигурация httpx-клиента для транспорта:

```python
# connector/infra/target/transports/http/client_factory.py

@dataclass(frozen=True, slots=True)
class HttpClientSettings:
    """Параметры сборки httpx.Client для target HTTP-транспорта."""

    base_url: str

    # Таймауты
    timeout_seconds: float = 20.0
    connect_timeout_seconds: float | None = None   # None → использует timeout_seconds
    read_timeout_seconds: float | None = None
    write_timeout_seconds: float | None = None
    pool_timeout_seconds: float | None = None

    # Connection pool
    max_connections: int = 100
    max_keepalive_connections: int = 20
    keepalive_expiry_seconds: float | None = 5.0

    # TLS
    tls_skip_verify: bool = False          # Пропустить верификацию сертификата
    ca_file: str | None = None             # Путь к CA bundle (PEM)

    # Переопределение transport (для тестов)
    transport: httpx.BaseTransport | None = None

    # Дополнительно
    default_headers: dict[str, str] = field(default_factory=dict)
    event_hooks: HttpEventHooks | None = None   # dict[str, list[Callable]]
    auth: httpx.Auth | None = None
    proxy: str | None = None
```

**Функция `build_http_client()`:**

```python
def build_http_client(settings: HttpClientSettings) -> httpx.Client:
    """Собрать настроенный httpx.Client для транспорта с одной попыткой I/O."""
    verify: bool | str = True
    if settings.tls_skip_verify:
        verify = False
    elif settings.ca_file:
        verify = settings.ca_file     # Путь к custom CA bundle

    default_timeout = settings.timeout_seconds
    timeout = httpx.Timeout(
        default_timeout,
        connect=settings.connect_timeout_seconds or default_timeout,
        read=settings.read_timeout_seconds or default_timeout,
        write=settings.write_timeout_seconds or default_timeout,
        pool=settings.pool_timeout_seconds or default_timeout,
    )
    limits = httpx.Limits(
        max_connections=settings.max_connections,
        max_keepalive_connections=settings.max_keepalive_connections,
        keepalive_expiry=settings.keepalive_expiry_seconds,
    )
    return httpx.Client(
        base_url=settings.base_url.rstrip("/"),   # Убирает trailing slash
        timeout=timeout,
        verify=verify,
        limits=limits,
        transport=settings.transport,
        headers=dict(settings.default_headers),
        event_hooks=settings.event_hooks,
        auth=settings.auth,
        proxy=settings.proxy,
    )
```

**Почему httpx.Client не содержит retry:**

httpx поддерживает `transport`-уровневые retry через `httpx_retrying` или кастомные transport-обёртки, но в этой архитектуре retry принципиально управляется на уровне `TargetGateway`. Если добавить retry в httpx, они будут невидимы для Gateway, что нарушит подсчёт попыток, задержки по `Retry-After` и мутации payload между retry.

`transport=settings.transport` используется для инжекции `httpx.MockTransport` в тестах — это позволяет тестировать весь стек без реального сервера.

### 4.10 Публичные экспорты

Всё публично полезное из HTTP transport доступно через единый пакет:

```python
# connector/infra/target/transports/http/__init__.py

from connector.infra.target.transports.http.client_factory import (
    HttpClientSettings,
    build_http_client,
)
from connector.infra.target.transports.http.compiler import (
    CompiledHttpOperation,
    compile_http_operation,
    compile_http_operation_data,
)
from connector.infra.target.transports.http.driver_base import (
    BaseHttpDriver,
    HttpRequestOncePort,
)
from connector.infra.target.transports.http.normalizer import (
    HttpNormalizedOutcome,
    normalize_http_outcome,
)
from connector.infra.target.transports.http.op_models import HttpOperationDataModel
from connector.infra.target.transports.http.paging import HttpPagingStrategy
from connector.infra.target.transports.http.request_builder import (
    HttpRequest,
    build_http_request,
)
from connector.infra.target.transports.http.request_once import (
    HttpErrorPayload,
    HttpOutcome,
    HttpResponsePayload,
    request_once,
)

__all__ = [
    "BaseHttpDriver",
    "HttpClientSettings",
    "HttpErrorPayload",
    "HttpNormalizedOutcome",
    "HttpOperationDataModel",
    "HttpOutcome",
    "HttpPagingStrategy",
    "HttpRequest",
    "HttpRequestOncePort",
    "HttpResponsePayload",
    "CompiledHttpOperation",
    "build_http_client",
    "build_http_request",
    "compile_http_operation",
    "compile_http_operation_data",
    "normalize_http_outcome",
    "request_once",
]
```

Итого 17 публичных имён. Провайдеры и тесты должны импортировать из этого пакета, а не из внутренних модулей напрямую.

---

## 5. HOW-TO: Создание нового транспорта

Это пошаговое руководство для разработчика, которому нужно добавить новый транспорт — например, gRPC. Все шаги независимы и выполняются последовательно.

### Шаг 1: Определить CompiledMyOperation

Создайте frozen dataclass для скомпилированной операции нового транспорта. Он должен реализовывать метод `build()` из `CompiledOperation` Protocol (duck typing — явного наследования не нужно):

```python
# connector/infra/target/transports/grpc/compiled.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class GrpcCompiledRequest:
    """Transport-специфичный запрос для одного gRPC вызова."""

    service: str
    method: str
    expected_statuses: tuple[int, ...]    # gRPC status codes (0 = OK)


@dataclass(frozen=True, slots=True)
class CompiledGrpcOperation:
    """Скомпилированная gRPC-операция. Реализует CompiledOperation Protocol."""

    service: str
    method: str
    expected_statuses: tuple[int, ...]

    def build(
        self,
        *,
        alias: str,
        operation_params: dict[str, Any] | None = None,
        query_overrides: dict[str, Any] | None = None,
        header_overrides: dict[str, str] | None = None,
    ) -> GrpcCompiledRequest:
        """Собрать transport-запрос из runtime-параметров."""
        # gRPC не использует query_overrides/header_overrides в том же смысле,
        # но сигнатура должна совпадать с Protocol.
        return GrpcCompiledRequest(
            service=self.service,
            method=self.method,
            expected_statuses=self.expected_statuses,
        )
```

Требования к `CompiledMyOperation`:

- `frozen=True` — объект создаётся один раз и переиспользуется.
- `build()` — принимает runtime-параметры, возвращает transport-specific request.
- Возвращаемый тип `build()` — opaque для ядра. Ядро передаёт его в `driver.execute()` без распаковки.

### Шаг 2: Создать MyOperationDataModel

Pydantic-модель, которая интерпретирует `OperationSpec.data` — opaque dict из YAML:

```python
# connector/infra/target/transports/grpc/op_models.py
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GrpcOperationDataModel(BaseModel):
    """Транспортное описание gRPC-операции."""

    model_config = ConfigDict(
        extra="forbid",    # Строго: неизвестные поля → ValidationError
        frozen=True,       # Неизменяема
    )

    service: str    # Полное имя gRPC-сервиса (например "UserService")
    method: str     # Имя метода (например "UpsertUser")
    # Добавьте другие поля по необходимости:
    # timeout_ms: int = 5000
    # metadata_keys: list[str] = Field(default_factory=list)
```

### Шаг 3: Создать компилятор

Функция компиляции — статическая валидация `OperationSpec` и создание `CompiledMyOperation`. Вызывается один раз при старте:

```python
# connector/infra/target/transports/grpc/compiler.py
from __future__ import annotations

from connector.infra.target.core.spec_models import OperationSpec
from connector.infra.target.transports.grpc.compiled import CompiledGrpcOperation
from connector.infra.target.transports.grpc.op_models import GrpcOperationDataModel


def compile_grpc_operation(operation: OperationSpec) -> CompiledGrpcOperation:
    """
    Скомпилировать и провалидировать gRPC-данные из OperationSpec.

    Raises:
        ValueError: если operation.kind != "grpc" или data невалидны.
    """
    if operation.kind != "grpc":
        raise ValueError(
            f"operation {operation.alias!r}: ожидался kind='grpc', получен {operation.kind!r}"
        )
    if not operation.data:
        raise ValueError(
            f"operation {operation.alias!r}: требуется поле data с gRPC-конфигурацией"
        )
    data = GrpcOperationDataModel.model_validate(operation.data)
    return CompiledGrpcOperation(
        service=data.service,
        method=data.method,
        expected_statuses=operation.expected_statuses,
    )
```

### Шаг 4: Реализовать MyDriver

Главный класс — реализация `TargetDriver` Protocol:

```python
# connector/infra/target/transports/grpc/driver.py
from __future__ import annotations

from typing import Any, Iterator

import grpc

from connector.infra.target.driver import DriverError, DriverResponse
from connector.infra.target.transports.grpc.compiled import GrpcCompiledRequest


class GrpcDriver:
    """
    gRPC-реализация TargetDriver Protocol.

    Контракт:
        - execute: ровно один gRPC-вызов, никогда не ретраит.
        - iter_batches: потоковое чтение через ServerStreaming (если поддерживается).
        - close: закрывает gRPC channel.
    """

    def __init__(self, channel: grpc.Channel) -> None:
        self._channel = channel
        # Инициализируйте stub здесь

    def execute(
        self,
        compiled_request: GrpcCompiledRequest,
        payload: Any | None = None,
    ) -> DriverResponse:
        """Выполнить ровно один gRPC-вызов. Никакого retry."""
        try:
            # Один вызов:
            stub = self._get_stub(compiled_request.service)
            method = getattr(stub, compiled_request.method)
            result = method(self._build_grpc_request(payload))

            # gRPC status code 0 = OK
            return DriverResponse(
                ok=grpc.StatusCode.OK.value[0] in compiled_request.expected_statuses,
                answer_code=grpc.StatusCode.OK.value[0],
                payload=self._parse_response(result),
            )
        except grpc.RpcError as exc:
            status_code = exc.code().value[0]
            if exc.code() in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                # Транспортный сбой → DriverError
                raise DriverError(
                    str(exc.details()),
                    code="GRPC_UNAVAILABLE",
                    answer_code=status_code,
                ) from exc
            # Приложение ответило с ошибкой → DriverResponse(ok=False)
            return DriverResponse(
                ok=False,
                answer_code=status_code,
                error_reason=exc.details(),
            )
        except Exception as exc:
            # Неожиданная ошибка → DriverError с общим кодом
            raise DriverError(str(exc), code="GRPC_ERROR") from exc

    def iter_batches(
        self,
        compiled_request: GrpcCompiledRequest,
        batch_size: int,
        max_batches: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterator[tuple[int, list[Any]]]:
        """Постраничное чтение. Реализуйте по аналогии с BaseHttpDriver."""
        # Пример с offset-based пагинацией:
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
        """Закрыть gRPC channel и освободить ресурсы."""
        self._channel.close()

    def _get_stub(self, service: str):
        # Вернуть stub для нужного сервиса
        raise NotImplementedError

    def _build_grpc_request(self, payload: Any):
        # Преобразовать dict payload в protobuf message
        raise NotImplementedError

    def _parse_response(self, result: Any) -> Any:
        # Преобразовать protobuf response в dict
        raise NotImplementedError

    def _fetch_page(
        self,
        req: GrpcCompiledRequest,
        page: int,
        batch_size: int,
        params: dict[str, Any] | None,
    ) -> list[Any]:
        raise NotImplementedError
```

**Инварианты, которые ОБЯЗАТЕЛЬНО соблюдать:**

- Ровно одна I/O-попытка в `execute()`. Не использовать `tenacity`, не делать `for attempt`.
- Не импортировать из `connector.domain.ports` — это нарушит boundary.
- Транспортный сбой → `raise DriverError(...)`.
- Приложение ответило (пусть с ошибкой) → `return DriverResponse(ok=False, ...)`.
- `close()` должен быть идемпотентным (безопасно вызывать дважды).

### Шаг 5: Зарегистрировать в TransportCompilerRegistry

Регистрация происходит в провайдере при сборке runtime. Создайте провайдер по аналогии с `AnkeyTargetProvider`:

```python
# connector/infra/target/providers/my_grpc/provider.py
from __future__ import annotations

import grpc

from connector.infra.target.core.gateway import TargetGateway
from connector.infra.target.core.kernel import TargetKernel
from connector.infra.target.core.runtime import DefaultTargetRuntime, TargetRuntime
from connector.infra.target.core.transport_compiler import TransportCompilerRegistry
from connector.infra.target.transports.grpc.compiler import compile_grpc_operation
from connector.infra.target.transports.grpc.driver import GrpcDriver


def build_grpc_compiler_registry() -> TransportCompilerRegistry:
    """Собрать реестр компиляторов для gRPC runtime."""
    registry = TransportCompilerRegistry()
    registry.register("grpc", compile_grpc_operation)
    # Можно зарегистрировать несколько transport kind в одном провайдере:
    # registry.register("grpc_streaming", compile_grpc_streaming_operation)
    return registry


class MyGrpcTargetProvider:
    target_type = "my_grpc"

    def __init__(self, grpc_address: str) -> None:
        self._address = grpc_address

    def build_core_runtime(self) -> TargetRuntime:
        from connector.domain.target_dsl import load_target_spec  # lazy: circular import

        spec = load_target_spec("my_grpc")
        channel = grpc.secure_channel(
            self._address,
            grpc.ssl_channel_credentials(),
        )
        driver = GrpcDriver(channel)
        kernel = TargetKernel(spec, compiler_registry=build_grpc_compiler_registry())
        gateway = TargetGateway(driver, kernel)
        # ... TargetConnectionConfig, DefaultTargetRuntime
        return DefaultTargetRuntime(gateway=gateway, ...)
```

### Шаг 6: Добавить kind в YAML-операциях

Создайте файл target-spec в `datasets/targets/my_grpc.yaml`:

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

  users.list:
    kind: grpc
    expected_statuses: [0]
    data:
      service: UserService
      method: ListUsers
```

Добавьте запись в `datasets/registry.yml` в секцию `targets:`:

```yaml
targets:
  ankey: datasets/targets/ankey.yaml
  my_grpc: datasets/targets/my_grpc.yaml  # ← новый провайдер
```

### Шаг 7: Тестирование

Тестирование нового транспорта строится по тем же паттернам, что и HTTP transport.

**Unit-тест компилятора:**

```python
# tests/unit/infrastructure/test_grpc_compiler.py
import pytest
from connector.infra.target.transports.grpc.compiler import compile_grpc_operation
from connector.domain.target_dsl.spec_models import OperationSpec


def _make_op(**kwargs) -> OperationSpec:
    defaults = {
        "alias": "users.upsert",
        "kind": "grpc",
        "expected_statuses": (0,),
        "data": {"service": "UserService", "method": "UpsertUser"},
    }
    defaults.update(kwargs)
    return OperationSpec(**defaults)


def test_compile_grpc_operation_valid():
    op = compile_grpc_operation(_make_op())
    assert op.service == "UserService"
    assert op.method == "UpsertUser"
    assert op.expected_statuses == (0,)


def test_compile_grpc_operation_wrong_kind():
    with pytest.raises(ValueError, match="ожидался kind='grpc'"):
        compile_grpc_operation(_make_op(kind="http"))


def test_compile_grpc_operation_missing_data():
    with pytest.raises(ValueError, match="требуется поле data"):
        compile_grpc_operation(_make_op(data={}))


def test_compile_grpc_operation_extra_field_forbidden():
    with pytest.raises(Exception):
        compile_grpc_operation(_make_op(data={
            "service": "UserService",
            "method": "UpsertUser",
            "unknown_field": "oops",   # extra="forbid"
        }))
```

**Unit-тест Driver с mock channel:**

```python
# tests/unit/infrastructure/test_grpc_driver.py
from unittest.mock import MagicMock, patch
import grpc
import pytest

from connector.infra.target.driver import DriverError
from connector.infra.target.transports.grpc.compiled import GrpcCompiledRequest
from connector.infra.target.transports.grpc.driver import GrpcDriver


def _make_compiled_request(**kwargs) -> GrpcCompiledRequest:
    defaults = {
        "service": "UserService",
        "method": "UpsertUser",
        "expected_statuses": (0,),
    }
    defaults.update(kwargs)
    return GrpcCompiledRequest(**defaults)


def test_execute_success():
    mock_channel = MagicMock(spec=grpc.Channel)
    driver = GrpcDriver(mock_channel)
    # Настройте mock stub и response...
    # response = driver.execute(_make_compiled_request(), payload={"name": "Alice"})
    # assert response.ok is True


def test_execute_unavailable_raises_driver_error():
    mock_channel = MagicMock(spec=grpc.Channel)
    driver = GrpcDriver(mock_channel)
    rpc_error = MagicMock(spec=grpc.RpcError)
    rpc_error.code.return_value = grpc.StatusCode.UNAVAILABLE
    rpc_error.details.return_value = "upstream unavailable"
    # Настройте stub чтобы поднял rpc_error...
    # with pytest.raises(DriverError) as exc_info:
    #     driver.execute(_make_compiled_request())
    # assert exc_info.value.code == "GRPC_UNAVAILABLE"
```

**Паттерн `httpx.MockTransport` для HTTP-транспорта** (для справки):

```python
def _make_client(transport: httpx.BaseTransport) -> httpx.Client:
    return build_http_client(
        HttpClientSettings(
            base_url="https://ankey.local",
            transport=transport,   # ← Инжекция mock
        )
    )

def test_example():
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = _make_client(httpx.MockTransport(responder))
    try:
        outcome = request_once(client, HttpRequest(...))
    finally:
        client.close()

    assert outcome.response.status_code == 200
```

**Интеграционный тест через TargetGateway** (сквозной тест без реального сервера):

```python
def test_gateway_with_mock_driver():
    mock_driver = MagicMock()
    mock_driver.execute.return_value = DriverResponse(ok=True, answer_code=0)
    # ... собрать TargetKernel с реальным spec, подставить mock_driver
    # gateway = TargetGateway(mock_driver, kernel)
    # result = gateway.execute(RequestSpec(...))
    # assert result.ok is True
```

---

## 6. Чеклист для нового транспорта

| Пункт | Обязательно | Файл |
|-------|:-----------:|------|
| `GrpcCompiledRequest` dataclass (transport-specific request) | ✓ | `transports/grpc/compiled.py` |
| `CompiledGrpcOperation` с методом `build()` | ✓ | `transports/grpc/compiled.py` |
| `GrpcOperationDataModel` (Pydantic, `extra="forbid"`, `frozen=True`) | ✓ | `transports/grpc/op_models.py` |
| `compile_grpc_operation(op_spec) -> CompiledGrpcOperation` | ✓ | `transports/grpc/compiler.py` |
| `GrpcDriver` класс, реализующий TargetDriver Protocol | ✓ | `transports/grpc/driver.py` |
| `execute()`: ровно одна попытка, никакого retry | ✓ | `transports/grpc/driver.py` |
| `execute()`: транспортный сбой → `raise DriverError` | ✓ | `transports/grpc/driver.py` |
| `execute()`: приложение ответило → `return DriverResponse` | ✓ | `transports/grpc/driver.py` |
| `iter_batches()` если capability `read_paged` | опционально | `transports/grpc/driver.py` |
| `close()` освобождает ресурсы (idempotent) | ✓ | `transports/grpc/driver.py` |
| Регистрация в `TransportCompilerRegistry` | ✓ | `providers/my_grpc/provider.py` |
| YAML target spec с `kind: grpc` в операциях | ✓ | `datasets/targets/my_grpc.yaml` |
| Запись в `datasets/registry.yml` | ✓ | `datasets/registry.yml` |
| Unit-тест компилятора (valid / wrong kind / missing data) | ✓ | `tests/unit/infrastructure/` |
| Unit-тест Driver.execute() с mock | ✓ | `tests/unit/infrastructure/` |
| NO import из `connector.domain.ports` в транспорте | ✓ | — |
| NO import `tenacity` в транспорте | ✓ | — |
| NO retry-логика в транспорте | ✓ | — |

---

## 7. Взаимосвязь транспорта и провайдера

Транспорт — это только I/O-механизм. Он не знает о конкретном сервисе, его аутентификации или бизнес-логике. Провайдер — это то, что собирает всё вместе.

**Разделение ответственности:**

```
Транспорт (HTTP, gRPC):
  - Знает: протокол, сериализацию, TCP-параметры
  - Не знает: бизнес-логику, retry-правила, конкретный API

Провайдер (Ankey, MyGrpc):
  - Создаёт транспортный клиент (httpx.Client с нужными настройками)
  - Регистрирует компилятор (registry.register("http", compile_http_operation))
  - Реализует HttpPagingStrategy (Ankey-специфичные ключи items/data/users/...)
  - Реализует error_reason_fn (детектит "resourceexists" из тела ответа)
  - Настраивает auth (AnkeyAuth с Basic Auth credentials)
  - Передаёт Driver в TargetGateway

Ядро (TargetKernel, TargetGateway):
  - Управляет retry-политикой
  - Классифицирует ошибки (FaultKind)
  - Применяет redaction к payload и headers
  - Считает статистику
```

**Пример сборки для Ankey (из `AnkeyTargetProvider.build_core_runtime()`):**

```python
def build_core_runtime(self, *, transport=None, include_reader=True) -> TargetRuntime:
    api = self._api_settings
    base_url = f"https://{api.host}:{api.port}"

    # 1. Загрузить и обновить spec
    from connector.domain.target_dsl import load_target_spec   # lazy import
    spec = load_target_spec("ankey")
    spec = apply_retry_overrides(spec, api)

    # 2. Собрать ядро с реестром компиляторов
    kernel = TargetKernel(
        spec,
        compiler_registry=build_transport_compiler_registry(),  # "http" → compile_http_operation
    )

    # 3. Создать httpx.Client с Ankey-специфичными настройками
    client = build_http_client(HttpClientSettings(
        base_url=base_url,
        timeout_seconds=api.timeout_seconds,
        tls_skip_verify=api.tls_skip_verify,
        ca_file=api.ca_file,
        transport=transport,        # None в prod, MockTransport в тестах
        auth=AnkeyAuth(             # Провайдер-специфичная аутентификация
            username=api.username or "",
            password=api.password or "",
        ),
    ))

    # 4. Создать Driver (провайдер настраивает paging и error_reason_fn)
    driver = AnkeyHttpDriver(client)    # Фабрика: BaseHttpDriver + AnkeyPagingStrategy

    # 5. Собрать Gateway (владелец retry-политики)
    gateway = TargetGateway(
        driver,
        kernel,
        mutation_registry=TargetMutationRegistry(build_ankey_mutations()),
    )

    return DefaultTargetRuntime(gateway=gateway, ...)
```

Один провайдер может регистрировать несколько `kind` в реестре — например, основные операции через HTTP, а streaming-чтение через gRPC. В этом случае `driver` должен реализовывать оба пути (или быть составным).

---

## 8. FAQ

### Q: Почему Driver не должен ретраить?

**A:** Потому что retry — это политика, а не механизм. Retry зависит от:
- Типа ошибки (`FaultKind` из `TargetSpec.fault_rules`)
- Правил повторов (`RetryRule` с `match_fault`, `match_status`, `match_reason`)
- Количества уже использованных попыток (`retries_used`)
- Задержки (`Retry-After` заголовок или экспоненциальный backoff)
- Мутаций payload (`retry_action.mutation` — например, смена операции)

Всё это знает `TargetGateway`. Driver знает только как сделать один запрос. Если Driver будет ретраить сам, Gateway не сможет применить правильную политику, отобразить корректную статистику или вернуть `retry_after_s` наверх.

### Q: Как добавить кастомную аутентификацию в HTTP transport?

**A:** Создайте класс, реализующий `httpx.Auth` Protocol, и передайте его в `HttpClientSettings.auth`:

```python
class BearerTokenAuth(httpx.Auth):
    def __init__(self, token: str) -> None:
        self._token = token

    def auth_flow(self, request: httpx.Request):
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request

settings = HttpClientSettings(
    base_url="https://my-api.example.com",
    auth=BearerTokenAuth("my-secret-token"),
)
client = build_http_client(settings)
```

Для OAuth2 с автообновлением токена — аналогично, но `auth_flow` может делать дополнительный запрос на `/token` endpoint. httpx корректно обработает это через генераторный протокол `auth_flow`.

### Q: Чем отличается DriverResponse(ok=False, answer_code=409) от DriverError(code="NETWORK_ERROR")?

**A:** Принципиально разные ситуации:

```
DriverResponse(ok=False, answer_code=409):
  - Соединение состоялось
  - Сервер получил запрос
  - Сервер вернул HTTP-ответ (409 Conflict)
  - Тело ответа может содержать диагностику
  - Gateway: classify_fault(status_code=409) → CONFLICT → retry по правилам

DriverError(code="NETWORK_ERROR"):
  - Соединение не состоялось (или прервалось)
  - Нет HTTP-ответа
  - Причина: TCP timeout, SSL handshake failure, etc.
  - Gateway: classify_fault(error_code="NETWORK_ERROR") → TRANSIENT → retry
```

Оба случая могут привести к retry — но через разные пути классификации в `TargetKernel`.

### Q: Можно ли один провайдер использовать несколько транспортов?

**A:** Да. `TransportCompilerRegistry` поддерживает любое количество зарегистрированных `kind`. Пример:

```python
registry.register("http", compile_http_operation)
registry.register("grpc", compile_grpc_operation)
```

В `TargetSpec.operations` каждая операция может иметь свой `kind`. Одни операции будут работать через HTTP, другие — через gRPC. `TargetDriver` в этом случае должен уметь обрабатывать compiled_request обоих типов:

```python
def execute(self, compiled_request, payload=None):
    if isinstance(compiled_request, HttpRequest):
        return self._execute_http(compiled_request, payload)
    elif isinstance(compiled_request, GrpcCompiledRequest):
        return self._execute_grpc(compiled_request, payload)
    raise DriverError("unknown request type", code="CONFIG_ERROR")
```

Или можно использовать два отдельных driver, выбирая нужный в зависимости от типа compiled_request через паттерн Visitor/dispatch.

### Q: Что произойдёт если extract_items() вернёт пустой список?

**A:** `BaseHttpDriver.iter_batches()` увидит `not items == True` и выполнит `break`. Итерация завершится нормально. Gateway и вышестоящий код получат пустой набор страниц — это валидный сигнал "данных нет". Ошибки не будет. Это стандартный способ для сервера сообщить "всё выдано".

`extract_items()` должна поднимать `ValueError` только если _формат_ ответа не распознан (не ожидаемый dict или list). Пустой список `[]` — валидный и нормальный ответ.

### Q: Как тестировать Driver без реального сервера?

**A:** Два паттерна:

**1. httpx.MockTransport** (для HTTP-транспорта) — рекомендуемый подход:

```python
def responder(request: httpx.Request) -> httpx.Response:
    assert request.method == "PUT"
    assert "/user/u-1" in str(request.url)
    return httpx.Response(200, json={"id": "u-1", "status": "updated"})

client = build_http_client(HttpClientSettings(
    base_url="https://ankey.local",
    transport=httpx.MockTransport(responder),
))
driver = AnkeyHttpDriver(client)
response = driver.execute(
    HttpRequest(method="PUT", path="/ankey/managed/user/u-1", ...),
    payload={"name": "Alice"},
)
assert response.ok is True
```

**2. Инжекция `request_fn`** — для тестирования `BaseHttpDriver` в изоляции от httpx:

```python
def mock_request_fn(client, req: HttpRequest) -> HttpOutcome:
    return HttpOutcome(response=HttpResponsePayload(
        status_code=200,
        headers={},
        body={"ok": True},
        body_snippet='{"ok": true}',
    ))

driver = BaseHttpDriver(
    client=MagicMock(),    # Не используется
    paging=SomePagingStrategy(),
    request_fn=mock_request_fn,   # ← Инжекция
)
```

### Q: Как добавить request interceptor / event hook для трейсинга?

**A:** Используйте `HttpClientSettings.event_hooks`. httpx поддерживает `request` и `response` хуки:

```python
import logging

logger = logging.getLogger("http_transport")

def log_request(request: httpx.Request) -> None:
    logger.debug("→ %s %s", request.method, request.url)

def log_response(response: httpx.Response) -> None:
    logger.debug("← %s %s", response.status_code, response.url)

settings = HttpClientSettings(
    base_url="https://ankey.local",
    event_hooks={
        "request": [log_request],
        "response": [log_response],
    },
)
```

Для трейсинга (OpenTelemetry) можно использовать `opentelemetry-instrumentation-httpx` — оно добавляет хуки автоматически. Важно: хуки не должны делать retry или модифицировать запрос семантически — только логировать/инструментировать.

---

## 9. Тестовое покрытие HTTP transport

### test_http_transport_request_once.py

Файл: `tests/unit/infrastructure/test_http_transport_request_once.py`

Покрывает атомарную функцию `request_once()` и нормализатор `normalize_http_outcome()`:

| Тест | Что проверяется |
|------|----------------|
| `test_request_once_sends_json_payload` | JSON payload корректно сериализуется и отправляется. Метод POST, путь и тело — точно совпадают с HttpRequest |
| `test_request_once_returns_text_when_invalid_json` | Если тело не валидный JSON, возвращается текст. `body == "not-json"`, `body_snippet == "not-json"`, `error_code is None` |
| `test_request_once_maps_network_error_to_transport_error` | `httpx.TransportError` маппируется в `HttpErrorPayload(code="NETWORK_ERROR")`. `status_code is None` после нормализации |

Паттерн тестирования: `httpx.MockTransport(responder)` + `build_http_client()` с mock transport. Это позволяет тестировать через весь стек (`build_http_client` → `request_once` → `normalize_http_outcome`) без реального сервера.

```python
def _make_client(transport: httpx.BaseTransport) -> httpx.Client:
    return build_http_client(
        HttpClientSettings(
            base_url="https://ankey.local",
            transport=transport,
        )
    )
```

Этот helper — стандартный паттерн, который следует копировать в тестах новых транспортных провайдеров.

### test_target_ankey_driver.py

Файл: `tests/unit/infrastructure/test_target_ankey_driver.py`

Покрывает `AnkeyHttpDriver` (который является `BaseHttpDriver` с `AnkeyPagingStrategy` и `_detect_ankey_error_reason`):

| Тест | Что проверяется |
|------|----------------|
| `test_execute_non_ok_extracts_provider_reason_and_retry_after` | HTTP 409 с `{"message": "Resource exists"}` и `Retry-After: 2`. Результат: `response.ok=False`, `answer_code=409`, `error_reason="resourceexists"`, `retry_after_s=2.0` |
| `test_iter_batches_stops_when_max_batches_reached` | При `max_batches=1` делается ровно один HTTP-запрос. `call_count == 1`. Результат: `[(1, [{"id": 1}])]` |
| `test_iter_batches_error_keeps_provider_reason` | HTTP 409 в iter_batches → `DriverError` с `answer_code=409` и `error_reason="resourceexists"` |

Эти тесты демонстрируют два ключевых поведения:

1. **error_reason propagation**: `_detect_ankey_error_reason()` ищет строку `"resourceexists"` (case-insensitive) в теле ответа и значениях dict. Это позволяет `TargetKernel.resolve_retry_action()` применить специфическое правило с `match_reason="resourceexists"`.

2. **iter_batches как DriverError при неожиданном статусе**: В отличие от `execute()`, который возвращает `DriverResponse(ok=False)`, `iter_batches()` при неожиданном статусе поднимает `DriverError` — потому что нельзя частично выдать страницы и вернуть ошибку.

### Покрытие смежных модулей

Смежные тесты, не перечисленные в этом документе:

| Модуль | Тесты |
|--------|-------|
| `normalizer.py` | Через `test_request_once_*` (интеграционно). Отдельные unit-тесты для `_parse_retry_after` |
| `request_builder.py` | Unit-тесты path template rendering, merge query/headers |
| `compiler.py` | Unit-тесты compile с валидными и невалидными OperationSpec |
| `paging.py` | Unit-тесты `AnkeyPagingStrategy.extract_items()` с разными форматами тела |
| `client_factory.py` | Тест через `test_request_once_*` (инжекция transport) |

Тестирование по принципу "снизу вверх": сначала unit-тесты атомарных функций (`request_once`, `normalize_http_outcome`, `build_http_request`), затем интеграционные тесты driver (`BaseHttpDriver`, `AnkeyHttpDriver`), наконец сквозные тесты через `TargetGateway`.
