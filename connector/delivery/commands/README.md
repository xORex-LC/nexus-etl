# connector/delivery/commands

## Назначение

Обработчики отдельных CLI-команд. Каждый файл реализует `CommandHandler` для одной команды. Команды только оркестрируют: получают зависимости из контекста, вызывают usecase, отдают результат в sink.

## Команды

| Файл | CLI-команда |
|---|---|
| `mapping.py` | `nexus mapping` |
| `normalize.py` | `nexus normalize` |
| `enrich.py` | `nexus enrich` |
| `match.py` | `nexus match` |
| `resolve.py` | `nexus resolve` |
| `import_plan.py` | `nexus import plan` |
| `import_apply.py` | `nexus import apply --plan <path>` |
| `cache_refresh.py` | `nexus cache refresh` |
| `cache_clear.py` | `nexus cache clear` |
| `cache_status.py` | `nexus cache status` |
| `vault_management.py` | `nexus vault-management {init,status,rotate,rewrap}` |
| `common.py` | Общие утилиты для команд |
| `topology_runtime.py` | Handler-scope helper для topology provider wiring в planning pipeline composition |

## Зависимости

**Зависит от:** `usecases/`, `domain/reporting/`, `delivery/cli/runtime/contracts.py`.  
**Используется:** `delivery/cli/app.py` (регистрация в Typer).

## Правило

Файл команды не содержит бизнес-логики. Его задача: взять зависимости из `BoundCommandContext`, вызвать usecase, передать результат в `IReportSink`. Никаких прямых вызовов `infra.*`.
