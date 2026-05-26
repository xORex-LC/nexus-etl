# connector/infra/target

## Назначение

Инфраструктура взаимодействия с целевой системой (REST API). Реализует порты `RequestExecutorProtocol` и `TargetPagedReaderProtocol`. Обеспечивает retry, fault classification, транспортную компиляцию и provider-специфическую аутентификацию.

## Структура

| Подпапка/файл | Назначение |
|---|---|
| `driver.py` | `TargetDriver[TCompiledRequest]` (Protocol), `DriverResponse`, `DriverError`, `infer_response_payload_format` |
| `core/` | `TargetGateway`, `TargetKernel`, `TargetRuntime`, factory, registry |
| `core/engines/` | `TargetRetryEngine`, `TargetResultBuilder`, `TargetFaultHandler`, `TargetErrorNormalizer`, `TargetSafeLogger` |
| `transports/http/` | `httpx`-транспорт: `request_builder`, `request_once`, `paging`, `normalizer`, `compiler` |
| `providers/` | Фабрика провайдеров |
| `providers/ankey_rest/` | Ankey-специфичная реализация: driver, auth, mutations |

## Поток выполнения

```
RequestSpec → TargetGateway.execute()
  → TargetKernel (resolve operation)
  → TargetDriver (send HTTP)
  → TargetFaultHandler (classify error)
  → TargetRetryEngine (retry decision)
  → TargetResultBuilder (build ExecutionResult)
```

## Зависимости

**Зависит от:** `domain/ports/target/`, `domain/target_dsl/`, `domain/diagnostics/`, `httpx`, `tenacity`.  
**Используется:** `usecases/import_apply_service.py`, `usecases/cache_refresh_service.py`.
