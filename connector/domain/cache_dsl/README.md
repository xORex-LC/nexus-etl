# connector/domain/cache_dsl

## Назначение

DSL декларативных политик кэша. Описывает через YAML: когда обновлять кэш, как обнаруживать drift, как очищать и синхронизировать данные с целевой системой.

## Файлы

| Файл | Назначение |
|---|---|
| `specs.py` | Pydantic-модели: `CacheDatasetSpec`, `CacheSyncSpec`, `CacheRefreshSpec`, `CacheDriftSpec`, `SoftDeleteRuleSpec`, `CacheProjectionRuleSpec`, `ValueExprSpec` |
| `compiler.py` | `CacheDslCompiler` — компилирует `CacheDatasetSpec` в `CacheSpec` (используемую `GenericCacheHandler`) |
| `loader.py` | Загрузка YAML cache-спек из `datasets/registry.yaml` |

## Зависимости

**Зависит от:** `domain/dsl/engine.py` (для `ValueExprSpec` — DSL-выражения в projection rules), `domain/ports/cache/models.py`, `pydantic`.  
**Используется:** `infra/cache/sync/dsl_adapter.py`, `domain/cache_core/`.
