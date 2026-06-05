# connector/delivery/cli/runtime

## Назначение

Lifecycle-оркестрация выполнения CLI-команды: инициализация → вызов handler → финализация → shutdown. Изолирует команды от деталей запуска: observability wiring, contextvars correlation, topology bootstrap, запись отчёта и обработка runtime/config ошибок.

## Файлы

| Файл | Назначение |
|---|---|
| `contracts.py` | `CommandHandler` (Protocol) — явный контракт `(ctx, opts, sink) → CommandResult`; `NullReportSink` — no-op для режимов без отчёта |
| `orchestrator.py` | Полный lifecycle: резолвит `ServiceComponent`, инициализирует structlog runtime через DI, bind/clear contextvars, запускает sweeper, вызывает handler, пишет component-aware report artifact |
| `topology_bootstrap.py` | `TopologyBootstrapStep` — pre-handler topology bootstrap, source validation, short-circuit и runtime binding для planning pipeline |
| `result_adapter.py` | Адаптирует legacy-форматы результатов в единый `CommandResult` |
| `result_mapper.py` | Маппит `CommandResult` → report events (`SetStatusEvent`, `SetRowCountersEvent`) |

## Зависимости

**Зависит от:** `domain/reporting/`, `domain/diagnostics/`, `domain/ports/topology`, `config/`, `infra/logging/`, `infra/artifacts`, `infra/observability`, `common/`.
**Используется:** каждой командой через `delivery/cli/containers.py`.

## Контракт

Каждый CLI-handler должен реализовывать `CommandHandler`:
```python
def __call__(self, ctx: BoundCommandContext, opts: Any, sink: IReportSink) -> CommandResult | None
```
