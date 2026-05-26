# connector/delivery/telemetry

## Назначение

Реализации порта `ApplyTelemetrySink` для delivery-слоя. Обеспечивает структурированное per-item логирование во время выполнения apply.

## Файлы

| Файл | Назначение |
|---|---|
| `apply_logging_sink.py` | `LoggingApplyTelemetrySink` — реализует `ApplyTelemetrySink`: логирует `on_item_ok`, `on_item_warn`, `on_item_error`, `on_summary` с полями `runId`, `component`, `dataset`, `op`, `row_id`, `line_no` |

## Зависимости

**Зависит от:** `usecases/apply/telemetry.py` (`ApplyTelemetrySink` Protocol), `domain/models.py`, `domain/diagnostics/policies.py`.  
**Используется:** `delivery/commands/import_apply.py` (передаётся в `ImportApplyService`).

## Связь с портом

`ApplyTelemetrySink` определён в `usecases/apply/telemetry.py`. `LoggingApplyTelemetrySink` — delivery-реализация. `NullApplyTelemetrySink` — no-op для тестов/dry-run.
