# connector/infra/cache/sync

## Назначение

DSL-управляемый адаптер синхронизации кэша. Реализует `CacheSyncAdapterProtocol` через `TransformationEngine`, применяя projection rules из `CacheSyncSpec` к сырым данным от target API.

## Файлы

| Файл | Назначение |
|---|---|
| `dsl_adapter.py` | `DslCacheSyncAdapter` — `get_item_key(raw_item)`, `is_deleted(raw_item)`, `map_target_to_cache(raw_item)` — каждый метод выполняет DSL-выражение из spec |

## Поток данных

```
target API response → DslCacheSyncAdapter.map_target_to_cache() → dict → SqliteCacheRepository.upsert()
```

## Зависимости

**Зависит от:** `domain/dsl/engine.py`, `domain/cache_dsl/specs.py`, `datasets/cache_sync.py`.  
**Используется:** `usecases/cache_refresh_service.py`.
