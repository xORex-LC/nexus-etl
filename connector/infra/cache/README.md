# connector/infra/cache

## Назначение

SQLite-реализация всех cache-портов. Хранит данные целевой системы локально для работы стадий match, enrich и resolve без прямых запросов к API.

## Структура

| Подпапка/файл | Назначение |
|---|---|
| `cache_gateway.py` | `SqliteCacheGateway` — единый фасад; объединяет cache engine + identity engine + pending engine; предоставляет `.transaction()` |
| `repository/` | `SqliteCacheRepository` — CRUD: `upsert`, `find`, `find_one`, `count`, `clear`, `rebuild`, `get_meta` / `set_meta` |
| `roles/` | Реализации портов: `CacheAdminRole`, `EnrichLookupRole`, `MatchRuntimeRole`, `ResolveRuntimeRole`, `ApplyRuntimeRole`, `CacheRefreshRole` |
| `backends/sqlite/` | `GenericCacheHandler` — универсальный handler для любого датасета на основе `CacheSpec` |
| `backends/sqlite/handlers/` | `base.py` — базовый класс handler; `generic_handler.py` |
| `sync/` | `DslCacheSyncAdapter` — DSL-управляемый адаптер синхронизации (`CacheSyncAdapterProtocol`) |
| `handlers/` | (зарезервировано) |

## Файлы кэша в runtime

| Файл | Содержимое |
|---|---|
| `var/cache/cache.sqlite3` | Данные датасетов (таблицы по одной на датасет) |
| `var/cache/identity.sqlite3` | Identity-индекс + pending_links |

## Зависимости

**Зависит от:** `infra/sqlite/engine.py`, `domain/ports/cache/`, `domain/cache_dsl/specs.py`.  
**Используется:** `delivery/cli/containers.py` (`CacheContainer`).
