# connector/infra/logging

## Назначение

Настройка структурированного логирования на основе `structlog`. Создаёт per-command логгеры с автоматическим инжектированием `runId` и `component`.

## Файлы

| Файл | Назначение |
|---|---|
| `setup.py` | `create_command_logger(...)` → `(logger, log_file_path)`; file logger + optional console mirror на original stderr; `EnsureFieldsFilter`, `StdStreamToLogger`, `TeeStream` |
| `topology.py` | `LegacyLogEventSink` — bridge `TopologyEventSink` → текущий stdlib command logger (`comp=topology`) |

## Формат лога

```
%(asctime)s %(levelname)s runId=%(runId)s comp=%(component)s msg=%(message)s
```

Файл лога: `{log_dir}/{command_name}_{run_id}.log`

## Зависимости

**Зависит от:** `structlog`, stdlib `logging`.  
**Используется:** `delivery/cli/runtime/orchestrator.py`.
