# connector/domain/transform/providers

## Назначение

Runtime-реестр провайдеров для стадии enrich. Провайдер — callable, который принимает ключ и контекст, возвращает данные (из кэша или справочника).

## Файлы

| Файл | Назначение |
|---|---|
| `registry.py` | `ProviderGateway` — реестр lookup и exists провайдеров по имени; `with_defaults()` регистрирует: `cache.by_field`, `cache.exists_by_field`, `dictionary.by_key`, `dictionary.canonicalize`, `dictionary.exists_by_key`; здесь же живут helper-ы для canonicalized cache lookup/exists |

## Зарегистрированные провайдеры

| Имя DSL | Тип | Источник |
|---|---|---|
| `cache.by_field` | lookup | `EnrichLookupPort` (SQLite кэш) |
| `cache.exists_by_field` | exists | `EnrichLookupPort` |
| `dictionary.by_key` | lookup | `DictionaryProviderPort` |
| `dictionary.canonicalize` | lookup | `DictionaryProviderPort` |
| `dictionary.exists_by_key` | exists | `DictionaryProviderPort` |

## Зависимости

**Зависит от:** `domain/ports/cache/roles.py`, `domain/ports/transform/dictionaries.py`.  
**Используется:** `domain/transform/enrich/enricher_core.py`, `domain/transform_dsl/compilers/enrich.py`.
