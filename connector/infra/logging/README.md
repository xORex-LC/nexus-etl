# connector/infra/logging

## Назначение

Логирующая инфраструктура в переходном состоянии между legacy stdlib command logger и новой observability-моделью на `structlog`.

## Файлы

| Файл | Назначение |
|---|---|
| `runtime.py` | `StructuredLoggingRuntime`, `DailySizeRotatingFileHandler`, `bind_observability_context()` — новый structlog runtime с stderr/file sinks и stdlib bridge |
| `redaction.py` | `LogRedactionEngine` — единый redaction engine для structlog event_dict, foreign-логов, traceback и stream-capture |
| `setup.py` | Legacy façade: `create_command_logger(...)`, `EnsureFieldsFilter`, `log_event`; временно сохраняет старые call-sites до switch-over |
| `topology.py` | `LegacyLogEventSink` — bridge `TopologyEventSink` → текущий stdlib command logger (`comp=topology`) |

## Переходный статус

- Legacy путь всё ещё пишет в `{log_dir}/{command_name}_{run_id}.log`.
- Новый runtime пишет JSON в stderr и daily+size файлы через `ObservabilityLayout`.

## Зависимости

**Зависит от:** `structlog`, stdlib `logging`, `common/observability.py`.
**Используется:** `delivery/cli/runtime/orchestrator.py`, `delivery/cli/stream_capture.py`, следующие фазы observability migration.
