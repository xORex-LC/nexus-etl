# connector/infra/cache/backends/sqlite/handlers

## Назначение

Реализации обработчиков SQLite для кэш-бэкенда.

## Файлы

| Файл | Назначение |
|---|---|
| `base.py` | `BaseCacheHandler` — абстрактный базовый класс с интерфейсом `ensure_schema`, `upsert`, `find`, `clear` |
| `generic_handler.py` | `GenericCacheHandler(BaseCacheHandler)` — универсальная реализация поверх `CacheSpec`; динамически создаёт таблицы, индексы и выполняет INSERT OR REPLACE |

## Зависимости

**Зависит от:** `infra/sqlite/engine.py`, `domain/ports/cache/models.py`.
