# connector/infra/cache/roles

## Назначение

Реализации ролевых портов кэша. Каждый файл реализует один порт из `domain/ports/cache/roles.py` — адаптируя репозиторий под конкретный use case.

## Файлы

| Файл | Реализует порт |
|---|---|
| `admin.py` | `CacheAdminPort` — полный admin-доступ (upsert, rebuild, clear, meta) |
| `enrich_lookup.py` | `EnrichLookupPort` — read-only поиск для enrich стадии |
| `planning_runtime.py` | `MatchRuntimePort` + `ResolveRuntimePort` — runtime state для match/resolve |
| `apply_runtime.py` | `ApplyRuntimePort` — post-apply синхронизация identity и pending |
| `cache_refresh.py` | `CacheRefreshPort` — composite порт для refresh операций |
| `topology_read.py` | `TopologyCacheReadPort` — read-only выборка adjacency-строк/meta/count для topology bootstrap |
| `bundle.py` | `CacheRoleBundle` — агрегирует все роли для удобной инициализации в DI |

## Зависимости

**Зависит от:** `infra/cache/repository/`, `domain/ports/cache/roles.py`.  
**Используется:** `delivery/cli/containers.py` (`CacheContainer`).
