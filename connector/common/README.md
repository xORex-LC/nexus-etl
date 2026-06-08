# connector/common

## Назначение

Кросс-слойные утилиты без бизнес-логики. Используются во всех слоях приложения.

## Содержимое

| Файл | Что делает |
|---|---|
| `interactive_io.py` | `InteractiveIoGate` — process-local gate для временного подавления console/capture mirror во время интерактивных prompt-секций |
| `observability.py` | `ServiceComponent`, `ObservabilityArtifactKind`, `ComponentIdentity`, `ObservabilityLayout` и policy/value-objects для observability-раскладки; layout владеет именованием log/report/plan/ledger артефактов |
| `run_id.py` | `generate_run_id()` и `generate_pipeline_run_id()` — идентификаторы command-run и pipeline-run |
| `runtime_paths.py` | `RuntimePaths`, `RuntimePathOverrides` — typed resolver корневых runtime-путей (datasets, cache, logs, reports, plans и т.д.); `@lru_cache` для синглтон-инстанса |
| `sanitize.py` | `mask_secret(value)` → `"***"` и `is_masked_secret()` — безопасный вывод секретов в логах |
| `time.py` | `get_utc_now_iso()`, `get_duration_ms()` — временны́е утилиты |

## Зависимости

**Зависит от:** stdlib и другие cross-cutting `connector.common.*` модули.
**Используется:** всеми слоями — `domain`, `infra`, `usecases`, `delivery`.

## Правило

Файлы в этой папке не должны импортировать `domain/`, `infra/`, `delivery/` или `usecases/`.
Импорты между `connector.common.*` модулями допустимы, если они сохраняют value-only характер и не тащат инфраструктуру.
