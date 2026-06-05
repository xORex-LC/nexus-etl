# connector/infra/logging

## Назначение

Логирующая инфраструктура observability-модели: `structlog`, stderr JSON, daily+size file sink и legacy bridge для старых `logger.log(..., extra=...)` call-sites.

## Файлы

| Файл | Назначение |
|---|---|
| `runtime.py` | `StructuredLoggingRuntime`, `DailySizeRotatingFileHandler`, `bind_observability_context()` — новый structlog runtime с stderr/file sinks и stdlib bridge |
| `redaction.py` | `LogRedactionEngine` — единый redaction engine для structlog event_dict, foreign-логов, traceback и stream-capture |
| `setup.py` | Legacy façade: `log_event`, `EnsureFieldsFilter`, `DropCapturedStdStreamsFilter`; `create_command_logger(...)` сохранён только для обратной совместимости и точечных legacy-тестов |
| `topology.py` | `LegacyLogEventSink` — bridge `TopologyEventSink` → текущий stdlib command logger (`comp=topology`) |

## Runtime-модель

- CLI orchestration пишет JSON в `stderr` и активный лог в `var/logs/<component>/<YYYY-MM-DD>_<component>.log`.
- Повторные запуски в тот же день дописывают в тот же файл; size-roll создаёт backup-файлы в том же component partition.
- Legacy `create_command_logger(...)` больше не является основным runtime-path.

## Зависимости

**Зависит от:** `structlog`, stdlib `logging`, `common/observability.py`.
**Используется:** `delivery/cli/runtime/orchestrator.py`, `delivery/cli/stream_capture.py`, topology/report/runtime tests.
