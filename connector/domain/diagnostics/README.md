# connector/domain/diagnostics

## Назначение

Централизованная система диагностики. Определяет таксономию ошибок, каталог кодов, политику остановки пайплайна и вспомогательные исключения.

## Файлы

| Файл | Назначение |
|---|---|
| `catalog.py` | `ErrorCatalog` — реестр `CatalogEntry(code, system_code, severity)`; `build_core_catalog()` создаёт каталог из `core_catalog.py` |
| `core_catalog.py` | Все ~60 кодов ошибок: `DSL_OP_FAILED`, `MATCH_CONFLICT`, `RESOLVE_MAX_ATTEMPTS`, `SECRET_REQUIRED`, `CACHE_ERROR`, `SINK_HTTP_ERROR` и др. |
| `policies.py` | `SystemErrorCode` — таксономия: `IO_ERROR`, `DATA_INVALID`, `INTERNAL_ERROR`, `CONFLICT`, `CACHE_ERROR`, `INFRA_UNAVAILABLE`, `INFRA_TIMEOUT`, `AUTH_*`; `StopPolicy` — фатальные vs recoverable коды |
| `exceptions.py` | `DiagnosticBoundaryError`, `MissingRequiredSecretError` (с dataset/field/row_id/target_id) |
| `boundary.py` | `@diagnostic_boundary` — декоратор для оборачивания unexpected exceptions на стадийных границах |
| `translator.py` | `ExecutionResult` → `DiagnosticItem` (для target-ошибок) |
| `command_result.py` | `CommandResult` — итоговый статус команды |
| `context.py` | Контекст диагностики для команды |

## Добавление нового кода ошибки

1. `core_catalog.py` → `build_core_catalog()`: `CatalogEntry("MY_CODE", SystemErrorCode.DATA_INVALID, severity=ERROR)`
2. Создавать ошибку через: `DiagnosticItem.from_catalog(catalog, stage, code="MY_CODE", field=..., record_ref=...)`

## Зависимости

**Зависит от:** `domain/models.py`.  
**Используется:** всем доменным кодом, `infra/target/`, `usecases/`.
