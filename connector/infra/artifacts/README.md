# connector/infra/artifacts

## Назначение

Сериализация и десериализация runtime-артефактов: `plan` и observability-отчётов.

Директория обслуживает активную component-aware раскладку DEC-002.

## Файлы

| Файл | Назначение |
|---|---|
| `_atomic_json.py` | Общий helper атомарной записи JSON через temp-файл и `os.replace()` |
| `plan_writer.py` | `write_plan_file_with_layout(...)` — writer планов в component-aware раскладку |
| `plan_reader.py` | `PlanReader.read(path)` → `Plan` — десериализует JSON-файл в доменную модель; валидирует структуру |
| `report_renderer.py` | `JsonReportRenderer.render_with_layout(...)` — writer report artifacts в component-aware раскладку |

## Файлы в runtime

| Путь | Содержимое |
|---|---|
| `reports/<component>/<datetime>_<component>.json` | Новый component-aware report artifact |
| `var/plans/<component>/<datetime>_<component>.json` | Новый component-aware plan artifact |

## Зависимости

**Зависит от:** `domain/planning/plan_models.py`, `domain/reporting/models.py`, `domain/reporting/sink.py`.  
**Используется:** `delivery/commands/import_plan.py`, `delivery/commands/import_apply.py`, `delivery/cli/runtime/orchestrator.py`, e2e/integration tests plan→apply.
