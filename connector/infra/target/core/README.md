# connector/infra/target/core

## Назначение

Transport-agnostic ядро исполнения запросов к целевой системе: gateway, kernel и factory. Не знает о HTTP-деталях — делегирует транспорту через `TargetDriver`.

## Файлы

| Файл | Назначение |
|---|---|
| `gateway.py` | `TargetGateway` — оркестрирует execute/iter_pages с retry: вызывает driver, fault handler, retry engine, result builder |
| `kernel.py` | `TargetKernel` — O(1) lookup операций; `classify_fault()` → `FaultKind`; `resolve_retry_action()` → `RETRY|ESCALATE|FAIL` |
| `runtime.py` | `TargetRuntime` — объединяет kernel + driver + gateway в единый runtime |
| `factory.py` | `TargetProviderFactory` — создаёт runtime по имени провайдера из `TargetSpec` |
| `registry.py` | Реестр зарегистрированных провайдеров |
| `spec_models.py` | `TargetSpec`, `OperationSpec`, `FaultRule`, `RetryRule`, `RetryConfig` |
| `transport_compiler.py` | Компилирует `OperationSpec` → транспортный формат |
| `models.py` | `Operation`, `TargetRequest` |
| `mutations.py` | Мутации операций (переопределение дефолтов) |
| `engines/` | Движки: retry, fault handler, result builder, error normalizer, safe logger |

## Зависимости

**Зависит от:** `infra/target/driver.py`, `domain/ports/target/execution.py`, `domain/diagnostics/`, `domain/target_dsl/`.  
**Используется:** `infra/target/providers/`.
