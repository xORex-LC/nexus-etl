# connector/domain/ports/cache

## Назначение

Ролевые интерфейсы кэша. Каждый порт предоставляет ровно те операции, которые нужны конкретной стадии — без избыточных прав.

## Порты

| Порт | Файл | Кто использует | Операции |
|---|---|---|---|
| `CacheAdminPort` | `roles.py` | `usecases/cache_*` | `transaction`, `upsert`, `count`, `clear`, `rebuild`, `get_meta`, `set_meta` |
| `EnrichLookupPort` | `roles.py` | `EnricherCore` | `find`, `find_one`, `read_all` (lookup + optional canonicalized scan path) |
| `MatchRuntimePort` | `roles.py` | `MatchCore` | `find`, `set/get runtime_state`, `clear_scope` |
| `ResolveRuntimePort` | `roles.py` | `ResolveCore` | `add_pending`, `list_pending_rows`, `mark_resolved`, `sweep_expired`, `purge_stale` |
| `ApplyRuntimePort` | `roles.py` | `ImportApplyService` | `upsert_identity`, `list_pending_for_key`, `mark_resolved` |
| `TopologyCacheReadPort` | `roles.py` | `SqliteTopologyTargetReader` (topology bootstrap) | `read_all`, `get_meta`, `count` (только чтение) |

## Модели

| Файл | Назначение |
|---|---|
| `models.py` | `CacheSpec`, `FieldSpec` — описание схемы таблицы кэша |

## Реализация

→ `infra/cache/roles/`
