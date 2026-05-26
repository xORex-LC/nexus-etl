# connector/infra/logging

## Назначение

Настройка структурированного логирования на основе `structlog`. Создаёт per-command логгеры с автоматическим инжектированием `runId` и `component`.

## Файлы

| Файл | Назначение |
|---|---|
| `setup.py` | `create_command_logger(command_name, log_dir, run_id, log_level)` → `(logger, log_file_path)`; `EnsureFieldsFilter` — инжектирует `runId`/`component` в каждый `LogRecord`; `StdStreamToLogger`, `TeeStream` — перехват stdout/stderr |

## Формат лога

```
%(asctime)s %(levelname)s runId=%(runId)s comp=%(component)s msg=%(message)s
```

Файл лога: `{log_dir}/{command_name}_{run_id}.log`

## Зависимости

**Зависит от:** `structlog`, stdlib `logging`.  
**Используется:** `delivery/cli/runtime/orchestrator.py`.
