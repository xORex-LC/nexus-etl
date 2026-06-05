# connector/infra/artifacts

## Назначение

Сериализация и десериализация runtime-артефактов: `plan` и observability-отчётов.

Директория уже обслуживает активную component-aware раскладку DEC-002. Legacy
symbols и сигнатуры оставлены как стабилизационный слой для обратной
совместимости, но боевой orchestration path пишет через layout-aware writers.

## Файлы

| Файл | Назначение |
|---|---|
| `_atomic_json.py` | Общий helper атомарной записи JSON через temp-файл и `os.replace()` |
| `plan_writer.py` | `write_plan_file_with_layout(...)` — основной writer планов; `write_plan_file(...)` оставлен как legacy-совместимый symbol |
| `plan_reader.py` | `PlanReader.read(path)` → `Plan` — десериализует JSON-файл в доменную модель; валидирует структуру |
| `report_renderer.py` | `JsonReportRenderer` — основной `render_with_layout(...)` для component-aware report artifacts; `render(...)` сохранён для legacy compatibility |

## Файлы в runtime

| Путь | Содержимое |
|---|---|
| `reports/<component>/<datetime>_<component>.json` | Новый component-aware report artifact |
| `var/plans/<component>/<datetime>_<component>.json` | Новый component-aware plan artifact |

## Зависимости

**Зависит от:** `domain/planning/plan_models.py`, `domain/reporting/models.py`, `domain/reporting/sink.py`.  
**Используется:** `delivery/commands/import_plan.py`, `delivery/commands/import_apply.py`, `delivery/cli/runtime/orchestrator.py`, e2e/integration tests plan→apply.
