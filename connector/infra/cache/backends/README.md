# connector/infra/cache/backends

## Назначение

Реестр и базовые классы бэкендов кэша. Позволяет подключать разные хранилища (сейчас только SQLite).

## Структура

| Подпапка | Назначение |
|---|---|
| `sqlite/` | SQLite-бэкенд: `GenericCacheHandler` — универсальный handler; `handlers/` — base + generic |

## Зависимости

**Зависит от:** `infra/sqlite/`.  
**Используется:** `infra/cache/repository/`.
