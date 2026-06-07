# connector/domain/reporting/adapters

## Назначение

Адаптеры, преобразующие результаты стадий трансформации в события отчётности. Изолируют domain-модели трансформации от системы reporting.

## Файлы

| Файл | Назначение |
|---|---|
| `stage_result_reporter.py` | `StageResultReporter.process(result, row_ref)` — конвертирует `TransformResult` → `AddItemEvent` + `SetContextEvent`; применяет stage policy по `report_stage` / `report_stages` |
| `payload_sanitizer.py` | `PayloadSanitizer` — маскирует `secret_fields` в `desired_state` перед записью в отчёт |
| `result_policy.py` | `ResultPolicy` — определяет статус итема (OK/FAILED/SKIPPED) по наличию errors/warnings |
| `stats_accumulator.py` | `ExecutionStatsAccumulator` — накапливает статистику выполнения (timing, counts) |

## Зависимости

**Зависит от:** `domain/reporting/events.py`, `domain/reporting/contracts.py`, `domain/transform/core/result.py`.  
**Используется:** `usecases/` (stage usecases передают `StageResultReporter` в стадии).
