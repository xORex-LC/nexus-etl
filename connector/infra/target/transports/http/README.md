# connector/infra/target/transports/http

## Назначение

HTTP-транспорт на базе `httpx`. Компилирует операционные спеки в HTTP-запросы, выполняет их и нормализует ответы.

## Файлы

| Файл | Назначение |
|---|---|
| `compiler.py` | `HttpTransportCompiler` — `OperationSpec` → `HttpRequest` (рендеринг path templates, merge headers/params) |
| `request_builder.py` | `build_http_request(spec, params)` → `HttpRequest` DTO с `method/path/query/headers/json/timeout` |
| `request_once.py` | `execute_once(client, request)` → `DriverResponse|DriverError` — однократное выполнение без retry |
| `paging.py` | `HttpPager` — постраничная итерация `iter_pages(client, spec)` |
| `normalizer.py` | Нормализация httpx-ответа → `DriverResponse` |
| `client_factory.py` | `build_http_client(settings)` → `httpx.Client` с TLS, auth, timeout |
| `driver_base.py` | Базовый класс HTTP-driver |
| `op_models.py` | `HttpRequest`, `HttpClientSettings` DTO |

## Зависимости

**Зависит от:** `httpx`, `infra/target/driver.py`, `infra/target/core/spec_models.py`.  
**Используется:** `infra/target/providers/ankey_rest/driver.py`.
