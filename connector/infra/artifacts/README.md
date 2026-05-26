# connector/infra/artifacts

## Назначение

Сериализация и десериализация runtime-артефактов: plan (JSON) и отчётов (JSON/text).

## Файлы

| Файл | Назначение |
|---|---|
| `plan_writer.py` | `PlanWriter.write(plan, path)` — сериализует `Plan` → JSON-файл |
| `plan_reader.py` | `PlanReader.read(path)` → `Plan` — десериализует JSON-файл в доменную модель; валидирует структуру |
| `report_renderer.py` | `ReportRenderer` — реализует `IReportSink`; записывает `ReportEnvelope` в JSON (и опционально текст) |

## Файлы в runtime

| Путь | Содержимое |
|---|---|
| `var/plan_<run_id>.json` | Сериализованный `Plan` |
| `reports/<command>_<run_id>.json` | `ReportEnvelope` |

## Зависимости

**Зависит от:** `domain/planning/plan_models.py`, `domain/reporting/models.py`, `domain/reporting/sink.py`.  
**Используется:** `delivery/commands/import_plan.py`, `delivery/commands/import_apply.py`, `delivery/cli/runtime/orchestrator.py`.
