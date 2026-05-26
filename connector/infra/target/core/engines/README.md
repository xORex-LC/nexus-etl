# connector/infra/target/core/engines

## Назначение

Специализированные движки ядра target: каждый отвечает за одну задачу в цикле execute.

## Файлы

| Файл | Класс | Назначение |
|---|---|---|
| `retry_engine.py` | `TargetRetryEngine` | Exponential backoff + jitter (tenacity); `can_retry(retries_used)`, `sleep_before_retry(n)` |
| `fault_handler.py` | `TargetFaultHandler` | `from_driver_error()` → `NormalizedFault` + `ResolvedRetryAction`; редактирует credentials в error details |
| `result_builder.py` | `TargetResultBuilder` | Строит `ExecutionResult` из успешного `DriverResponse` или финальной ошибки |
| `error_normalizer.py` | `TargetErrorNormalizer` | HTTP status → `FaultKind` → `SystemErrorCode` |
| `safe_logging.py` | `TargetSafeLogger` | Логирует запрос/ответ с redact секретных полей |

## Зависимости

**Зависит от:** `tenacity`, `domain/diagnostics/policies.py`, `domain/ports/target/execution.py`.
