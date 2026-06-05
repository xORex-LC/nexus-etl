# connector/delivery/presenters

## Назначение

Форматирование результатов use case'ов в report-события на границе delivery-слоя.

## Файлы

| Файл | Назначение |
|---|---|
| `apply_report_presenter.py` | `ApplyReportPresenter.present(result, sink)` — преобразует `ApplyResult` в серию `IReportSink.emit(...)` вызовов: `AddOpEvent`, `AddItemEvent`, `SetRowCountersEvent`, `SetContextEvent` |
| `observability_presenter.py` | `ObservabilityPresenter` — человекочитаемый stdout-вывод для `maintenance prune` и `obs latest|tail` |

## Зависимости

**Зависит от:** `usecases/apply/models.py` (`ApplyResult`), `domain/reporting/events.py`, `domain/reporting/sink.py`.  
**Используется:** `delivery/commands/import_apply.py`.

## Правило

Presenter только пишет в `IReportSink` — не читает состояние context, не содержит бизнес-логики. Один presenter = один тип результата.
