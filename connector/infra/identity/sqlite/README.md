# connector/infra/identity/sqlite

## Назначение

SQLite-реализация репозиториев идентичности и pending-ссылок.

## Файлы

| Файл | Назначение |
|---|---|
| `schema.py` | Определения таблиц: `identity` (match_key → target_id, run_id, timestamps), `pending_links` (match_key, status, attempts, expires_at) |
| `identity_repository.py` | `SqliteIdentityRepository` — `upsert_identity()`, `find_by_key()`, `find_by_target_id()` |
| `pending_links_repository.py` | `SqlitePendingLinksRepository` — `add_pending()`, `list_pending()`, `mark_resolved()`, `sweep_expired()`, `purge_stale()` |

## Статусы pending_links

`PENDING` → `RESOLVED` / `CONFLICT` / `EXPIRED`

## Зависимости

**Зависит от:** `infra/sqlite/engine.py`.  
**Используется:** `infra/cache/roles/planning_runtime.py`, `infra/cache/roles/apply_runtime.py`.
