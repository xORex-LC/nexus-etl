# Target Provider — архитектура провайдеров и руководство по созданию нового

> **Провайдер** — точка сборки (assembler), которая знает специфику конкретного API: схему
> аутентификации, формат пагинации, причины ошибок, мутации при retry. Он принимает
> `ApiSettings` и возвращает полностью сконфигурированный `DefaultTargetRuntime`.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [🛠️ HOW-TO: Создание нового провайдера](#️-how-to-создание-нового-провайдера)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
- [🧪 Тестовое покрытие](#-тестовое-покрытие)
- [❓ FAQ](#-faq)
- [🔗 Связанные документы](#-связанные-документы)
- [📝 История изменений](#-история-изменений)

---

## 📋 Обзор

Провайдер — это **паттерн assembler**: он принимает внешние настройки и собирает полный
объектный граф target-ядра. Провайдер существует только во время сборки — после того, как
`build_core_runtime()` вернул `DefaultTargetRuntime`, провайдер больше не нужен.

**Что провайдер знает** (API-специфика):

| Ответственность провайдера | Пример для Ankey |
|----------------------------|------------------|
| URL и схема соединения     | `https://{host}:{port}` |
| Схема аутентификации       | `X-Ankey-Username / X-Ankey-Password / X-Ankey-NoSession` |
| Формат пагинации           | `page`, `rows`, `_queryFilter=true` |
| Извлечение items из ответа | ключи `items / data / users / organizations / orgs / result` |
| Специфические причины ошибок | `"resourceexists"` / `"resource exists"` → `"resourceexists"` |
| Мутации при retry          | `regenerate_target_id` → новый UUID при 409 CONFLICT |

**Что провайдер НЕ знает** (роль ядра):

| Ответственность ядра | Компонент |
|----------------------|-----------|
| Retry backoff / jitter | `TargetRetryEngine` |
| Классификация fault по HTTP-статусу | `TargetKernel.classify_fault()` |
| Lookup retry-директивы | `TargetKernel.resolve_retry_action()` |
| Применение мутации по имени | `TargetGateway._apply_execute_retry()` |
| Подсчёт статистики | `TargetGateway` counters |

**Структура файлов:**

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

---

## 🏗️ Архитектура слоя

### Провайдер как точка сборки

```
AnkeyTargetProvider.build_core_runtime()
  │
  ├── load_target_spec("ankey")           [lazy import → TargetSpec из YAML]
  │    └── apply_retry_overrides(spec, api_settings)
  │         └── spec.model_copy(update={"retry_config": new_retry})
  │
  ├── build_transport_compiler_registry()
  │    └── TransportCompilerRegistry
  │         └── .register("http", compile_http_operation)
  │
  ├── TargetKernel(spec, compiler_registry)
  │    └── строит lookup-таблицы из spec (операции, fault_rules, retry_rules)
  │
  ├── HttpClientSettings(base_url, timeout, tls, auth=AnkeyAuth(...))
  │    └── build_http_client(settings) → httpx.Client
  │         └── AnkeyAuth(username, password)
  │              └── добавляет X-Ankey-Username / X-Ankey-Password / X-Ankey-NoSession
  │
  ├── AnkeyHttpDriver(client)
  │    └── BaseHttpDriver(
  │         client=client,
  │         paging=AnkeyPagingStrategy(),
  │         error_reason_fn=_detect_ankey_error_reason
  │        )
  │
  ├── TargetMutationRegistry(build_ankey_mutations())
  │    └── {"regenerate_target_id": regenerate_target_id}
  │
  ├── TargetGateway(driver, kernel, mutation_registry=mutations)
  │    └── владеет retry-циклом; не знает об httpx или Ankey
  │
  ├── TargetConnectionConfig(target_type="ankey", endpoint=base_url, ...)
  │
  └── DefaultTargetRuntime(gateway=gateway, config=config, has_reader=include_reader)
       └── возвращается delivery-слою как TargetRuntime (Protocol)
```

### Место провайдера в карте слоёв

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

## 🔑 Ключевые абстракции

### TargetProvider Protocol

**Файл:** `connector/infra/target/core/provider.py`

```python
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

Это **structural typing** (не ABC) — любой класс с атрибутом `target_type: str` и методом
`build_core_runtime()` с совместимой сигнатурой удовлетворяет контракту автоматически,
без явного наследования.

**Параметры `build_core_runtime()`:**

| Параметр         | Тип              | По умолчанию | Назначение |
|------------------|------------------|:------------:|------------|
| `transport`      | `object \| None` | `None`       | `None` — реальный HTTP. В тестах передаётся `httpx.MockTransport` для перехвата запросов без реального сервера. |
| `include_reader` | `bool`           | `True`       | Если `False`, свойство `runtime.reader` вернёт `None`. Используется в сценариях только-запись. |

> **Замечание:** В реальной реализации `AnkeyTargetProvider` настройки API (`ApiSettings`)
> передаются **через конструктор** (`__init__`), а не в сигнатуру `build_core_runtime()`.
> Это позволяет создать провайдер один раз при сборке реестра и переиспользовать его.

`build_core_runtime()` возвращает `DefaultTargetRuntime`, который структурно удовлетворяет
протоколу `TargetRuntime`. Delivery-слой держит только Protocol-тип, не concrete class.

### Атрибут target_type

`target_type: str` — строковый идентификатор провайдера. Используется:
- как ключ в `TargetProviderRegistry` при поиске провайдера по имени
- в `TargetConnectionConfig.target_type`, который попадает в `TargetMeta`
- в логах и отчётах для идентификации целевой системы

Для `AnkeyTargetProvider` это `"ankey"` (совпадает с ключом `target_type` в YAML-спецификации).

---

## 🗂️ Модели данных

### TargetProviderRegistry

**Файл:** `connector/infra/target/core/registry.py`

```python
class TargetProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, TargetProvider] = {}
        self._default_target_type: str | None = None
```

Простой `dict` провайдеров. Ключ — `target_type` (строка). Значение — экземпляр провайдера.

| Метод | Поведение |
|-------|-----------|
| `register(provider, *, default=False)` | Читает `provider.target_type` как ключ. Дубликат → `ValueError`. Если `default=True` или реестр пуст → устанавливает как default. |
| `get(target_type)` | Поиск по `target_type`. Не найдено → `MissingTargetProviderError` с перечнем известных. |
| `get_default()` | Возвращает default-провайдер. Default не задан → `MissingTargetProviderError`. |

```python
class MissingTargetProviderError(LookupError): ...
```

### TargetRuntimeBuildResult

**Файл:** `connector/infra/target/core/factory.py`

```python
@dataclass(frozen=True)
class TargetRuntimeBuildResult:
    runtime: TargetRuntime
    target_type: str
    requested_mode: TargetRuntimeMode          # Literal["core"]
    effective_mode: EffectiveTargetRuntimeMode # Literal["core"]
```

`requested_mode` — то, что передал вызывающий (после нормализации).
`effective_mode` — реально использованный режим. Сейчас оба всегда `"core"`.
Разделение подготавливает API к будущим режимам без breaking change.

### TargetConnectionConfig

**Файл:** `connector/infra/target/core/models.py`

| Поле | Тип | Назначение |
|------|-----|------------|
| `target_type` | `str` | Идентификатор провайдера, `"ankey"` |
| `endpoint` | `str` | `"https://host:port"` |
| `transport` | `str` | Всегда `"http"` для HTTP-провайдеров |
| `principal` | `str` | `api.username` — для метаданных/логов |

---

## 📊 Ключевые методы и алгоритмы

### AnkeyTargetProvider — 9 шагов сборки

**Файл:** `connector/infra/target/providers/ankey_rest/provider.py`

```python
class AnkeyTargetProvider:
    target_type = "ankey"

    def __init__(self, api_settings: ApiSettings) -> None:
        self._api_settings = api_settings
```

#### Шаг 1: Lazy import load_target_spec

```python
from connector.domain.target_dsl import load_target_spec
spec = load_target_spec("ankey")
```

Import выполняется **внутри метода**, а не на уровне модуля. Причина: `connector.domain.target_dsl`
транзитивно импортирует из `connector.domain.dsl`, который в некоторых сценариях может тянуть
`connector.infra.target` — возникает circular import. Lazy import разрывает этот цикл.

`load_target_spec("ankey")` читает `datasets/targets/ankey.target.yaml` и возвращает
замороженный `TargetSpec` (Pydantic frozen model).

#### Шаг 2: apply_retry_overrides

```python
spec = apply_retry_overrides(spec, api)
```

Иммутабельное слияние runtime-настроек поверх YAML-дефолтов через `model_copy(update=...)`:

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

Что переопределяется:

| Поле ApiSettings | Переопределяет поле RetryConfig |
|------------------|---------------------------------|
| `api_settings.retries` | `retry_config.max_attempts` |
| `api_settings.retry_backoff_seconds` | `retry_config.backoff_base` |

Поля `backoff_max` и `jitter` остаются из YAML-дефолтов (`30.0` и `true` для Ankey).

#### Шаг 3: TransportCompilerRegistry

```python
def build_transport_compiler_registry() -> TransportCompilerRegistry:
    registry = TransportCompilerRegistry()
    registry.register("http", compile_http_operation)
    return registry
```

Регистрирует соответствие `kind → compiler_fn`. Компилятор `compile_http_operation` превращает
декларативное описание операции из YAML в исполняемый `CompiledOperation`.

#### Шаг 4: TargetKernel

```python
kernel = TargetKernel(spec, compiler_registry=build_transport_compiler_registry())
```

`TargetKernel` инициализирует lookup-таблицы из `TargetSpec`. После создания — иммутабелен.

#### Шаг 5: HttpClient с AnkeyAuth

```python
client = build_http_client(
    HttpClientSettings(
        base_url=base_url,            # "https://{host}:{port}"
        timeout_seconds=api.timeout_seconds,
        tls_skip_verify=api.tls_skip_verify,
        ca_file=api.ca_file,
        transport=transport,          # None в production, mock в тестах
        auth=AnkeyAuth(
            username=api.username or "",
            password=api.password or "",
        ),
    )
)
```

Параметр `transport` передаётся в `httpx.Client(transport=...)`. В тестах передаётся
`httpx.MockTransport`, что позволяет тестировать полную цепочку сборки без реального HTTP.

#### Шаг 6: AnkeyHttpDriver

```python
driver = AnkeyHttpDriver(client)
```

`AnkeyHttpDriver` — фабричная функция (не класс), возвращающая `BaseHttpDriver`:

```python
def AnkeyHttpDriver(client: httpx.Client) -> BaseHttpDriver:
    return BaseHttpDriver(
        client=client,
        paging=AnkeyPagingStrategy(),
        error_reason_fn=_detect_ankey_error_reason,
    )
```

#### Шаг 7: Mutations

```python
mutation_registry = TargetMutationRegistry(build_ankey_mutations())
# {"regenerate_target_id": regenerate_target_id}
```

#### Шаг 8: TargetGateway

```python
gateway = TargetGateway(driver, kernel, mutation_registry=mutations)
```

`TargetGateway` — единственный владелец retry-политики. Знает о `TargetDriver`, `TargetKernel`,
`TargetMutationRegistry`. Не знает об httpx, об Ankey, о формате пагинации.

```python
def __init__(
    self,
    driver: TargetDriver[Any],
    kernel: TargetKernel,
    *,
    mutation_registry: TargetMutationRegistry | None = None,
) -> None: ...
```

#### Шаг 9: DefaultTargetRuntime

```python
config = TargetConnectionConfig(
    target_type=self.target_type,   # "ankey"
    endpoint=base_url,              # "https://host:port"
    transport="http",
    principal=api.username or "",
)
return DefaultTargetRuntime(
    gateway=gateway,
    config=config,
    has_reader=include_reader,
)
```

`DefaultTargetRuntime` — фасад, объединяющий `TargetGateway` и `TargetConnectionConfig`.
Свойство `executor` всегда возвращает `gateway`. Свойство `reader` возвращает `gateway`
если `has_reader=True`, иначе `None`.

### Вспомогательные функции провайдера

| Функция | Назначение |
|---------|-----------|
| `apply_retry_overrides(spec, api_settings)` | Иммутабельное слияние retry-конфига из `ApiSettings` в `TargetSpec`. Вынесена на верхний уровень для прямого тестирования. |
| `build_transport_compiler_registry()` | Создаёт реестр компиляторов с зарегистрированным `compile_http_operation`. Вынесена для переиспользования в тестах. |

### AnkeyAuth — аутентификация

**Файл:** `connector/infra/target/providers/ankey_rest/auth.py`

`AnkeyAuth` наследует `httpx.Auth` и реализует generator-протокол:

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

`auth_flow()` — Python-генератор. Точка `yield request` передаёт управление httpx: тот
отправляет запрос и возвращает ответ обратно в генератор. Поскольку Ankey использует
stateless-аутентификацию, генератор не обрабатывает ответ после `yield`.

**Заголовки Ankey:**

| Заголовок           | Значение              | Назначение |
|---------------------|-----------------------|------------|
| `X-Ankey-Username`  | `username` из ApiConfig | Имя пользователя сервисного аккаунта |
| `X-Ankey-Password`  | `password` из ApiConfig | Пароль сервисного аккаунта |
| `X-Ankey-NoSession` | `"true"`              | Запрет создания серверной сессии (stateless режим) |
| `accept`            | `"application/json"`  | Default Accept-заголовок, если не задан иной |

> Заголовок `accept` устанавливается через `setdefault` — позволяет переопределить его
> в конкретных операциях. Credentials в YAML не помещаются из соображений безопасности:
> `AnkeyAuth` получает их из конфигурации runtime и добавляет программно.

### AnkeyPagingStrategy — стратегия пагинации

**Файл:** `connector/infra/target/providers/ankey_rest/driver.py`

```python
class AnkeyPagingStrategy:
    _ITEMS_KEYS: tuple[str, ...] = (
        "items", "data", "users", "organizations", "orgs", "result"
    )
```

**`build_paged_request(base_req, page, batch_size)`** — добавляет пагинационные параметры:

| Параметр       | Источник           | Назначение |
|----------------|--------------------|------------|
| `page`         | аргумент (1-based) | Номер страницы |
| `rows`         | аргумент           | Размер страницы (batch_size) |
| `_queryFilter` | `setdefault`       | Активирует фильтрацию на стороне Ankey; устанавливается только если не задан в `query_defaults` |

```python
def build_paged_request(self, base_req, page, batch_size):
    query = {**base_req.query, "page": page, "rows": batch_size}
    query.setdefault("_queryFilter", "true")
    return replace(base_req, query=query)  # dataclasses.replace — иммутабельно
```

**`extract_items(body)`** — поддерживает два формата ответа:

1. `body` является `list` — возвращается as-is.
2. `body` является `dict` — перебираются ключи `_ITEMS_KEYS` в порядке приоритета.

Несколько ключей необходимы, потому что Ankey REST API непоследовательна между endpoints:
`users.list` → `"users"` / `"items"`, `organizations.list` → `"organizations"` / `"orgs"` / `"data"`.

Если ни один формат не распознан → `ValueError` → оборачивается в `DriverError`.

Итерация `BaseHttpDriver.iter_batches()` прекращается когда полученный список пуст
(последняя страница) или достигнут лимит `max_pages`.

### `_detect_ankey_error_reason` — обнаружение причины ошибки

**Файл:** `connector/infra/target/providers/ankey_rest/driver.py`

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

Объединяет все строковые значения из ответа и `content_preview` в haystack, приводит к
нижнему регистру и ищет подстроки.

| Подстрока в haystack | Возвращаемый reason |
|----------------------|---------------------|
| `"resourceexists"` или `"resource exists"` | `"resourceexists"` |

Путь через систему:

```
HTTP response (409 Conflict)
  └── BaseHttpDriver
       └── error_reason_fn(payload, content_preview) → "resourceexists"
            └── DriverResponse.error_reason = "resourceexists"
                 └── TargetGateway._fault_handler.from_driver_response(resp)
                      └── kernel.resolve_retry_action(fault_kind="CONFLICT", reason="resourceexists")
                           └── retry_rules: match_fault=CONFLICT, match_reason=resourceexists
                                └── directive=RETRY_BACKOFF, mutation="regenerate_target_id"
                                     └── mutation_registry.apply("regenerate_target_id", spec)
                                          └── новый UUID → следующая попытка
```

### AnkeyMutations — мутации запросов при retry

**Файл:** `connector/infra/target/providers/ankey_rest/mutations.py`

**Тип мутации:**

```python
TargetMutation = Callable[[RequestSpec], RequestSpec]
```

Мутация — это **чистая функция**: принимает `RequestSpec`, возвращает новый `RequestSpec`.
Никаких side-effects, никакого IO. Исходный `RequestSpec` не изменяется.

**`regenerate_target_id(request_spec)`:**

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

Генерирует новый UUID и помещает его в `operation_params["target_id"]`. При следующей
итерации retry `compile_http_operation` подставит новый UUID в path_template:
`/ankey/managed/user/{target_id}` → `/ankey/managed/user/NEW-UUID-HERE`.

Поля `operation_alias` и `payload` остаются неизменными.

**Связь с YAML-спецификацией:**

```yaml
# datasets/targets/ankey.target.yaml
retry_rules:
  - directive: RETRY_BACKOFF
    match_fault: CONFLICT
    match_reason: resourceexists
    mutation: regenerate_target_id   # ← имя совпадает с ключом в dict
```

`TargetKernel.resolve_retry_action()` возвращает `ResolvedRetryAction` с `mutation="regenerate_target_id"`.
`TargetGateway` вызывает `mutation_registry.apply("regenerate_target_id", current_spec)`.

**`TargetMutationRegistry`:**

```python
class TargetMutationRegistry:
    def apply(self, name: str, request_spec: RequestSpec) -> RequestSpec:
        mutation = self._mutations.get(name)
        if mutation is None:
            raise ValueError(f"unknown mutation: {name}")
        return mutation(request_spec)
```

Если мутация не зарегистрирована → `ValueError` → `TargetGateway` конвертирует в `SPEC` fault.
Это fail-fast поведение при некорректной конфигурации.

---

## 🔄 Взаимодействие с другими слоями

### Payloads — формирование тела запроса

**Файл:** `connector/infra/target/providers/ankey_rest/payloads/users.py`

Payload-функции — маппинг полей источника данных в формат тела HTTP-запроса Ankey REST API.
Изолированы в провайдере: ядро не знает о формате данных конкретного API.

**`build_user_upsert_payload(source)`** преобразует строку из источника в payload
для `PUT /ankey/managed/user/{uuid}`.

Обязательные поля:

| Поле источника     | Поле Ankey API    | Преобразование |
|--------------------|-------------------|----------------|
| `email`            | `mail`            | str, as-is |
| `last_name`        | `lastName`        | str, as-is |
| `first_name`       | `firstName`       | str, as-is |
| `middle_name`      | `middleName`      | str, as-is |
| `is_logon_disable` | `isLogonDisabled` | `_to_bool()` |
| `user_name`        | `userName`        | str, as-is |
| `phone`            | `phone`           | str, as-is |
| `personnel_number` | `personnelNumber` | str, as-is |
| `organization_id`  | `organization_id` | `_to_int_or_none()` |
| `position`         | `position`        | str, as-is |
| `usr_org_tab_num`  | `usrOrgTabNum`    | str, as-is |

Опциональные поля:

| Поле источника | Поле Ankey API | Поведение |
|----------------|----------------|-----------|
| `manager_id`   | `managerId`    | `_to_int_or_none()`, может быть `None` |
| `password`     | `password`     | Включается только если не пустой |

Поле `avatarId` всегда `None` в текущей версии.

Место в pipeline:

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

### Factory — точка входа для delivery

**Файл:** `connector/infra/target/core/factory.py`

**`build_target_runtime(api_settings, *, transport, include_reader, runtime_mode, target_type)`** —
упрощённый фасад, возвращает только `TargetRuntime`.

**`build_target_runtime_with_info(...)`** — возвращает `TargetRuntimeBuildResult` с метаданными.

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
       target_type=provider.target_type,   # "ankey"
       requested_mode=requested_mode,      # "core"
       effective_mode="core",
   )
```

**Параметры:**

| Параметр        | По умолчанию | Назначение |
|-----------------|:------------:|------------|
| `transport`     | `None`       | `None` → реальный HTTP. `httpx.MockTransport` → тесты. |
| `include_reader`| `True`       | `False` → `runtime.reader is None`. |
| `runtime_mode`  | `None` → `"core"` | Режим сборки. Сейчас только `"core"`. |
| `target_type`   | `None`       | `None` → default provider. Строка → поиск по имени. |

**`build_default_target_provider_registry()`:**

**Файл:** `connector/infra/target/providers/registry.py`

```python
def build_default_target_provider_registry(api_settings: ApiSettings) -> TargetProviderRegistry:
    registry = TargetProviderRegistry()
    registry.register(AnkeyTargetProvider(api_settings), default=True)
    return registry
```

Создаёт свежий реестр при каждом вызове (не singleton). При добавлении нового провайдера
именно эта функция является точкой расширения.

### DI wiring — как delivery использует target

**Файл:** `connector/delivery/cli/containers.py`

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

В `AppContainer`:

```python
target = providers.Container(
    TargetContainer,
    api_settings=_api_settings,
    transport=providers.Object(None),  # None → реальный HTTP
)
```

В тестах `transport` заменяется на `providers.Object(mock_transport)`.

---

## 🔌 Контракты и границы

**Публичный API пакета** (`connector/infra/target/__init__.py`):

```python
from connector.infra.target.core.factory import (
    TargetRuntimeBuildResult,
    build_target_runtime,
    build_target_runtime_with_info,
)
from connector.infra.target.core.models import (
    TargetCheckResult, TargetConnectionConfig, TargetFaultKind, TargetMeta, TargetStats,
)
from connector.infra.target.core.runtime import DefaultTargetRuntime, TargetRuntime
```

**Правила импорта:**

```python
# ПРАВИЛЬНО: delivery импортирует только публичный API
from connector.infra.target import build_target_runtime, TargetRuntime
from connector.infra.target.core.factory import (
    TargetRuntimeBuildResult,
    build_target_runtime_with_info,
)

# ЗАПРЕЩЕНО
from connector.infra.target.providers.ankey_rest.provider import AnkeyTargetProvider
from connector.infra.target.core.gateway import TargetGateway
import httpx  # delivery не знает о httpx
```

**Protocol-ориентированное использование** в delivery:

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

Это позволяет в тестах передавать `StubRuntime` без наследования.

**Инварианты:**

| Инвариант | Описание |
|-----------|----------|
| Lazy import в провайдере | `load_target_spec` импортируется только внутри `build_core_runtime()`, не на уровне модуля |
| Иммутабельный spec | `apply_retry_overrides` использует `model_copy()`, не мутирует оригинал |
| Driver single-attempt | `AnkeyHttpDriver` / `BaseHttpDriver` никогда не ретраит |
| Gateway retry-owner | Только `TargetGateway` управляет retry-циклом |
| Ядро не знает о API | `TargetKernel` / `TargetGateway` не содержат Ankey-специфичных литералов |

---

## 🛠️ HOW-TO: Создание нового провайдера

### Шаг 1: Создать структуру директорий

```
connector/infra/target/providers/my_system/
├── __init__.py
├── provider.py      # MySystemTargetProvider
├── auth.py          # MySystemAuth (если нужна кастомная auth)
├── driver.py        # MySystemHttpDriver + MySystemPagingStrategy
└── mutations.py     # build_my_system_mutations() (если нужны мутации)
```

### Шаг 2: Написать YAML-спецификацию

Создать `datasets/targets/my_system.target.yaml`:

```yaml
target_type: my_system

capabilities:
  - check
  - execute
  - read_paged    # убрать если API не поддерживает чтение

health:
  operation_alias: health.check

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
  forbidden_fields:
    - password
    - token

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

```python
# connector/infra/target/providers/my_system/auth.py

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

Если API не требует кастомной auth — передать `auth=None` в `HttpClientSettings`.

### Шаг 4: Реализовать MySystemPagingStrategy

```python
# connector/infra/target/providers/my_system/driver.py

import dataclasses
from typing import Any

from connector.infra.target.transports.http.request_builder import HttpRequest


class MySystemPagingStrategy:
    """
    Стратегия пагинации для My System REST API.
    API использует offset/limit (0-based) и возвращает items в ключе "results".
    """

    def build_paged_request(
        self, base_req: HttpRequest, page: int, batch_size: int,
    ) -> HttpRequest:
        offset = (page - 1) * batch_size  # 0-based offset
        query = {**base_req.query, "offset": offset, "limit": batch_size}
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
def _detect_my_system_error_reason(payload: Any, content_preview: str | None) -> str | None:
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
import httpx

from connector.infra.target.transports.http.driver_base import BaseHttpDriver


def MySystemHttpDriver(client: httpx.Client) -> BaseHttpDriver:
    """Фабрика HTTP-драйвера для My System REST API."""
    return BaseHttpDriver(
        client=client,
        paging=MySystemPagingStrategy(),
        error_reason_fn=_detect_my_system_error_reason,
    )


__all__ = ["MySystemHttpDriver", "MySystemPagingStrategy"]
```

### Шаг 7: Реализовать мутации (опционально)

```python
# connector/infra/target/providers/my_system/mutations.py

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
    return {"regenerate_my_id": regenerate_my_id}


__all__ = ["build_my_system_mutations", "regenerate_my_id"]
```

Если мутации не нужны — передать `TargetMutationRegistry()` без аргументов.

### Шаг 8: Реализовать MySystemTargetProvider

```python
# connector/infra/target/providers/my_system/provider.py

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
    HttpClientSettings, build_http_client,
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
        api = self._api_settings
        base_url = f"https://{api.host}:{api.port}"

        # Шаг 1: Lazy import — разрывает потенциальный circular import
        from connector.domain.target_dsl import load_target_spec
        spec = load_target_spec("my_system")

        # Шаг 2: apply_retry_overrides
        from connector.infra.target.providers.ankey_rest.provider import apply_retry_overrides
        spec = apply_retry_overrides(spec, api)

        # Шаг 3-4: Компилятор операций и ядро
        compiler_registry = TransportCompilerRegistry()
        compiler_registry.register("http", compile_http_operation)
        kernel = TargetKernel(spec, compiler_registry=compiler_registry)

        # Шаг 5: HTTP-клиент с аутентификацией
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

        # Шаг 6-8: Driver, Mutations, Gateway
        driver = MySystemHttpDriver(client)
        mutations = TargetMutationRegistry(build_my_system_mutations())
        gateway = TargetGateway(driver, kernel, mutation_registry=mutations)

        # Шаг 9: Runtime
        config = TargetConnectionConfig(
            target_type=self.target_type,
            endpoint=base_url,
            transport="http",
            principal=api.username or "",
        )
        return DefaultTargetRuntime(gateway=gateway, config=config, has_reader=include_reader)


__all__ = ["MySystemTargetProvider"]
```

### Шаг 9: Добавить `__init__.py`

```python
# connector/infra/target/providers/my_system/__init__.py

from connector.infra.target.providers.my_system.auth import MySystemAuth
from connector.infra.target.providers.my_system.driver import MySystemHttpDriver
from connector.infra.target.providers.my_system.mutations import build_my_system_mutations
from connector.infra.target.providers.my_system.provider import MySystemTargetProvider

__all__ = [
    "MySystemAuth", "MySystemHttpDriver", "MySystemTargetProvider", "build_my_system_mutations",
]
```

### Шаг 10: Зарегистрировать провайдер

**Файл:** `connector/infra/target/providers/registry.py`

```python
from connector.infra.target.providers.ankey_rest import AnkeyTargetProvider
from connector.infra.target.providers.my_system import MySystemTargetProvider


def build_default_target_provider_registry(api_settings: ApiSettings) -> TargetProviderRegistry:
    registry = TargetProviderRegistry()
    registry.register(AnkeyTargetProvider(api_settings), default=True)
    registry.register(MySystemTargetProvider(api_settings))  # добавить
    return registry
```

После этого delivery может запросить провайдер по имени:

```python
runtime = build_target_runtime(api_settings, target_type="my_system")
```

### Шаг 11: Написать тесты

```python
# tests/unit/infrastructure/test_my_system_provider.py

import pytest
import httpx

from connector.config.models import ApiConfig as ApiSettings
from connector.infra.target.core.factory import build_target_runtime
from connector.infra.target.providers.my_system.auth import MySystemAuth
from connector.infra.target.providers.my_system.driver import MySystemPagingStrategy


@pytest.fixture()
def api_settings() -> ApiSettings:
    return ApiSettings(
        host="my-system.local", port=8443, username="svc",
        password="my-bearer-token", tls_skip_verify=True, ca_file=None,
        timeout_seconds=15.0, retries=3, retry_backoff_seconds=0.5,
        resource_exists_retries=3,
    )


def test_build_my_system_runtime_returns_runtime(api_settings: ApiSettings) -> None:
    runtime = build_target_runtime(api_settings, target_type="my_system", include_reader=False)
    meta = runtime.meta()
    assert meta.target_type == "my_system"
    assert meta.transport == "http"
    assert "my-system.local" in meta.endpoint


def test_my_system_auth_adds_bearer_header() -> None:
    auth = MySystemAuth(token="my-secret-token")
    request = httpx.Request("GET", "https://my-system.local/api/health")
    gen = auth.auth_flow(request)
    modified = next(gen)
    assert modified.headers["Authorization"] == "Bearer my-secret-token"
    assert modified.headers["accept"] == "application/json"


def test_my_system_paging_extracts_results() -> None:
    strategy = MySystemPagingStrategy()
    body = {"results": [{"id": 1}, {"id": 2}], "total": 2}
    assert strategy.extract_items(body) == [{"id": 1}, {"id": 2}]


def test_my_system_paging_builds_offset_request() -> None:
    from connector.infra.target.transports.http.request_builder import HttpRequest
    strategy = MySystemPagingStrategy()
    base_req = HttpRequest(method="GET", url="/api/v1/users", query={}, headers={})
    paged = strategy.build_paged_request(base_req, page=3, batch_size=50)
    assert paged.query["offset"] == 100   # (3-1) * 50
    assert paged.query["limit"] == 50
```

### Чеклист для нового провайдера

| Пункт | Обязательно | Примечание |
|-------|:-----------:|------------|
| YAML-спецификация в `datasets/targets/` | Да | Должна содержать `target_type`, `capabilities`, `fault_rules`, `retry_config`, `retry_rules`, `operations` |
| Регистрация в `datasets/registry.yml` | Да | Ключ в секции `targets:` должен совпадать с именем файла без `.target.yaml` |
| `MyAuth(httpx.Auth)` или `auth=None` | Опционально | Нужна если API требует кастомных auth-заголовков |
| `MyPagingStrategy` если `read_paged` в capabilities | Да (при `read_paged`) | Реализовать `build_paged_request()` и `extract_items()` |
| `MyHttpDriver` фабричная функция | Да | Обёртка над `BaseHttpDriver` с paging и `error_reason_fn` |
| `MyTargetProvider` с атрибутом `target_type` | Да | Должен удовлетворять `TargetProvider` Protocol |
| `build_core_runtime()` с lazy import | Да | `load_target_spec` импортировать внутри метода |
| Регистрация в `providers/registry.py` | Да | Добавить в `build_default_target_provider_registry()` |
| Иммутабельное использование `TargetSpec` | Да | Использовать `model_copy(update=...)`, не мутировать |
| Мутации если `retry_rules` содержит `mutation:` | Да (если есть) | Имена в dict должны совпадать с YAML |
| `TargetConnectionConfig` с правильным `target_type` | Да | `target_type` должен совпадать с атрибутом класса |
| Unit-тесты | Да | Минимум: factory test, auth test, paging test |

---

## 💡 Типичные сценарии

### Успешный upsert пользователя

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
                 └── HttpRequest(
                         method="PUT",
                         url="/ankey/managed/user/{uuid_str}",
                         query={"_prettyPrint": "true", "decrypt": "false"},
                         body=payload,
                     )
            └── driver.execute(compiled_request, payload)
                 └── AnkeyAuth.auth_flow(request)   [добавляет X-Ankey-* headers]
                 └── httpx.Client.send(request)     [реальный HTTP запрос]
                 └── DriverResponse(ok=True, status=201, payload=...)
            └── result_builder.execute_success(resp)
                 └── ExecutionResult(ok=True, ...)
  └── delivery получает ExecutionResult
```

### Конфликт UUID → мутация и повтор

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

### Проверка доступности через health_check

```python
result = runtime.check()
# → TargetGateway.health_check()
#   → kernel.health_operation_alias() → "health.check"
#   → gateway.execute(RequestSpec.operation("health.check"))
#   → TargetCheckResult(ok=True, latency_ms=42.3)
```

### Тестирование провайдера с MockTransport

```python
def mock_handler(request: httpx.Request) -> httpx.Response:
    if "/health" in str(request.url):
        return httpx.Response(200, json={"status": "ok"})
    return httpx.Response(404, json={"error": "not found"})

transport = httpx.MockTransport(handler=mock_handler)
runtime = build_target_runtime(api_settings, target_type="my_system", transport=transport)
result = runtime.check()
assert result.ok
```

`httpx.MockTransport` перехватывает все запросы до отправки по сети. `build_http_client()`
передаёт transport в `httpx.Client(transport=...)`.

---

## 📌 Важные детали

### Режимы ошибок и их обработка

| Ситуация | Причина | Следствие |
|----------|---------|-----------|
| Неизвестная мутация в YAML | `retry_rules[].mutation` не зарегистрирован | `TargetGateway` → `SPEC` fault → `ExecutionResult(ok=False)` |
| Незарегистрированный `target_type` | `registry.get("unknown")` | `MissingTargetProviderError` до сборки runtime |
| Недопустимый `runtime_mode` | `_resolve_runtime_mode("legacy")` | `ValueError` до сборки runtime |
| `extract_items` не распознал формат | `ValueError` в `AnkeyPagingStrategy` | `DriverError` → `TargetGateway` → `TRANSIENT` fault |
| `load_target_spec` не нашёл файл | Нет записи в `registry.yml` | `DslLoadError` при вызове `build_core_runtime()` |

### Инварианты архитектуры

| Инвариант | Обоснование |
|-----------|-------------|
| Lazy import `load_target_spec` в провайдере | Разрывает circular import между `domain.target_dsl` и `infra.target` |
| Провайдер существует только во время сборки | После `build_core_runtime()` всё управление у `TargetRuntime` |
| `AnkeyAuth` не хранит ответ после `yield` | Stateless auth не требует обработки 401 |
| `_detect_ankey_error_reason` — чистая функция | Нет state, нет IO, легко тестируется изолированно |
| `regenerate_target_id` — чистая функция | Иммутабельна, side-effect free, детерминирована при тестировании |

### Особенности AnkeyPagingStrategy

- Нумерация страниц **1-based** (Ankey API требует `page=1` для первой страницы)
- `_queryFilter=true` устанавливается через `setdefault` — не перезаписывает явный параметр из YAML
- Перебор 6 ключей ответа в приоритетном порядке: `items`, `data`, `users`, `organizations`, `orgs`, `result`
- `ValueError` при неизвестном формате сигнализирует об изменении API Ankey

---

## 🧪 Тестовое покрытие

### `test_target_factory.py`

**Файл:** `tests/unit/infrastructure/test_target_factory.py`

| Тест | Что проверяет |
|------|--------------|
| `test_build_target_runtime_returns_runtime_with_typed_meta` | Фабрика возвращает runtime с `target_type="ankey"`, `transport="http"`. При `include_reader=False` → `runtime.reader is None`. |
| `test_build_target_runtime_applies_retry_overrides` | `apply_retry_overrides()` переопределяет `max_attempts` и `backoff_base` из `ApiSettings`. Доступ через `gateway._kernel.spec`. |
| `test_build_target_runtime_loads_operation_catalog` | Kernel содержит все операции из YAML: `users.upsert`, `users.list`, `health.check` с правильными `path_template`. |
| `test_apply_retry_overrides_is_immutable` | Исходный `TargetSpec` после `apply_retry_overrides()` не изменяется. |
| `test_build_target_runtime_sets_single_attempt_client_and_injects_transport` | `transport` пробрасывается в `HttpClientSettings`. |
| `test_build_target_runtime_with_info_reports_core_mode` | `requested_mode == "core"` и `effective_mode == "core"`. |
| `test_build_target_runtime_rejects_invalid_mode` | `runtime_mode="broken"/"legacy"/"auto"` → `ValueError`. |
| `test_build_target_runtime_rejects_unknown_target_type` | `target_type="unknown-target"` → `MissingTargetProviderError`. |

### `test_target_registry.py`

**Файл:** `tests/unit/infrastructure/test_target_registry.py`

| Тест | Что проверяет |
|------|--------------|
| `test_registry_registers_and_resolves_default_provider` | `register(a, default=True)` + `register(b)`. `get_default()` → `a`. `get("b")` → `b`. |
| `test_registry_rejects_duplicate_target_type` | Дубликат `target_type` → `ValueError`. |
| `test_registry_raises_for_missing_provider` | `get("missing")` → `MissingTargetProviderError`. |
| `test_registry_raises_when_default_is_not_defined` | `get_default()` на пустом реестре → `MissingTargetProviderError`. |

### `test_target_mutations.py`

**Файл:** `tests/unit/infrastructure/test_target_mutations.py`

| Тест | Что проверяет |
|------|--------------|
| `test_regenerate_target_id_updates_operation_params` | `regenerate_target_id()` заменяет `target_id` на новый UUID. `operation_alias` и `payload` не изменяются. |

### `test_target_runtime.py`

**Файл:** `tests/unit/infrastructure/test_target_runtime.py`

| Тест | Что проверяет |
|------|--------------|
| `test_runtime_exposes_executor_and_reader_when_enabled` | `has_reader=True` → `executor is gateway` и `reader is gateway`. |
| `test_runtime_reader_is_none_when_disabled` | `has_reader=False` → `reader is None`. |
| `test_runtime_meta_returns_typed_model` | `meta()` возвращает `TargetMeta` с полями из `TargetConnectionConfig`. |
| `test_runtime_stats_returns_typed_model` | `stats()` делегирует в `gateway.get_stats()` → `TargetStats`. |
| `test_runtime_check_delegates_to_gateway` | `check()` возвращает результат `gateway.health_check()`. |
| `test_runtime_reset_delegates_to_gateway` | `reset()` вызывает `gateway.reset_stats()`. |
| `test_runtime_close_delegates_to_gateway` | `close()` вызывает `gateway.close()`. |

Все тесты `test_target_runtime.py` используют `StubGateway` — минимальный stub без зависимости
на реальный `TargetGateway`.

---

## ❓ FAQ

**Зачем lazy import `load_target_spec` внутри `build_core_runtime()`?**

`connector.domain.target_dsl` транзитивно импортирует из `connector.domain.dsl`, который
в некоторых сценариях может тянуть `connector.infra.target` — возникает circular import.
Import внутри метода откладывается до момента вызова, когда все модули уже инициализированы.
Правило: всегда делать этот import внутри `build_core_runtime()`, не на уровне модуля.

**Что если мой API не поддерживает пагинацию?**

- Убрать `read_paged` из `capabilities` в YAML: `TargetKernel.require_capability("read_paged")`
  выбросит ошибку при попытке `iter_pages()`, явно документируя контракт.
- Использовать `include_reader=False` при сборке: `runtime.reader` вернёт `None`.

Рекомендация: убрать `read_paged` из `capabilities` — это явный контракт.

**Как переопределить retry_config из ApiSettings для нового провайдера?**

Переиспользовать функцию `apply_retry_overrides` из `ankey_rest/provider.py`:

```python
from connector.infra.target.providers.ankey_rest.provider import apply_retry_overrides
spec = apply_retry_overrides(spec, api_settings)
```

Переопределяет `max_attempts` и `backoff_base`. Стандартное поведение для всех провайдеров.

**Можно ли иметь несколько провайдеров с разными target_type?**

Да. `TargetProviderRegistry` поддерживает любое количество провайдеров. Delivery выбирает:

```python
runtime_ankey = build_target_runtime(api_settings, target_type="ankey")
runtime_my_system = build_target_runtime(api_settings, target_type="my_system")
```

**Нужно ли регистрировать провайдер как default?**

Нет, если delivery всегда передаёт явный `target_type`. Но если используется `target_type=None`,
хотя бы один провайдер должен быть default. Первый зарегистрированный автоматически становится
default (даже без `default=True`) — поведение в `register()`: `if default or self._default_target_type is None`.

**Что если мой API использует JWT с refresh при 401?**

Реализовать `httpx.Auth` с `requires_response_body = True` и повторным `yield request` после
получения 401. httpx поддерживает семантику ре-аутентификации через генератор `auth_flow()`.

---

## 🔗 Связанные документы

| Документ | Описание |
|----------|---------|
| [target-dsl.md](target-dsl.md) | DSL-спецификация `TargetSpec`, YAML-формат, загрузчик |
| [target-core.md](target-core.md) | `TargetKernel`, `TargetGateway`, engines, `DefaultTargetRuntime` |
| [target-transport.md](target-transport.md) | Transport protocol, HTTP transport, HOW-TO новый транспорт |
| [docs/adr/target/](../../../adr/target/) | ADR: TARGET-DEC-001, TARGET-DEC-003 — ключевые архитектурные решения |
| `datasets/targets/ankey.target.yaml` | Эталонная YAML-спецификация Ankey |
| `datasets/registry.yml` | Реестр всех target-спецификаций |

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-28 | Создан документация Target Providers | xORex-LC |
