# connector/domain/reporting

## Назначение

Event-driven система отчётности. Компоненты эмитируют события — `InMemoryReportContext` их накапливает. По завершении команды `snapshot()` возвращает полный `ReportEnvelope`.

## Структура

| Файл/папка | Назначение |
|---|---|
| `events.py` | Все события: `SetMetaEvent`, `SetContextEvent`, `AddOpEvent`, `AddItemEvent`, `SetRowCountersEvent`, `FinishEvent`, и др. |
| `context.py` | `InMemoryReportContext` — потоковый агрегатор событий; `snapshot()` → `ReportEnvelope` |
| `contracts.py` | `ReportItemStatus` (OK/FAILED/SKIPPED), `ReportContextKey` (CONFIG/RUNTIME/APPLY/…), `ReportOpKey` (CREATE/UPDATE/SKIP/APPLY_FAILED/…) |
| `models.py` | `ReportEnvelope`, `ReportMeta`, `ReportSummary`, `ReportItem`, `ReportDiagnostic` |
| `sink.py` | `IReportSink` — интерфейс записи готового отчёта; `NullReportSink` — no-op |
| `assembler.py` | `ReportAssembler` — конструирует `ReportEnvelope` из финального состояния context |
| `policy.py` | `ReportPolicy` — конфигурация поведения отчёта (лимиты items, фильтры) |
| `diagnostics.py` | `to_report_diagnostics()` — `DiagnosticItem` → `ReportDiagnostic` |
| `adapters/` | `StageResultReporter`, `PayloadSanitizer`, `StatsAccumulator` |

## Как добавить событие в отчёт

1. Счётчик операции: `sink.emit(AddOpEvent(name=ReportOpKey.CREATE, ok=True))`
2. Построчный итем: `sink.emit(AddItemEvent(status=FAILED, row_ref=..., diagnostics=[...]))`
3. Контекст команды: `sink.emit(SetContextEvent(key=ReportContextKey.APPLY, value={...}))`

## Зависимости

**Зависит от:** `domain/models.py`, `domain/diagnostics/`.  
**Используется:** `usecases/`, `delivery/commands/`, `delivery/presenters/`.
