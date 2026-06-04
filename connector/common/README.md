# connector/common

## Назначение

Кросс-слойные утилиты без бизнес-логики. Используются во всех слоях приложения.

## Содержимое

| Файл | Что делает |
|---|---|
| `observability.py` | `ServiceComponent`, `ComponentIdentity`, `ObservabilityLayout` и policy/value-objects для observability-раскладки |
| `run_id.py` | `generate_run_id()` — UUID4 для идентификации прогона |
| `runtime_paths.py` | `RuntimePaths`, `RuntimePathOverrides` — typed resolver корневых runtime-путей (datasets, cache, logs, reports, plans и т.д.); `@lru_cache` для синглтон-инстанса |
| `sanitize.py` | `mask_secret(value)` → `"***"` и `is_masked_secret()` — безопасный вывод секретов в логах |
| `time.py` | `get_utc_now_iso()`, `get_duration_ms()` — временны́е утилиты |

## Зависимости

**Зависит от:** стандартная библиотека Python (`uuid`, `pathlib`, `functools`, `datetime`, `enum`).
**Используется:** всеми слоями — `domain`, `infra`, `usecases`, `delivery`.

## Правило

Файлы в этой папке не должны импортировать ничего из `connector.*` — только stdlib.
