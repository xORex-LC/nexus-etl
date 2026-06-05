# connector/infra/artifacts

## Назначение

Сериализация и десериализация runtime-артефактов: `plan` и отчётов observability.

Директория удерживает additive-переход между legacy-путями и новой
component-aware раскладкой DEC-002: старые symbols и сигнатуры остаются
доступными, а layout-aware writers добавляются рядом и будут переключены
оркестратором на следующем этапе.

## Файлы

| Файл | Назначение |
|---|---|
| `_atomic_json.py` | Общий helper атомарной записи JSON через temp-файл и `os.replace()` |
| `plan_writer.py` | Legacy `write_plan_file(...)` и additive `write_plan_file_with_layout(...)` для сериализации import plan |
| `plan_reader.py` | `PlanReader.read(path)` → `Plan` — десериализует JSON-файл в доменную модель; валидирует структуру |
| `report_renderer.py` | `JsonReportRenderer` — legacy `render(...)` и additive `render_with_layout(...)` для `ReportEnvelope` |

## Файлы в runtime

| Путь | Содержимое |
|---|---|
| `reports/<command>_<run_id>.json` | Legacy `ReportEnvelope` до switch-over orchestration |
| `reports/<component>/<datetime>_<component>.json` | Новый component-aware report artifact |
| `reports/plan_import_<run_id>.json` | Legacy import plan до switch-over orchestration |
| `var/plans/<component>/<datetime>_<component>.json` | Новый component-aware plan artifact |

## Зависимости

**Зависит от:** `domain/planning/plan_models.py`, `domain/reporting/models.py`, `domain/reporting/sink.py`.  
**Используется:** `delivery/commands/import_plan.py`, `delivery/commands/import_apply.py`, `delivery/cli/runtime/orchestrator.py`.
