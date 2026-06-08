# connector/infra/logging

## Назначение

Логирующая инфраструктура observability-модели: `structlog`, stderr JSON и daily+size file sink.

## Файлы

| Файл | Назначение |
|---|---|
| `runtime.py` | `StructuredLoggingRuntime`, `DailySizeRotatingFileHandler`, `bind_observability_context()` — structlog runtime с stderr/file sinks, human console text renderer и stdlib bridge для foreign-логов |
| `redaction.py` | `LogRedactionEngine` — единый redaction engine для structlog event_dict, foreign-логов, traceback и stream-capture |
| `topology.py` | `StructlogTopologyEventSink` — bridge `TopologyEventSink` → native structlog logger (`scope=topology`) |

## Runtime-модель

- CLI orchestration пишет JSON в `stderr` и активный лог в `var/logs/<component>/<YYYY-MM-DD>_<component>.log`.
- Повторные запуски в тот же день дописывают в тот же файл; size-roll создаёт backup-файлы в том же component partition.
- CLI call-sites пишут через native structlog `logger.info/warning/error(event, scope=..., **fields)`.
- Во время интерактивных prompt-секций console mirror временно suppress-ится через `InteractiveIoGate`, но файловый sink продолжает писать события.
- `console.format=text` теперь рендерится как операторский однострочный формат вида `[INFO] vault core: Command started ...`; файловый `format=text` остаётся прежним `key=value`.

## Зависимости

**Зависит от:** `structlog`, stdlib `logging`, `common/observability.py`.
**Используется:** `delivery/cli/runtime/orchestrator.py`, `delivery/cli/stream_capture.py`, topology/report/runtime tests.
