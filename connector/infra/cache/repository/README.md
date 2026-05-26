# connector/infra/cache/repository

## Назначение

Data Access Layer кэша. Инкапсулирует SQL-операции с таблицами кэша, не зная об операционных ролях.

## Файлы

| Файл | Назначение |
|---|---|
| `cache_repository.py` | `SqliteCacheRepository` — `upsert(dataset, row)` → `UpsertResult.INSERTED|UPDATED`; `find(dataset, filters)`, `find_one`, `count`, `clear`, `rebuild`, `get_meta`, `set_meta`, `reset_meta` |

## Зависимости

**Зависит от:** `infra/sqlite/engine.py`, `infra/cache/backends/sqlite/handlers/`, `domain/ports/cache/models.py`.  
**Используется:** `infra/cache/roles/`.
