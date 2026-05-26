# connector/infra/cache/backends/sqlite

## Назначение

SQLite-бэкенд кэша. Содержит `GenericCacheHandler` — универсальный обработчик, создающий и заполняющий таблицы кэша на основе `CacheSpec`.

## Файлы

| Файл | Назначение |
|---|---|
| `handlers/generic_handler.py` | `GenericCacheHandler` — `ensure_schema()`, `upsert()`, `find()`, `clear()`, `rebuild()`; маппинг Python-типов → SQLite-типы (`string→TEXT`, `int→INTEGER`, `bool→INTEGER`, `json→TEXT`) |
| `handlers/base.py` | Базовый класс / интерфейс handler |

## Зависимости

**Зависит от:** `infra/sqlite/engine.py`, `domain/ports/cache/models.py` (`CacheSpec`, `FieldSpec`).  
**Используется:** `infra/cache/repository/cache_repository.py`.
