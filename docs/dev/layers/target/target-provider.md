# Target Provider — архитектура провайдеров и руководство по созданию нового

## Содержание

1. [Роль провайдера в архитектуре](#1-роль-провайдера-в-архитектуре)
2. [TargetProvider Protocol](#2-targetprovider-protocol)
3. [AnkeyTargetProvider — эталонная реализация](#3-ankeytargetprovider--эталонная-реализация)
4. [AnkeyAuth — аутентификация](#4-ankeyauth--аутентификация)
5. [AnkeyPagingStrategy — стратегия пагинации](#5-ankeypagingstrategy--стратегия-пагинации)
6. [_detect_ankey_error_reason — обнаружение причины ошибки](#6-_detect_ankey_error_reason--обнаружение-причины-ошибки)
7. [AnkeyMutations — мутации запросов при retry](#7-ankeymutations--мутации-запросов-при-retry)
8. [Payloads — формирование тела запроса](#8-payloads--формирование-тела-запроса)
9. [TargetProviderRegistry — реестр провайдеров](#9-targetproviderregistry--реестр-провайдеров)
10. [Factory — точка входа для delivery](#10-factory--точка-входа-для-delivery)
11. [DI wiring — как delivery использует target](#11-di-wiring--как-delivery-использует-target)
12. [HOW-TO: Создание нового провайдера](#12-how-to-создание-нового-провайдера)
13. [Чеклист для нового провайдера](#13-чеклист-для-нового-провайдера)
14. [FAQ](#14-faq)
15. [Тестовое покрытие](#15-тестовое-покрытие)

---

## 1. Роль провайдера в архитектуре

### 1.1 Что провайдер знает, а что — нет

Архитектура target-слоя построена на чётком разделении знания между **ядром (core)** и
**провайдером (provider)**. Это разделение не произвольное — оно следует принципу: ядро
управляет абстрактной механикой retry и исполнения операций, провайдер управляет конкретными
деталями транспорта и API.

```
+---------------------------+---------------------------+
|         CORE знает        |      PROVIDER знает       |
+---------------------------+---------------------------+
| retry backoff / jitter    | URL base_url              |
| fault classification      | схема аутентификации      |
| retry directive lookup    | формат пагинации          |
| operation catalog lookup  | специфика error_reason    |
| mutation application      | имена HTTP-заголовков     |
| stats counting            | мутации при retry         |
| capability checking       | структура ответа API      |
+---------------------------+---------------------------+
```

Ядро (`TargetKernel`, `TargetGateway`) никогда не импортирует `httpx`, не знает о заголовках
`X-Ankey-*`, не знает, что означает `resourceexists`. Провайдер собирает всё это вместе и
передаёт ядру готовые компоненты.

### 1.2 Граница ответственности

Провайдер владеет **transport details**:
- какой httpx transport использовать (реальный или mock)
- как построить `httpx.Client` (timeout, TLS, auth, limits)
- как аутентифицироваться (заголовки, JWT, Basic Auth)
- как пагинировать чтение (параметры запроса, извлечение items из ответа)
- как детектировать специфические причины ошибок API
- какие мутации доступны при retry

Ядро владеет **retry mechanics**:
- когда делать повтор (по `fault_rules` и `retry_rules` из YAML)
- сколько раз (по `retry_config.max_attempts`)
- с какой задержкой (exponential backoff + jitter)
- какую мутацию применить (по имени из `retry_rules[].mutation`)

### 1.3 Паттерн: провайдер = "сборщик" (assembler)

Провайдер — это не сервис и не репозиторий. Это **точка сборки** (wiring point): он принимает
конфигурацию (`ApiSettings`) и возвращает полностью сконфигурированный `DefaultTargetRuntime`.
После того как метод `build_core_runtime()` вернул результат, провайдер больше не нужен — всё
управление передаётся `TargetRuntime`.

### 1.4 ASCII-диаграмма: провайдер как точка сборки

```
AnkeyTargetProvider.build_core_runtime()
  |
  |-- load_target_spec("ankey")           [lazy import → TargetSpec из YAML]
  |    └── apply_retry_overrides(spec, api_settings)
  |         └── spec.model_copy(update={"retry_config": new_retry})
  |
  |-- build_transport_compiler_registry()
  |    └── TransportCompilerRegistry
  |         └── .register("http", compile_http_operation)
  |
  |-- TargetKernel(spec, compiler_registry)
  |    └── строит lookup-таблицы из spec (операции, fault_rules, retry_rules)
  |
  |-- HttpClientSettings(base_url, timeout, tls, auth=AnkeyAuth(...))
  |    └── build_http_client(settings) → httpx.Client
  |         └── AnkeyAuth(username, password)
  |              └── добавляет X-Ankey-Username / X-Ankey-Password / X-Ankey-NoSession
  |
  |-- AnkeyHttpDriver(client)
  |    └── BaseHttpDriver(
  |         client=client,
  |         paging=AnkeyPagingStrategy(),
  |         error_reason_fn=_detect_ankey_error_reason
  |        )
  |
  |-- TargetMutationRegistry(build_ankey_mutations())
  |    └── {"regenerate_target_id": regenerate_target_id}
  |
  |-- TargetGateway(driver, kernel, mutation_registry=mutations)
  |    └── владеет retry-циклом; не знает об httpx или Ankey
  |
  |-- TargetConnectionConfig(target_type="ankey", endpoint=base_url, ...)
  |
  └── DefaultTargetRuntime(gateway=gateway, config=config, has_reader=include_reader)
       └── возвращается delivery-слою как TargetRuntime (Protocol)
```

### 1.5 Место провайдера в общей карте слоёв

```
delivery (CLI containers.py)
  └── build_target_runtime_with_info(api_settings)   [публичный API infra/target]
       └── build_default_target_provider_registry(api_settings)
            └── TargetProviderRegistry
                 └── AnkeyTargetProvider(api_settings)  ← PROVIDER
                      └── build_core_runtime()
                           └── DefaultTargetRuntime     ← то, что получает delivery
```

---

## 2. TargetProvider Protocol

### 2.1 Контракт

```python
# connector/infra/target/core/provider.py

class TargetProvider(Protocol):
    """Контракт провайдера target-инфраструктуры."""

    target_type: str

    def build_core_runtime(
        self,
        *,
        transport: object | None = None,
        include_reader: bool = True,
    ) -> TargetRuntime: ...
```

Протокол определён в модуле `connector/infra/target/core/provider.py`. Это structural typing
(не ABC) — любой класс с атрибутом `target_type: str` и методом `build_core_runtime()` с
совместимой сигнатурой удовлетворяет контракту автоматически, без явного наследования.

### 2.2 Параметры build_core_runtime()

| Параметр         | Тип                      | Значение по умолчанию | Назначение |
|------------------|--------------------------|-----------------------|------------|
| `transport`      | `object \| None`         | `None`                | Override транспорта. `None` — реальный HTTP. В тестах передаётся `httpx.MockTransport` для перехвата запросов без реального сервера. |
| `include_reader` | `bool`                   | `True`                | Если `False`, свойство `runtime.reader` вернёт `None`. Используется в сценариях только-запись (apply pipeline без предварительного чтения). |

Обратите внимание: в реальной реализации `AnkeyTargetProvider` настройки API (`ApiSettings`)
передаются **через конструктор** (`__init__`), а не в сигнатуру `build_core_runtime()`. Это
позволяет создать провайдер один раз при сборке реестра и переиспользовать его.

### 2.3 Возвращаемое значение

`build_core_runtime()` возвращает `DefaultTargetRuntime`, который структурно удовлетворяет
протоколу `TargetRuntime`. Delivery-слой держит только Protocol-тип, не concrete class:

```python
# TargetRuntime Protocol (connector/infra/target/core/runtime.py)
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

### 2.4 Атрибут target_type

`target_type: str` — строковый идентификатор провайдера. Используется:
- как ключ в `TargetProviderRegistry` при поиске провайдера по имени
- в `TargetConnectionConfig.target_type`, который попадает в `TargetMeta`
- в логах и отчётах для идентификации целевой системы

Для `AnkeyTargetProvider` это `"ankey"` (совпадает с ключом `target_type` в YAML-спецификации).

---

## 3. AnkeyTargetProvider — эталонная реализация

Файл: `connector/infra/target/providers/ankey_rest/provider.py`

### 3.1 Конструктор

```python
class AnkeyTargetProvider:
    target_type = "ankey"

    def __init__(self, api_settings: ApiSettings) -> None:
        self._api_settings = api_settings
```

`ApiSettings` — это `connector.config.models.ApiConfig`. Провайдер сохраняет настройки и
использует их при вызове `build_core_runtime()`. Это позволяет фабрике создать провайдер с
настройками один раз, а затем вызвать сборку с разными override параметрами (например, разными
значениями `include_reader` или `transport`).

### 3.2 build_core_runtime() — детальный пошаговый разбор

Полный метод для наглядности:

```python
def build_core_runtime(
    self,
    *,
    transport: object | None = None,
    include_reader: bool = True,
) -> TargetRuntime:
    api = self._api_settings
    base_url = f"https://{api.host}:{api.port}"

    # Шаг 1: Lazy load_target_spec
    from connector.domain.target_dsl import load_target_spec
    spec = load_target_spec("ankey")

    # Шаг 2: apply_retry_overrides
    spec = apply_retry_overrides(spec, api)

    # Шаг 3 + 4: TransportCompilerRegistry + TargetKernel
    kernel = TargetKernel(
        spec,
        compiler_registry=build_transport_compiler_registry(),
    )

    # Шаг 5: HttpClient с AnkeyAuth
    client = build_http_client(
        HttpClientSettings(
            base_url=base_url,
            timeout_seconds=api.timeout_seconds,
            tls_skip_verify=api.tls_skip_verify,
            ca_file=api.ca_file,
            transport=transport,
            auth=AnkeyAuth(
                username=api.username or "",
                password=api.password or "",
            ),
        )
    )

    # Шаг 6: AnkeyHttpDriver
    driver = AnkeyHttpDriver(client)

    # Шаг 7 + 8: Mutations + TargetGateway
    gateway = TargetGateway(
        driver,
        kernel,
        mutation_registry=TargetMutationRegistry(build_ankey_mutations()),
    )

    # Шаг 9: DefaultTargetRuntime
    config = TargetConnectionConfig(
        target_type=self.target_type,
        endpoint=base_url,
        transport="http",
        principal=api.username or "",
    )
    return DefaultTargetRuntime(
        gateway=gateway,
        config=config,
        has_reader=include_reader,
    )
```

#### Шаг 1: Lazy import load_target_spec

```python
from connector.domain.target_dsl import load_target_spec
spec = load_target_spec("ankey")
```

Import выполняется **внутри метода**, а не на уровне модуля. Причина: `connector.domain.target_dsl`
импортирует из `connector.domain.dsl`, который в некоторых сценариях может транзитивно
тянуть `connector.infra.target` — возникает circular import. Lazy import (внутри функции)
разрывает этот цикл: к моменту вызова `build_core_runtime()` все модули уже загружены.

`load_target_spec("ankey")` читает файл `datasets/targets/ankey.target.yaml` и возвращает
замороженный объект `TargetSpec` (Pydantic frozen model). Ключ `"ankey"` соответствует
полю `target_type` в YAML и записи в `datasets/registry.yml`.

#### Шаг 2: apply_retry_overrides

```python
spec = apply_retry_overrides(spec, api)
```

Функция `apply_retry_overrides()` применяет runtime-настройки поверх дефолтных значений из
YAML-спецификации. Иммутабельное слияние через `model_copy(update=...)`:

```python
def apply_retry_overrides(spec: TargetSpec, api_settings: ApiSettings) -> TargetSpec:
    new_retry_config = spec.retry_config.model_copy(
        update={
            "max_attempts": api_settings.retries,
            "backoff_base": api_settings.retry_backoff_seconds,
        },
    )
    return spec.model_copy(update={"retry_config": new_retry_config})
```

Исходный `spec` остаётся неизменным (frozen Pydantic model). Создаётся новый объект
`RetryConfig` с переопределёнными полями, затем новый `TargetSpec` с новым `RetryConfig`.

Что переопределяется из `ApiSettings`:

| Поле ApiSettings          | Переопределяет поле RetryConfig |
|---------------------------|---------------------------------|
| `api_settings.retries`    | `retry_config.max_attempts`     |
| `api_settings.retry_backoff_seconds` | `retry_config.backoff_base` |

Поля `backoff_max` и `jitter` остаются из YAML-дефолтов (`30.0` и `true` для Ankey).

#### Шаг 3: build_transport_compiler_registry

```python
def build_transport_compiler_registry() -> TransportCompilerRegistry:
    registry = TransportCompilerRegistry()
    registry.register("http", compile_http_operation)
    return registry
```

`TransportCompilerRegistry` хранит соответствие `kind → compiler_fn`. Для каждой операции
в YAML указан `kind` (по умолчанию `"http"`). Компилятор `compile_http_operation` превращает
декларативное описание операции из YAML в исполняемый `CompiledOperation` объект, который
умеет строить конкретный `HttpRequest` с подставленными path-параметрами и query-параметрами.

#### Шаг 4: TargetKernel

```python
kernel = TargetKernel(spec, compiler_registry=build_transport_compiler_registry())
```

`TargetKernel` инициализирует lookup-таблицы из `TargetSpec`:
- каталог скомпилированных операций (alias → CompiledOperation)
- таблицы классификации ошибок (fault_rules)
- таблицы retry-директив (retry_rules)
- health-check alias

После создания kernel иммутабелен. Все последующие вызовы (`resolve_operation`, `classify_fault`,
`get_compiled_operation`) — только чтение lookup-таблиц.

#### Шаг 5: HttpClient с AnkeyAuth

```python
client = build_http_client(
    HttpClientSettings(
        base_url=base_url,           # "https://{host}:{port}"
        timeout_seconds=api.timeout_seconds,   # дефолт 20.0 с
        tls_skip_verify=api.tls_skip_verify,   # False в проде
        ca_file=api.ca_file,         # путь к CA bundle или None
        transport=transport,         # None в проде, mock в тестах
        auth=AnkeyAuth(
            username=api.username or "",
            password=api.password or "",
        ),
    )
)
```

`HttpClientSettings` — frozen dataclass. `build_http_client()` создаёт `httpx.Client` с
настроенными timeout, TLS, connection pool limits и auth. httpx автоматически вызывает
`auth.auth_flow()` перед каждым запросом.

Параметр `transport` передаётся напрямую в `httpx.Client(transport=...)`. В production это
`None` (httpx использует свой реальный transport). В тестах передаётся `httpx.MockTransport`
или `httpx.MockHandler`, что позволяет тестировать полную цепочку сборки без реального HTTP.

#### Шаг 6: AnkeyHttpDriver

```python
driver = AnkeyHttpDriver(client)
```

`AnkeyHttpDriver` — это фабричная функция (не класс), возвращающая `BaseHttpDriver`:

```python
def AnkeyHttpDriver(client: httpx.Client) -> BaseHttpDriver:
    return BaseHttpDriver(
        client=client,
        paging=AnkeyPagingStrategy(),
        error_reason_fn=_detect_ankey_error_reason,
    )
```

`BaseHttpDriver` — общий HTTP-драйвер из transport-слоя. Он выполняет единственный HTTP-запрос
(без retry), передаёт результат обратно в `TargetGateway`. Paging-стратегия и функция
обнаружения ошибок — это Ankey-специфичные детали, изолированные в провайдере.

#### Шаг 7: Mutations

```python
gateway = TargetGateway(
    driver,
    kernel,
    mutation_registry=TargetMutationRegistry(build_ankey_mutations()),
)
```

`build_ankey_mutations()` возвращает словарь `{"regenerate_target_id": regenerate_target_id}`.
`TargetMutationRegistry` оборачивает этот словарь и предоставляет метод `apply(name, spec)`.

`TargetGateway` при retry-цикле вызывает `mutation_registry.apply(mutation_name, current_spec)`,
если в `retry_rules` для данного fault указана мутация.

#### Шаг 8: TargetGateway

```python
gateway = TargetGateway(driver, kernel, mutation_registry=mutations)
```

`TargetGateway` — единственный владелец retry-политики. Он знает:
- `TargetDriver` — для единственной I/O-попытки
- `TargetKernel` — для классификации fault и lookup retry-директивы
- `TargetMutationRegistry` — для мутации `RequestSpec` перед следующей попыткой

Gateway не знает об httpx, об Ankey, о формате пагинации. Это намеренное ограничение.

Конструктор `TargetGateway`:

```python
def __init__(
    self,
    driver: TargetDriver[Any],
    kernel: TargetKernel,
    *,
    mutation_registry: TargetMutationRegistry | None = None,
) -> None:
```

#### Шаг 9: DefaultTargetRuntime

```python
config = TargetConnectionConfig(
    target_type=self.target_type,   # "ankey"
    endpoint=base_url,              # "https://host:port"
    transport="http",
    principal=api.username or "",   # для метаданных
)
return DefaultTargetRuntime(
    gateway=gateway,
    config=config,
    has_reader=include_reader,
)
```

`DefaultTargetRuntime` — фасад, объединяющий `TargetGateway` и `TargetConnectionConfig`.
Свойство `executor` всегда возвращает `gateway`. Свойство `reader` возвращает `gateway` если
`has_reader=True`, иначе `None`.

### 3.3 Роль вспомогательных функций модуля

В `provider.py` вынесены две вспомогательные функции верхнего уровня:

| Функция | Назначение |
|---------|-----------|
| `apply_retry_overrides(spec, api_settings)` | Иммутабельное слияние retry-конфига из ApiSettings в TargetSpec. Вынесена на верхний уровень для прямого тестирования. |
| `build_transport_compiler_registry()` | Создаёт реестр компиляторов с зарегистрированным `compile_http_operation`. Вынесена для переиспользования в тестах и новых провайдерах. |

---

## 4. AnkeyAuth — аутентификация

Файл: `connector/infra/target/providers/ankey_rest/auth.py`

### 4.1 Паттерн httpx.Auth

`AnkeyAuth` наследует `httpx.Auth` и реализует generator-протокол через `auth_flow()`:

```python
class AnkeyAuth(httpx.Auth):
    def __init__(self, *, username: str, password: str) -> None:
        self._username = username
        self._password = password

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["X-Ankey-Username"] = self._username
        request.headers["X-Ankey-Password"] = self._password
        request.headers["X-Ankey-NoSession"] = "true"
        request.headers.setdefault("accept", "application/json")
        yield request
```

`auth_flow()` — это Python-генератор. Точка `yield request` передаёт управление httpx: тот
отправляет запрос и возвращает ответ обратно в генератор. Поскольку Ankey использует
stateless-аутентификацию (нет refresh-токена, нет 401→ре-аутентификация логики), генератор
не обрабатывает ответ после `yield`.

### 4.2 Заголовки Ankey

| Заголовок            | Значение              | Назначение |
|----------------------|-----------------------|------------|
| `X-Ankey-Username`   | username из ApiConfig | Имя пользователя сервисного аккаунта |
| `X-Ankey-Password`   | password из ApiConfig | Пароль сервисного аккаунта |
| `X-Ankey-NoSession`  | `"true"`              | Запрет создания серверной сессии (stateless режим) |
| `accept`             | `"application/json"`  | Default Accept-заголовок, если не задан иной |

Заголовок `accept` устанавливается через `setdefault` — это позволяет переопределить его
в конкретных операциях при необходимости.

### 4.3 Почему не header_defaults в YAML

Credentials (username, password) конфиденциальны. YAML-спецификации операций хранятся в
репозитории и могут логироваться. Помещать credentials в YAML неприемлемо с точки зрения
безопасности. `AnkeyAuth` получает credentials из конфигурации runtime и добавляет их
программно, до того как запрос уходит по сети.

### 4.4 Интеграция с build_http_client

```python
# В HttpClientSettings
auth=AnkeyAuth(username=api.username or "", password=api.password or "")

# В build_http_client
return httpx.Client(
    ...
    auth=settings.auth,  # передаётся в httpx.Client
    ...
)
```

httpx вызывает `auth.auth_flow(request)` автоматически перед каждым исходящим запросом.
Разработчику не нужно вызывать это явно — достаточно передать `auth` в `httpx.Client`.

### 4.5 Тестирование AnkeyAuth

```python
# Пример unit-теста для AnkeyAuth
def test_ankey_auth_adds_headers() -> None:
    auth = AnkeyAuth(username="svc_user", password="s3cr3t")
    request = httpx.Request("GET", "https://example.com/api")

    # Прогоняем через генератор
    gen = auth.auth_flow(request)
    modified_request = next(gen)  # получаем запрос после добавления заголовков

    assert modified_request.headers["X-Ankey-Username"] == "svc_user"
    assert modified_request.headers["X-Ankey-Password"] == "s3cr3t"
    assert modified_request.headers["X-Ankey-NoSession"] == "true"
    assert modified_request.headers["accept"] == "application/json"
```

---

## 5. AnkeyPagingStrategy — стратегия пагинации

Файл: `connector/infra/target/providers/ankey_rest/driver.py`

### 5.1 Назначение

`AnkeyPagingStrategy` инкапсулирует знание о том, как Ankey REST API реализует пагинацию.
`BaseHttpDriver` использует стратегию для итерации по страницам в методе `iter_batches()`.

```python
class AnkeyPagingStrategy:
    _ITEMS_KEYS: tuple[str, ...] = (
        "items", "data", "users", "organizations", "orgs", "result"
    )
```

### 5.2 build_paged_request()

```python
def build_paged_request(
    self,
    base_req: HttpRequest,
    page: int,
    batch_size: int,
) -> HttpRequest:
    query = {**base_req.query, "page": page, "rows": batch_size}
    query.setdefault("_queryFilter", "true")
    return replace(base_req, query=query)
```

Метод принимает базовый `HttpRequest` (уже содержащий `query_defaults` из YAML-операции) и
добавляет пагинационные параметры:

| Параметр       | Источник           | Назначение |
|----------------|--------------------|------------|
| `page`         | аргумент (1-based) | Номер страницы. Ankey API использует 1-based нумерацию. |
| `rows`         | аргумент           | Размер страницы (batch_size). |
| `_queryFilter` | `setdefault`       | Активирует фильтрацию на стороне Ankey. Устанавливается только если не задан в `query_defaults`. |

`dataclasses.replace(base_req, query=query)` создаёт новый `HttpRequest` — иммутабельная
операция.

### 5.3 extract_items()

```python
def extract_items(self, body: Any) -> list[Any]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in self._ITEMS_KEYS:
            if key in body and isinstance(body[key], list):
                return body[key]
    raise ValueError("Unexpected response format: no items array")
```

Метод поддерживает два формата ответа:
1. **Прямой список** — `body` является `list`. Возвращается as-is.
2. **Словарь с известным ключом** — перебираются ключи `_ITEMS_KEYS` в порядке приоритета.

Несколько ключей необходимы, потому что Ankey REST API не консистентна между endpoints:
- `users.list` → ключ `"users"` или `"items"`
- `organizations.list` → ключ `"organizations"`, `"orgs"` или `"data"`
- некоторые endpoints → `"result"`

Если ни один формат не распознан, `ValueError` пробрасывается в `BaseHttpDriver`, который
оборачивает его в `DriverError` и передаёт в `TargetGateway` для нормализации.

### 5.4 Поведение при пагинации

`BaseHttpDriver.iter_batches()` вызывает `build_paged_request()` для каждой страницы,
выполняет HTTP-запрос, вызывает `extract_items()` на результате. Итерация прекращается
когда полученный список пуст (последняя страница) или достигнут лимит `max_pages`.

---

## 6. _detect_ankey_error_reason — обнаружение причины ошибки

Файл: `connector/infra/target/providers/ankey_rest/driver.py`

### 6.1 Назначение и сигнатура

```python
def _detect_ankey_error_reason(payload: Any, content_preview: str | None) -> str | None:
```

Функция анализирует тело ответа HTTP-запроса (после десериализации JSON) и `content_preview`
(сырой текст, если JSON-парсинг не удался) и возвращает строку с именем причины ошибки или
`None` если причина не распознана.

### 6.2 Логика обнаружения

```python
def _detect_ankey_error_reason(payload: Any, content_preview: str | None) -> str | None:
    haystacks: list[str] = []
    if isinstance(payload, str):
        haystacks.append(payload)
    if isinstance(payload, dict):
        haystacks.extend(str(v) for v in payload.values())
    if content_preview:
        haystacks.append(content_preview)
    joined = " ".join(haystacks).lower()
    if "resourceexists" in joined or "resource exists" in joined:
        return "resourceexists"
    return None
```

Функция объединяет все строковые значения из ответа (значения словаря или сам payload если
строка) и `content_preview` в один haystack, приводит к нижнему регистру и ищет подстроки.

Текущие поддерживаемые причины:

| Подстрока в haystack               | Возвращаемый reason |
|------------------------------------|---------------------|
| `"resourceexists"` или `"resource exists"` | `"resourceexists"` |

### 6.3 Путь через систему

```
HTTP response (409 Conflict)
  └── BaseHttpDriver
       └── error_reason_fn(payload, content_preview)  ← _detect_ankey_error_reason
            └── "resourceexists"
                 └── DriverResponse.error_reason = "resourceexists"
                      └── TargetGateway._fault_handler.from_driver_response(resp)
                           └── kernel.resolve_retry_action(fault_kind="CONFLICT", reason="resourceexists")
                                └── retry_rules: match_fault=CONFLICT, match_reason=resourceexists
                                     └── directive=RETRY_BACKOFF, mutation="regenerate_target_id"
                                          └── mutation_registry.apply("regenerate_target_id", current_spec)
                                               └── новый UUID → следующая попытка
```

### 6.4 Добавление новых причин

Для добавления нового reason достаточно расширить функцию `_detect_ankey_error_reason` и
добавить соответствующее правило в YAML-спецификацию:

```yaml
# В ankey.target.yaml
retry_rules:
  - directive: RETRY_BACKOFF
    match_fault: DATA
    match_reason: quotaexceeded      # новый reason
    mutation: some_mutation_name
```

```python
# В _detect_ankey_error_reason
if "quotaexceeded" in joined or "quota exceeded" in joined:
    return "quotaexceeded"
```

---

## 7. AnkeyMutations — мутации запросов при retry

Файл: `connector/infra/target/providers/ankey_rest/mutations.py`

### 7.1 Тип TargetMutation

```python
# connector/infra/target/core/mutations.py
TargetMutation = Callable[[RequestSpec], RequestSpec]
```

Мутация — это чистая функция: принимает `RequestSpec`, возвращает новый `RequestSpec`.
Никаких side-effects, никакого IO. Иммутабельность: исходный `RequestSpec` не изменяется.

### 7.2 regenerate_target_id()

```python
def regenerate_target_id(request_spec: RequestSpec) -> RequestSpec:
    params = dict(request_spec.operation_params or {})
    params["target_id"] = str(uuid.uuid4())
    return RequestSpec.operation(
        alias=request_spec.operation_alias,
        payload=request_spec.payload,
        params=params,
    )
```

Мутация генерирует новый UUID и помещает его в `operation_params["target_id"]`. При следующей
итерации retry `compile_http_operation` подставит новый UUID в path_template:
`/ankey/managed/user/{target_id}` → `/ankey/managed/user/NEW-UUID-HERE`.

Почему нужна эта мутация: Ankey REST API при `PUT /ankey/managed/user/{uuid}` может вернуть
`409 Conflict` с сообщением `"Resource exists"` если другой объект уже занимает этот UUID.
Новый UUID решает конфликт.

Поля `operation_alias` и `payload` остаются неизменными. Меняется только `target_id` в параметрах.

### 7.3 build_ankey_mutations()

```python
def build_ankey_mutations() -> Mapping[str, TargetMutation]:
    return {
        "regenerate_target_id": regenerate_target_id,
    }
```

Возвращает словарь `name → callable`. `TargetMutationRegistry` принимает этот словарь в
конструкторе и использует имена для поиска мутации по имени из `retry_rules[].mutation` в YAML.

### 7.4 Связь мутации с YAML-спецификацией

```yaml
# datasets/targets/ankey.target.yaml
retry_rules:
  - directive: RETRY_BACKOFF
    match_fault: CONFLICT
    match_reason: resourceexists
    mutation: regenerate_target_id   # ← имя совпадает с ключом в dict
```

`TargetKernel.resolve_retry_action()` возвращает `ResolvedRetryAction` с полем
`mutation="regenerate_target_id"`. `TargetGateway` вызывает
`mutation_registry.apply("regenerate_target_id", current_spec)`.

### 7.5 TargetMutationRegistry

```python
class TargetMutationRegistry:
    def __init__(self, mutations: Mapping[str, TargetMutation] | None = None) -> None:
        self._mutations: dict[str, TargetMutation] = dict(mutations or {})

    def apply(self, name: str, request_spec: RequestSpec) -> RequestSpec:
        mutation = self._mutations.get(name)
        if mutation is None:
            raise ValueError(f"unknown mutation: {name}")
        return mutation(request_spec)
```

Если мутация с именем из YAML не зарегистрирована в `TargetMutationRegistry`, при попытке
применить её выбрасывается `ValueError`, который `TargetGateway` конвертирует в `SPEC` fault.
Это fail-fast поведение при некорректной конфигурации.

---

## 8. Payloads — формирование тела запроса

Файл: `connector/infra/target/providers/ankey_rest/payloads/users.py`

### 8.1 Назначение

Payload-функции — это маппинг полей источника данных (dict из transform pipeline) в
формат тела HTTP-запроса, специфичный для Ankey REST API. Эта логика изолирована в
провайдере: ядро target-слоя не знает о формате данных конкретного API.

### 8.2 build_user_upsert_payload()

```python
def build_user_upsert_payload(source: dict[str, Any]) -> dict[str, Any]:
```

Преобразует строку из источника данных (dict) в payload для `PUT /ankey/managed/user/{uuid}`.

Обязательные входные поля:

| Поле источника      | Поле Ankey API    | Преобразование |
|---------------------|-------------------|----------------|
| `email`             | `mail`            | str, as-is |
| `last_name`         | `lastName`        | str, as-is |
| `first_name`        | `firstName`       | str, as-is |
| `middle_name`       | `middleName`      | str, as-is |
| `is_logon_disable`  | `isLogonDisabled` | `_to_bool()` |
| `user_name`         | `userName`        | str, as-is |
| `phone`             | `phone`           | str, as-is |
| `personnel_number`  | `personnelNumber` | str, as-is |
| `organization_id`   | `organization_id` | `_to_int_or_none()` |
| `position`          | `position`        | str, as-is |
| `usr_org_tab_num`   | `usrOrgTabNum`    | str, as-is |

Опциональные поля:

| Поле источника   | Поле Ankey API | Поведение |
|------------------|----------------|-----------|
| `manager_id`     | `managerId`    | `_to_int_or_none()`, может быть `None` |
| `password`       | `password`     | Включается в payload только если не пустой |

Поле `avatarId` всегда `None` в текущей версии.

### 8.3 Конверсионные утилиты

`_to_bool(value)` — принимает `bool`, `int`, `str` (`"1"/"true"/"yes"/"y"` → `True`,
`"0"/"false"/"no"/"n"` → `False`). Любое другое значение → `ValueError`.

`_to_int_or_none(value)` — принимает `None`, пустую строку (→ `None`), `int`, числовую строку.
`bool` запрещён явно (→ `ValueError`).

### 8.4 Место в pipeline

`build_user_upsert_payload()` вызывается из delivery-слоя **перед** формированием
`RequestSpec`. Это не часть ядра target — это бизнес-логика, специфичная для Ankey REST.

```
delivery (apply step)
  └── row: dict → build_user_upsert_payload(row) → payload: dict
       └── RequestSpec.operation(
               alias="users.upsert",
               params={"target_id": row["target_id"]},
               payload=payload,
           )
            └── runtime.executor.execute(spec)
```

---

## 9. TargetProviderRegistry — реестр провайдеров

### 9.1 Структура

Файл: `connector/infra/target/core/registry.py`

```python
class TargetProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, TargetProvider] = {}
        self._default_target_type: str | None = None
```

Реестр — простой dict. Ключ — `target_type` (строка). Значение — экземпляр провайдера.

### 9.2 Метод register()

```python
def register(self, provider: TargetProvider, *, default: bool = False) -> None:
```

- Читает `provider.target_type` как ключ
- Если ключ уже существует → `ValueError` (дубликат не допускается)
- Если `default=True` или реестр пуст → устанавливает этот провайдер как default

Важная деталь: первый зарегистрированный провайдер автоматически становится default
(`self._default_target_type is None` при первой регистрации). Явный `default=True` позволяет
контролировать это при множестве провайдеров.

### 9.3 Метод get()

```python
def get(self, target_type: str) -> TargetProvider:
```

Поиск по `target_type`. Если не найдено → `MissingTargetProviderError` с перечнем
известных провайдеров в сообщении:

```
Target provider 'unknown' is not registered. Known providers: ankey
```

### 9.4 Метод get_default()

```python
def get_default(self) -> TargetProvider:
```

Возвращает провайдер, помеченный как default. Если default не задан →
`MissingTargetProviderError("No default target provider is registered")`.

### 9.5 MissingTargetProviderError

```python
class MissingTargetProviderError(LookupError):
```

Специализированное исключение для ошибок lookup в реестре. Наследует `LookupError`,
что позволяет обрабатывать его на уровне factory.

### 9.6 build_default_target_provider_registry()

Файл: `connector/infra/target/providers/registry.py`

```python
def build_default_target_provider_registry(api_settings: ApiSettings) -> TargetProviderRegistry:
    registry = TargetProviderRegistry()
    registry.register(AnkeyTargetProvider(api_settings), default=True)
    return registry
```

Функция создаёт свежий реестр при каждом вызове (не singleton). `AnkeyTargetProvider`
регистрируется с флагом `default=True`. При добавлении нового провайдера именно эта функция
является точкой расширения.

---

## 10. Factory — точка входа для delivery

### 10.1 Публичный API пакета

Файл: `connector/infra/target/__init__.py`

```python
from connector.infra.target.core.factory import (
    TargetRuntimeBuildResult,
    build_target_runtime,
    build_target_runtime_with_info,
)
from connector.infra.target.core.models import (
    TargetCheckResult,
    TargetConnectionConfig,
    TargetFaultKind,
    TargetMeta,
    TargetStats,
)
from connector.infra.target.core.runtime import DefaultTargetRuntime, TargetRuntime

__all__ = [
    "build_target_runtime",
    "build_target_runtime_with_info",
    "TargetRuntimeBuildResult",
    "DefaultTargetRuntime",
    "TargetCheckResult",
    "TargetConnectionConfig",
    "TargetFaultKind",
    "TargetMeta",
    "TargetRuntime",
    "TargetStats",
]
```

Delivery импортирует только из `connector.infra.target` (пакет верхнего уровня),
а не из внутренних подмодулей. Это граница изоляции.

### 10.2 build_target_runtime() — упрощённый фасад

```python
def build_target_runtime(
    api_settings: ApiSettings,
    *,
    transport: object | None = None,
    include_reader: bool = True,
    runtime_mode: str | None = None,
    target_type: str | None = None,
) -> TargetRuntime:
```

Упрощённый фасад над `build_target_runtime_with_info()`. Возвращает только `TargetRuntime`,
без метаданных о выбранном провайдере и режиме. Подходит для большинства use cases.

| Параметр       | Значение по умолчанию | Назначение |
|----------------|-----------------------|------------|
| `transport`    | `None`                | `None` → реальный HTTP. `httpx.MockTransport` → тесты. |
| `include_reader` | `True`              | `False` → `runtime.reader is None`. |
| `runtime_mode` | `None` (→ `"core"`)   | Режим сборки. Сейчас только `"core"`. |
| `target_type`  | `None`                | `None` → default provider. Строка → поиск по имени. |

### 10.3 build_target_runtime_with_info() — полный алгоритм

```python
def build_target_runtime_with_info(
    api_settings: ApiSettings,
    *,
    transport: object | None = None,
    include_reader: bool = True,
    runtime_mode: str | None = None,
    target_type: str | None = None,
) -> TargetRuntimeBuildResult:
```

Алгоритм:

```
1. _resolve_runtime_mode(runtime_mode)
   └── None → "core"
   └── "core" → "core" (допустимо)
   └── любое другое → ValueError

2. build_default_target_provider_registry(api_settings)
   └── TargetProviderRegistry с AnkeyTargetProvider как default

3. target_type is None → registry.get_default()
   target_type is str  → registry.get(target_type)
                          └── MissingTargetProviderError если не найден

4. provider.build_core_runtime(transport=transport, include_reader=include_reader)
   └── DefaultTargetRuntime

5. TargetRuntimeBuildResult(
       runtime=runtime,
       target_type=provider.target_type,  # "ankey"
       requested_mode=requested_mode,     # "core"
       effective_mode="core",
   )
```

### 10.4 TargetRuntimeBuildResult

```python
@dataclass(frozen=True)
class TargetRuntimeBuildResult:
    runtime: TargetRuntime
    target_type: str
    requested_mode: TargetRuntimeMode   # Literal["core"]
    effective_mode: EffectiveTargetRuntimeMode  # Literal["core"]
```

`requested_mode` — то, что передал вызывающий (после нормализации).
`effective_mode` — реально использованный режим. Сейчас оба всегда `"core"`. Разделение
подготавливает API к будущим режимам без breaking change.

### 10.5 _resolve_runtime_mode()

```python
def _resolve_runtime_mode(*, runtime_mode: str | None = None) -> TargetRuntimeMode:
    candidate = runtime_mode if runtime_mode is not None else "core"
    normalized = str(candidate).strip().lower()
    allowed: set[str] = {"core"}
    if normalized not in allowed:
        raise ValueError(
            f"Invalid target runtime mode: {candidate!r}. Expected one of: core"
        )
    return normalized
```

Допустимые значения: только `"core"` (или `None` → `"core"`). Любая другая строка →
`ValueError`. Тесты `test_target_factory.py` проверяют `"broken"`, `"legacy"`, `"auto"` —
все должны поднимать `ValueError`.

---

## 11. DI wiring — как delivery использует target

### 11.1 Паттерн TargetContainer

Файл: `connector/delivery/cli/containers.py`

```python
def target_runtime_resource(
    api_settings: ApiConfig,
    transport: object | None,
) -> Iterator[TargetRuntimeBuildResult]:
    """Resource-генератор: build → yield → close."""
    result = build_target_runtime_with_info(api_settings, transport=transport)
    yield result
    result.runtime.close()


class TargetContainer(containers.DeclarativeContainer):
    api_settings = providers.Dependency(instance_of=ApiConfig)
    transport = providers.Dependency()

    runtime = providers.Resource(
        target_runtime_resource,
        api_settings=api_settings,
        transport=transport,
    )
```

`providers.Resource` в `dependency_injector` управляет lifecycle: при инициализации
контейнера вызывается `target_runtime_resource()`, при teardown — `result.runtime.close()`.

### 11.2 Монтирование в AppContainer

```python
class AppContainer(containers.DeclarativeContainer):
    ...
    target = providers.Container(
        TargetContainer,
        api_settings=_api_settings,
        transport=providers.Object(None),  # None → реальный HTTP
    )
```

В тестах `transport` можно заменить на `providers.Object(mock_transport)`.

### 11.3 Что delivery импортирует и что нет

```python
# ПРАВИЛЬНО: delivery импортирует только публичный API
from connector.infra.target import build_target_runtime, TargetRuntime
from connector.infra.target.core.factory import (
    TargetRuntimeBuildResult,
    build_target_runtime_with_info,
)

# ЗАПРЕЩЕНО: delivery не должна импортировать
from connector.infra.target.providers.ankey_rest.provider import AnkeyTargetProvider
from connector.infra.target.core.gateway import TargetGateway
import httpx  # delivery не знает о httpx
```

### 11.4 Protocol-ориентированное использование

Delivery работает с `TargetRuntime` как с Protocol, не как с конкретным классом:

```python
class SomeDeliveryService:
    def __init__(self, runtime: TargetRuntime) -> None:
        self._runtime = runtime  # тип: Protocol, не DefaultTargetRuntime

    def execute_upsert(self, payload: dict) -> ExecutionResult:
        spec = RequestSpec.operation(
            alias="users.upsert",
            params={"target_id": str(uuid4())},
            payload=payload,
        )
        return self._runtime.executor.execute(spec)
```

Это позволяет в тестах передавать `StubRuntime` или любой другой объект, структурно
совместимый с `TargetRuntime`, без наследования.

---

## 12. HOW-TO: Создание нового провайдера

Этот раздел содержит пошаговое руководство для добавления поддержки новой целевой системы.
В качестве примера используется гипотетический `MySystemTargetProvider`.

### Шаг 1: Создать структуру директорий

```
connector/infra/target/providers/my_system/
├── __init__.py
├── provider.py      # MySystemTargetProvider
├── auth.py          # MySystemAuth (если нужна кастомная auth)
├── driver.py        # MySystemHttpDriver + MySystemPagingStrategy
└── mutations.py     # build_my_system_mutations() (если нужны мутации)
```

```bash
mkdir -p connector/infra/target/providers/my_system
touch connector/infra/target/providers/my_system/__init__.py
touch connector/infra/target/providers/my_system/provider.py
touch connector/infra/target/providers/my_system/auth.py
touch connector/infra/target/providers/my_system/driver.py
touch connector/infra/target/providers/my_system/mutations.py
```

### Шаг 2: Написать YAML-спецификацию

Создать файл `datasets/targets/my_system.target.yaml`:

```yaml
# datasets/targets/my_system.target.yaml

target_type: my_system

capabilities:
  - check
  - execute
  - read_paged    # убрать если API не поддерживает чтение

health:
  operation_alias: health.check

# Классификация ошибок: HTTP-статус → FaultKind
fault_rules:
  - fault_kind: AUTH
    match_status: 401
  - fault_kind: PERMISSION
    match_status: 403
  - fault_kind: DATA
    match_status: 400
  - fault_kind: NOT_FOUND
    match_status: 404
  - fault_kind: CONFLICT
    match_status: 409
  - fault_kind: THROTTLE
    match_status: 429
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
  - directive: RETRY_AFTER
    match_fault: THROTTLE
  - directive: NO_RETRY
    match_fault: AUTH
  - directive: NO_RETRY
    match_fault: PERMISSION
  - directive: NO_RETRY
    match_fault: DATA
  - directive: NO_RETRY
    match_fault: NOT_FOUND
  - directive: NO_RETRY
    match_fault: CONFLICT

redaction:
  body_mode: truncated
  forbidden_metadata_keys:
    - authorization
    - x-my-system-token
    - cookie
  forbidden_fields:
    - password
    - token
    - secret

operations:
  health.check:
    expected_statuses: [200]
    data:
      method: GET
      path_template: /api/v1/health

  users.list:
    expected_statuses: [200]
    data:
      method: GET
      path_template: /api/v1/users

  users.upsert:
    expected_statuses: [200, 201]
    data:
      method: PUT
      path_template: /api/v1/users/{target_id}
```

Зарегистрировать в `datasets/registry.yml`:

```yaml
targets:
  ankey: datasets/targets/ankey.target.yaml
  my_system: datasets/targets/my_system.target.yaml   # добавить строку
```

### Шаг 3: Реализовать MySystemAuth

Если API использует Bearer токен из ApiSettings:

```python
# connector/infra/target/providers/my_system/auth.py

from __future__ import annotations

from collections.abc import Generator

import httpx


class MySystemAuth(httpx.Auth):
    """Добавляет Bearer-токен аутентификации в каждый запрос."""

    def __init__(self, *, token: str) -> None:
        self._token = token

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._token}"
        request.headers.setdefault("accept", "application/json")
        yield request


__all__ = ["MySystemAuth"]
```

Если API не требует кастомной auth (например, только TLS mutual auth), можно передать
`auth=None` в `HttpClientSettings` и использовать `default_headers` для статических заголовков.

### Шаг 4: Реализовать MySystemPagingStrategy

```python
# connector/infra/target/providers/my_system/driver.py (часть 1)

from __future__ import annotations

import dataclasses
from typing import Any

from connector.infra.target.transports.http.request_builder import HttpRequest


class MySystemPagingStrategy:
    """
    Стратегия пагинации для My System REST API.

    API использует offset/limit (0-based) и возвращает items в ключе "results".
    """

    def build_paged_request(
        self,
        base_req: HttpRequest,
        page: int,
        batch_size: int,
    ) -> HttpRequest:
        # My System API: offset-based, 0-based (page 1 → offset 0)
        offset = (page - 1) * batch_size
        query = {
            **base_req.query,
            "offset": offset,
            "limit": batch_size,
        }
        return dataclasses.replace(base_req, query=query)

    def extract_items(self, body: Any) -> list[Any]:
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            for key in ("results", "items", "data"):
                if key in body and isinstance(body[key], list):
                    return body[key]
        raise ValueError(f"Cannot extract items: unexpected format {type(body)}")
```

### Шаг 5: Реализовать detect_error_reason (если нужна)

```python
# connector/infra/target/providers/my_system/driver.py (часть 2)

def _detect_my_system_error_reason(payload: Any, content_preview: str | None) -> str | None:
    """Определить специфическую причину ошибки по содержимому ответа."""
    haystacks: list[str] = []
    if isinstance(payload, dict):
        haystacks.extend(str(v) for v in payload.values())
    if isinstance(payload, str):
        haystacks.append(payload)
    if content_preview:
        haystacks.append(content_preview)
    joined = " ".join(haystacks).lower()
    if "duplicate entry" in joined or "already exists" in joined:
        return "resourceexists"
    return None
```

Если API не имеет специфических причин ошибок — передать `error_reason_fn=None`.

### Шаг 6: Реализовать MySystemHttpDriver

```python
# connector/infra/target/providers/my_system/driver.py (окончание)

import httpx

from connector.infra.target.transports.http.driver_base import BaseHttpDriver


def MySystemHttpDriver(client: httpx.Client) -> BaseHttpDriver:
    """Фабрика HTTP-драйвера для My System REST API."""
    return BaseHttpDriver(
        client=client,
        paging=MySystemPagingStrategy(),
        error_reason_fn=_detect_my_system_error_reason,  # или None
    )


__all__ = ["MySystemHttpDriver", "MySystemPagingStrategy"]
```

### Шаг 7: Реализовать мутации (опционально)

Если API требует мутации при retry (например, тоже нужен новый UUID):

```python
# connector/infra/target/providers/my_system/mutations.py

from __future__ import annotations

import uuid
from collections.abc import Mapping

from connector.domain.ports.target.execution import RequestSpec
from connector.infra.target.core.mutations import TargetMutation


def regenerate_my_id(request_spec: RequestSpec) -> RequestSpec:
    """Сгенерировать новый идентификатор ресурса перед повторной попыткой."""
    params = dict(request_spec.operation_params or {})
    params["target_id"] = str(uuid.uuid4())
    return RequestSpec.operation(
        alias=request_spec.operation_alias,
        payload=request_spec.payload,
        params=params,
    )


def build_my_system_mutations() -> Mapping[str, TargetMutation]:
    return {
        "regenerate_my_id": regenerate_my_id,
    }


__all__ = ["build_my_system_mutations", "regenerate_my_id"]
```

Если мутации не нужны — передать `TargetMutationRegistry()` без аргументов (пустой реестр).

### Шаг 8: Реализовать MySystemTargetProvider

```python
# connector/infra/target/providers/my_system/provider.py

from __future__ import annotations

from connector.config.models import ApiConfig as ApiSettings
from connector.infra.target.core.gateway import TargetGateway
from connector.infra.target.core.kernel import TargetKernel
from connector.infra.target.core.models import TargetConnectionConfig
from connector.infra.target.core.mutations import TargetMutationRegistry
from connector.infra.target.core.runtime import DefaultTargetRuntime, TargetRuntime
from connector.infra.target.core.transport_compiler import TransportCompilerRegistry
from connector.infra.target.providers.my_system.auth import MySystemAuth
from connector.infra.target.providers.my_system.driver import MySystemHttpDriver
from connector.infra.target.providers.my_system.mutations import build_my_system_mutations
from connector.infra.target.transports.http.client_factory import (
    HttpClientSettings,
    build_http_client,
)
from connector.infra.target.transports.http.compiler import compile_http_operation


class MySystemTargetProvider:
    """Provider сборки target runtime для My System REST API."""

    target_type = "my_system"

    def __init__(self, api_settings: ApiSettings) -> None:
        self._api_settings = api_settings

    def build_core_runtime(
        self,
        *,
        transport: object | None = None,
        include_reader: bool = True,
    ) -> TargetRuntime:
        """Собрать runtime My System REST на компонентах target-core."""
        api = self._api_settings
        base_url = f"https://{api.host}:{api.port}"

        # Шаг 1: Lazy import — разрывает потенциальный circular import
        from connector.domain.target_dsl import load_target_spec
        spec = load_target_spec("my_system")

        # Шаг 2: Переопределить retry из ApiSettings
        from connector.infra.target.providers.ankey_rest.provider import apply_retry_overrides
        spec = apply_retry_overrides(spec, api)

        # Шаги 3-4: Компилятор операций и ядро
        compiler_registry = TransportCompilerRegistry()
        compiler_registry.register("http", compile_http_operation)
        kernel = TargetKernel(spec, compiler_registry=compiler_registry)

        # Шаг 5: HTTP-клиент с аутентификацией
        # В данном примере используем token из api.password (как Bearer токен)
        client = build_http_client(
            HttpClientSettings(
                base_url=base_url,
                timeout_seconds=api.timeout_seconds,
                tls_skip_verify=api.tls_skip_verify,
                ca_file=api.ca_file,
                transport=transport,
                auth=MySystemAuth(token=api.password or ""),
            )
        )

        # Шаг 6: Driver с paging стратегией
        driver = MySystemHttpDriver(client)

        # Шаги 7-8: Мутации и Gateway
        mutations = TargetMutationRegistry(build_my_system_mutations())
        gateway = TargetGateway(driver, kernel, mutation_registry=mutations)

        # Шаг 9: Runtime
        config = TargetConnectionConfig(
            target_type=self.target_type,
            endpoint=base_url,
            transport="http",
            principal=api.username or "",
        )
        return DefaultTargetRuntime(
            gateway=gateway,
            config=config,
            has_reader=include_reader,
        )


__all__ = ["MySystemTargetProvider"]
```

### Шаг 9: Добавить __init__.py с экспортами

```python
# connector/infra/target/providers/my_system/__init__.py

from __future__ import annotations

from connector.infra.target.providers.my_system.auth import MySystemAuth
from connector.infra.target.providers.my_system.driver import MySystemHttpDriver
from connector.infra.target.providers.my_system.mutations import build_my_system_mutations
from connector.infra.target.providers.my_system.provider import MySystemTargetProvider

__all__ = [
    "MySystemAuth",
    "MySystemHttpDriver",
    "MySystemTargetProvider",
    "build_my_system_mutations",
]
```

### Шаг 10: Зарегистрировать провайдер в реестре

Файл: `connector/infra/target/providers/registry.py`

```python
from __future__ import annotations

from connector.config.models import ApiConfig as ApiSettings
from connector.infra.target.core.registry import TargetProviderRegistry
from connector.infra.target.providers.ankey_rest import AnkeyTargetProvider
from connector.infra.target.providers.my_system import MySystemTargetProvider


def build_default_target_provider_registry(api_settings: ApiSettings) -> TargetProviderRegistry:
    """Собрать реестр providers по умолчанию для production wiring."""
    registry = TargetProviderRegistry()
    # Существующий провайдер остаётся default
    registry.register(AnkeyTargetProvider(api_settings), default=True)
    # Новый провайдер регистрируется без default
    registry.register(MySystemTargetProvider(api_settings))
    return registry
```

После этого delivery может запросить провайдер по имени:

```python
runtime = build_target_runtime(
    api_settings,
    target_type="my_system",
)
```

Или использовать default (если my_system должен стать default — передать `default=True`
и не передавать `default=True` для Ankey).

### Шаг 11: Написать тесты

Минимальный набор тестов по аналогии с `tests/unit/infrastructure/test_target_factory.py`:

```python
# tests/unit/infrastructure/test_my_system_provider.py

from __future__ import annotations

import pytest
import httpx

from connector.config.models import ApiConfig as ApiSettings
from connector.infra.target.core.factory import build_target_runtime
from connector.infra.target.providers.my_system.auth import MySystemAuth
from connector.infra.target.providers.my_system.driver import MySystemPagingStrategy


@pytest.fixture()
def api_settings() -> ApiSettings:
    return ApiSettings(
        host="my-system.local",
        port=8443,
        username="svc",
        password="my-bearer-token",
        tls_skip_verify=True,
        ca_file=None,
        timeout_seconds=15.0,
        retries=3,
        retry_backoff_seconds=0.5,
        resource_exists_retries=3,
    )


def test_build_my_system_runtime_returns_runtime(api_settings: ApiSettings) -> None:
    """Фабрика собирает runtime без ошибок."""
    runtime = build_target_runtime(
        api_settings,
        target_type="my_system",
        include_reader=False,
    )

    meta = runtime.meta()
    assert meta.target_type == "my_system"
    assert meta.transport == "http"
    assert "my-system.local" in meta.endpoint


def test_my_system_runtime_loads_operation_catalog(api_settings: ApiSettings) -> None:
    """Операции из YAML доступны в kernel."""
    runtime = build_target_runtime(
        api_settings,
        target_type="my_system",
        include_reader=False,
    )
    gateway = runtime.executor
    operation = gateway._kernel.resolve_operation("users.upsert")
    assert operation.alias == "users.upsert"


def test_my_system_auth_adds_bearer_header() -> None:
    """MySystemAuth добавляет Authorization заголовок."""
    auth = MySystemAuth(token="my-secret-token")
    request = httpx.Request("GET", "https://my-system.local/api/health")

    gen = auth.auth_flow(request)
    modified = next(gen)

    assert modified.headers["Authorization"] == "Bearer my-secret-token"
    assert modified.headers["accept"] == "application/json"


def test_my_system_paging_extracts_results() -> None:
    """MySystemPagingStrategy извлекает items из ключа 'results'."""
    strategy = MySystemPagingStrategy()
    body = {"results": [{"id": 1}, {"id": 2}], "total": 2}
    items = strategy.extract_items(body)
    assert items == [{"id": 1}, {"id": 2}]


def test_my_system_paging_handles_direct_list() -> None:
    """Прямой список возвращается as-is."""
    strategy = MySystemPagingStrategy()
    body = [{"id": 1}, {"id": 2}]
    assert strategy.extract_items(body) == body


def test_my_system_paging_raises_on_unknown_format() -> None:
    """Неизвестный формат ответа → ValueError."""
    strategy = MySystemPagingStrategy()
    with pytest.raises(ValueError, match="Cannot extract items"):
        strategy.extract_items({"unknown_key": [1, 2, 3]})


def test_my_system_paging_builds_offset_request() -> None:
    """build_paged_request использует offset/limit вместо page/rows."""
    import dataclasses
    from connector.infra.target.transports.http.request_builder import HttpRequest

    strategy = MySystemPagingStrategy()
    base_req = HttpRequest(method="GET", url="/api/v1/users", query={}, headers={})
    paged = strategy.build_paged_request(base_req, page=3, batch_size=50)

    assert paged.query["offset"] == 100   # (3-1) * 50
    assert paged.query["limit"] == 50


def test_build_my_system_runtime_rejects_include_reader_false_operations(
    api_settings: ApiSettings,
) -> None:
    """runtime.reader is None когда include_reader=False."""
    runtime = build_target_runtime(
        api_settings,
        target_type="my_system",
        include_reader=False,
    )
    assert runtime.reader is None
```

---

## 13. Чеклист для нового провайдера

| Пункт | Обязательно | Примечание |
|-------|:-----------:|-----------|
| YAML-спецификация в `datasets/targets/` | Да | Должна содержать `target_type`, `capabilities`, `fault_rules`, `retry_config`, `retry_rules`, `operations` |
| Регистрация в `datasets/registry.yml` | Да | Ключ в секции `targets:` должен совпадать с именем файла без `.target.yaml` |
| `MyAuth(httpx.Auth)` или `auth=None` | Опционально | Нужна если API требует кастомных auth-заголовков |
| `MyPagingStrategy` если `read_paged` в capabilities | Да (при read_paged) | Реализовать `build_paged_request()` и `extract_items()` |
| `MyHttpDriver` фабричная функция | Да | Обёртка над `BaseHttpDriver` с paging и error_reason_fn |
| `MyTargetProvider` с атрибутом `target_type` | Да | Должен удовлетворять `TargetProvider` Protocol |
| `build_core_runtime()` с lazy import | Да | `load_target_spec` импортировать внутри метода |
| Регистрация в `providers/registry.py` | Да | Добавить в `build_default_target_provider_registry()` |
| Иммутабельное использование `TargetSpec` | Да | Использовать `model_copy(update=...)`, не мутировать |
| Мутации если `retry_rules` содержит `mutation:` | Да (если есть) | Имена в dict должны совпадать с YAML |
| `TargetConnectionConfig` с правильным `target_type` | Да | `target_type` должен совпадать с атрибутом класса |
| Unit-тесты | Да | Минимум: factory test, auth test, paging test |

---

## 14. FAQ

### Q: Зачем lazy import load_target_spec внутри build_core_runtime()?

`connector.domain.target_dsl` транзитивно импортирует из `connector.domain.dsl`, который в
некоторых сценариях (например, через `connector.domain.dsl.loader`) может тянуть
`connector.infra.target`. Если сделать `from connector.domain.target_dsl import load_target_spec`
на уровне модуля `provider.py`, Python встретит circular import при загрузке пакета.
Import внутри метода откладывается до момента вызова, когда все модули уже инициализированы.

Правило: всегда делать `from connector.domain.target_dsl import load_target_spec` внутри
`build_core_runtime()`, не на уровне модуля провайдера.

### Q: Что если мой API не поддерживает пагинацию?

Два варианта:

1. **include_reader=False при использовании**: delivery вызывает
   `build_target_runtime(api_settings, include_reader=False)`. В этом случае `runtime.reader`
   вернёт `None` и pipeline не будет пытаться читать из target.

2. **Убрать `read_paged` из `capabilities` в YAML**: если capability не заявлена,
   `TargetKernel.require_capability("read_paged")` выбросит ошибку при попытке `iter_pages()`.
   Передавать `error_reason_fn=None` и `paging=None` в `BaseHttpDriver` (или любую заглушку).

Рекомендация: убрать `read_paged` из `capabilities` — это явный контракт в YAML, документирующий
возможности API.

### Q: Как переопределить retry_config из ApiSettings для нового провайдера?

Переиспользовать функцию `apply_retry_overrides` из `ankey_rest/provider.py`:

```python
from connector.infra.target.providers.ankey_rest.provider import apply_retry_overrides

spec = load_target_spec("my_system")
spec = apply_retry_overrides(spec, api_settings)
```

Функция переопределяет `max_attempts` и `backoff_base` из `ApiSettings.retries` и
`ApiSettings.retry_backoff_seconds`. Это стандартное поведение для всех провайдеров.

### Q: Можно ли иметь несколько провайдеров с разными target_type?

Да. `TargetProviderRegistry` поддерживает любое количество провайдеров. Каждый регистрируется
под уникальным `target_type`. Delivery выбирает провайдер через параметр `target_type`:

```python
runtime_ankey = build_target_runtime(api_settings, target_type="ankey")
runtime_my_system = build_target_runtime(api_settings, target_type="my_system")
```

`ApiSettings` при этом общий (одна конфигурация подключения). Если разным провайдерам нужны
разные настройки подключения, нужно расширить фабрику.

### Q: Что означает is_default=True при регистрации?

Провайдер с `default=True` возвращается при вызове `registry.get_default()` и при передаче
`target_type=None` в `build_target_runtime()`. Только один провайдер может быть default
(последний с `default=True` перезаписывает предыдущий — нет, первый с `default=True` или
`default=False` с пустым реестром становится default; явный `default=True` перезаписывает).

Фактически: `default=True` устанавливает `_default_target_type = target_type` в `register()`.

### Q: Как тестировать провайдер без реального HTTP-сервера?

Передать `transport` в `build_core_runtime()` или `build_target_runtime()`:

```python
import httpx

# Создать mock handler
def mock_handler(request: httpx.Request) -> httpx.Response:
    if "/health" in str(request.url):
        return httpx.Response(200, json={"status": "ok"})
    return httpx.Response(404, json={"error": "not found"})

transport = httpx.MockTransport(handler=mock_handler)

runtime = build_target_runtime(
    api_settings,
    target_type="my_system",
    transport=transport,
)
result = runtime.check()
assert result.ok
```

`httpx.MockTransport` перехватывает все запросы до отправки по сети. `build_http_client()`
передаёт transport в `httpx.Client(transport=...)`.

### Q: Нужно ли регистрировать провайдер как default?

Нет, если delivery всегда передаёт явный `target_type`. Но если delivery использует
`target_type=None` (default), хотя бы один провайдер должен быть default. Если реестр пуст
или default не задан — `get_default()` вернёт `MissingTargetProviderError`.

Обратите внимание: первый зарегистрированный провайдер автоматически становится default
(даже без `default=True`). Это поведение в `TargetProviderRegistry.register()`:
`if default or self._default_target_type is None`.

### Q: Что если мой API использует JWT с refresh при 401?

В этом случае нужна нетривиальная реализация `httpx.Auth`:

```python
class JwtBearerAuth(httpx.Auth):
    requires_response_body = True  # важно: нужно тело ответа при 401

    def __init__(self, token_url: str, client_id: str, client_secret: str) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None

    def auth_flow(self, request):
        if self._token is None:
            self._token = self._fetch_token()
        request.headers["Authorization"] = f"Bearer {self._token}"
        response = yield request

        if response.status_code == 401:
            # Token expired — refresh and retry once
            self._token = self._fetch_token()
            request.headers["Authorization"] = f"Bearer {self._token}"
            yield request

    def _fetch_token(self) -> str:
        # Синхронный запрос для получения токена
        response = httpx.post(
            self._token_url,
            data={"client_id": self._client_id, "client_secret": self._client_secret},
        )
        response.raise_for_status()
        return response.json()["access_token"]
```

Такая auth делает повторный yield (с обновлённым токеном) при получении 401.
httpx поддерживает эту семантику через `requires_response_body = True`.

---

## 15. Тестовое покрытие

### 15.1 test_target_factory.py

Файл: `tests/unit/infrastructure/test_target_factory.py`

| Тест | Что проверяет |
|------|--------------|
| `test_build_target_runtime_returns_runtime_with_typed_meta` | Фабрика возвращает runtime с правильными метаданными (`target_type="ankey"`, `transport="http"`, `endpoint`). При `include_reader=False` `runtime.reader is None`. |
| `test_build_target_runtime_applies_retry_overrides` | `apply_retry_overrides()` переопределяет `spec.retry_config.max_attempts` и `backoff_base` значениями из `ApiSettings`. Доступ через `gateway._kernel.spec`. |
| `test_build_target_runtime_loads_operation_catalog` | После сборки `kernel` содержит все операции из YAML: `users.upsert`, `users.list`, `health.check` с правильными `path_template`. |
| `test_apply_retry_overrides_is_immutable` | Исходный `TargetSpec` после `apply_retry_overrides()` не изменяется. Возвращается новый объект с обновлёнными значениями. |
| `test_build_target_runtime_sets_single_attempt_client_and_injects_transport` | `transport` пробрасывается в `HttpClientSettings`. Monkeypatch `build_http_client` для перехвата. |
| `test_build_target_runtime_with_info_reports_core_mode` | `TargetRuntimeBuildResult.requested_mode == "core"` и `effective_mode == "core"`. |
| `test_build_target_runtime_rejects_invalid_mode` | `runtime_mode="broken"/"legacy"/"auto"` → `ValueError`. |
| `test_build_target_runtime_rejects_unknown_target_type` | `target_type="unknown-target"` → `MissingTargetProviderError`. |

### 15.2 test_target_registry.py

Файл: `tests/unit/infrastructure/test_target_registry.py`

| Тест | Что проверяет |
|------|--------------|
| `test_registry_registers_and_resolves_default_provider` | `register(a, default=True)` + `register(b)`. `get_default()` вернёт `a`. `get("b")` вернёт `b`. |
| `test_registry_rejects_duplicate_target_type` | Регистрация двух провайдеров с одинаковым `target_type` → `ValueError`. |
| `test_registry_raises_for_missing_provider` | `get("missing")` на пустом реестре → `MissingTargetProviderError`. |
| `test_registry_raises_when_default_is_not_defined` | `get_default()` на пустом реестре → `MissingTargetProviderError`. |

### 15.3 test_target_mutations.py

Файл: `tests/unit/infrastructure/test_target_mutations.py`

| Тест | Что проверяет |
|------|--------------|
| `test_regenerate_target_id_updates_operation_params` | `regenerate_target_id()` заменяет `target_id` в `operation_params` на новый UUID. Через `monkeypatch` на `uuid.uuid4` проверяется детерминизм. `operation_alias` и `payload` не изменяются. |

### 15.4 test_target_runtime.py

Файл: `tests/unit/infrastructure/test_target_runtime.py`

| Тест | Что проверяет |
|------|--------------|
| `test_runtime_exposes_executor_and_reader_when_enabled` | `has_reader=True` → `runtime.executor is gateway` и `runtime.reader is gateway`. |
| `test_runtime_reader_is_none_when_disabled` | `has_reader=False` → `runtime.reader is None`. |
| `test_runtime_meta_returns_typed_model` | `runtime.meta()` возвращает `TargetMeta` с правильными полями из `TargetConnectionConfig`. |
| `test_runtime_stats_returns_typed_model` | `runtime.stats()` делегирует в `gateway.get_stats()` и оборачивает в `TargetStats`. |
| `test_runtime_check_delegates_to_gateway` | `runtime.check()` возвращает тот же объект, что `gateway.health_check()`. |
| `test_runtime_reset_delegates_to_gateway` | `runtime.reset()` вызывает `gateway.reset_stats()`. |
| `test_runtime_close_delegates_to_gateway` | `runtime.close()` вызывает `gateway.close()`. |

Все тесты в `test_target_runtime.py` используют `StubGateway` — минимальный stub без зависимости
на реальный `TargetGateway`. Это позволяет тестировать `DefaultTargetRuntime` изолированно.

---

## Приложение A: Структура файлов провайдерного слоя

```
connector/infra/target/
├── __init__.py                          # публичный API: build_target_runtime, TargetRuntime
├── core/
│   ├── factory.py                       # build_target_runtime, build_target_runtime_with_info
│   ├── gateway.py                       # TargetGateway (retry owner)
│   ├── kernel.py                        # TargetKernel (spec + lookup tables)
│   ├── models.py                        # TargetMeta, TargetStats, TargetCheckResult, TargetConnectionConfig
│   ├── mutations.py                     # TargetMutation type, TargetMutationRegistry
│   ├── provider.py                      # TargetProvider Protocol
│   ├── registry.py                      # TargetProviderRegistry, MissingTargetProviderError
│   ├── runtime.py                       # TargetRuntime Protocol, DefaultTargetRuntime
│   ├── spec_models.py                   # TargetSpec, RetryConfig, OperationSpec (frozen Pydantic)
│   └── transport_compiler.py           # TransportCompilerRegistry
├── providers/
│   ├── registry.py                      # build_default_target_provider_registry()
│   └── ankey_rest/
│       ├── __init__.py                  # реэкспорт публичных сущностей
│       ├── provider.py                  # AnkeyTargetProvider, apply_retry_overrides
│       ├── auth.py                      # AnkeyAuth(httpx.Auth)
│       ├── driver.py                    # AnkeyHttpDriver, AnkeyPagingStrategy, _detect_ankey_error_reason
│       ├── mutations.py                 # regenerate_target_id, build_ankey_mutations
│       └── payloads/
│           └── users.py                 # build_user_upsert_payload
└── transports/
    └── http/
        ├── client_factory.py            # HttpClientSettings, build_http_client
        ├── compiler.py                  # compile_http_operation
        ├── driver_base.py               # BaseHttpDriver
        └── request_builder.py          # HttpRequest
```

## Приложение B: Полный маршрут запроса upsert

```
delivery
  └── build_user_upsert_payload(source_row)     → payload: dict
  └── RequestSpec.operation(
          alias="users.upsert",
          params={"target_id": uuid_str},
          payload=payload,
      )
  └── runtime.executor.execute(spec)
       └── TargetGateway.execute(spec)           [retry loop owner]
            └── kernel.get_compiled_operation("users.upsert")
                 └── compiled.build(alias, params)
                      └── HttpRequest(
                              method="PUT",
                              url="/ankey/managed/user/{uuid_str}",
                              query={"_prettyPrint": "true", "decrypt": "false"},
                              body=payload,
                          )
            └── driver.execute(compiled_request, payload)
                 └── BaseHttpDriver.execute()
                      └── AnkeyAuth.auth_flow(request)   [добавляет X-Ankey-* headers]
                      └── httpx.Client.send(request)     [реальный HTTP запрос]
                      └── DriverResponse(ok=True, status=201, payload=...)
            └── result_builder.execute_success(resp)
                 └── ExecutionResult(ok=True, ...)
  └── delivery получает ExecutionResult
```

При конфликте (409 + resourceexists):

```
driver.execute() → DriverResponse(ok=False, status=409, error_reason="resourceexists")
  └── fault_handler.from_driver_response(resp)
       └── fault_kind="CONFLICT", retry_action={directive=RETRY_BACKOFF, mutation="regenerate_target_id"}
  └── _apply_execute_retry(...)
       └── mutation_registry.apply("regenerate_target_id", current_spec)
            └── current_spec.operation_params["target_id"] = str(uuid4())  [новый UUID]
       └── retry_engine.sleep_before_retry(retries_used)  [backoff + jitter]
  └── следующая итерация цикла с новым target_id
```
