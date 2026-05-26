# connector/delivery

## Назначение

Внешний слой приложения. Отвечает за ввод/вывод: разбор CLI-аргументов, инициализацию DI-контейнеров, оркестрацию выполнения команд, форматирование вывода.

**Правило слоя:** delivery знает о всех нижних слоях (`usecases`, `domain`, `infra`), но нижние слои никогда не импортируют из `delivery`.

## Структура

| Подпапка | Назначение |
|---|---|
| `cli/` | Typer-приложение (`app.py`), DI-контейнеры (`containers.py`), runtime orchestration, stage factory |
| `commands/` | Обработчики отдельных CLI-команд (import_plan, import_apply, cache_*, vault_management, mapping, …) |
| `pipelines/` | Lifecycle-aware пайплайн для `import plan` (`PlanningPipeline`) |
| `presenters/` | Форматирование `ApplyResult` → report events (`ApplyReportPresenter`) |
| `telemetry/` | `LoggingApplyTelemetrySink` — структурированное per-item логирование apply |

## Зависимости

**Зависит от:** всех слоёв (`usecases`, `domain`, `infra`, `config`, `datasets`, `common`).  
**Не импортируется** никем внутри `connector.*`.

## Точка входа

`connector/main.py` → `delivery/cli/app.py:app` (Typer), команда `nexus`.
