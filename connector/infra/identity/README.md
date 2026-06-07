# connector/infra/identity

## Назначение

SQLite-хранилище идентификаторов и pending-ссылок. Хранит информацию о сопоставлении source-записей с target-идентификаторами между прогонами.

## Структура

| Подпапка | Назначение |
|---|---|
| `sqlite/` | `SqliteIdentityRepository`, `SqlitePendingLinksRepository`, `schema.py` |

## Файлы SQLite

Данные хранятся в `var/cache/identity.sqlite3` (отдельный файл от `cache.sqlite3`).

## Зависимости

**Зависит от:** `infra/sqlite/engine.py`.  
**Используется:** `infra/cache/roles/planning_runtime.py`, `infra/cache/roles/apply_runtime.py`.
