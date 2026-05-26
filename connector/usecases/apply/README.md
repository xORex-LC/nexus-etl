# connector/usecases/apply

## Назначение

Модели результатов и порт телеметрии для use case `import apply`. Содержит DTO, которые `ImportApplyService` возвращает, и интерфейс для per-item логирования.

## Файлы

| Файл | Назначение |
|---|---|
| `models.py` | `ApplySummary` (created/updated/failed/skipped/error_stats), `ApplyItemOutcome` (per-item результат), `ApplyResult` (полный результат apply) |
| `telemetry.py` | `ApplyTelemetrySink` (Protocol) — `on_item_ok/warn/error`, `on_summary`; `NullApplyTelemetrySink` — no-op реализация |

## Зависимости

**Зависит от:** `domain/models.py`, `domain/diagnostics/policies.py`, `domain/planning/record_ref.py`.  
**Используется:** `usecases/import_apply_service.py`, `delivery/telemetry/apply_logging_sink.py`, `delivery/presenters/apply_report_presenter.py`.
