# connector/delivery/cli/runtime

## Назначение

Lifecycle-оркестрация выполнения CLI-команды: инициализация → вызов handler → финализация → shutdown. Изолирует команды от деталей запуска: логирование, создание `run_id`, запись отчёта, обработка `SettingsLoadError`.

## Файлы

| Файл | Назначение |
|---|---|
| `contracts.py` | `CommandHandler` (Protocol) — явный контракт `(ctx, opts, sink) → CommandResult`; `NullReportSink` — no-op для режимов без отчёта |
| `orchestrator.py` | `CommandOrchestrator.run(handler, opts)` — полный lifecycle: создаёт run_id, инициализирует логгер, вызывает handler, пишет report, логирует итог |
| `topology_bootstrap.py` | `TopologyBootstrapStep` — pre-handler topology bootstrap, short-circuit и runtime binding для planning pipeline |
| `result_adapter.py` | Адаптирует legacy-форматы результатов в единый `CommandResult` |
| `result_mapper.py` | Маппит `CommandResult` → report events (`SetStatusEvent`, `SetRowCountersEvent`) |

## Зависимости

**Зависит от:** `domain/reporting/`, `domain/diagnostics/`, `domain/ports/topology`, `config/`, `infra/logging/`, `infra/topology`, `common/`.  
**Используется:** каждой командой через `delivery/cli/containers.py`.

## Контракт

Каждый CLI-handler должен реализовывать `CommandHandler`:
```python
def __call__(self, ctx: BoundCommandContext, opts: Any, sink: IReportSink) -> CommandResult | None
```
