# connector/domain/ports

## Назначение

Интерфейсы (Python Protocols) для всех внешних зависимостей домена. Определяют контракт взаимодействия между domain/usecases и инфраструктурными адаптерами в `infra/`.

## Структура

| Подпапка | Что определяет |
|---|---|
| `cache/` | Интерфейсы кэша: `CacheAdminPort`, `EnrichLookupPort`, `MatchRuntimePort`, `ResolveRuntimePort`, `ApplyRuntimePort` |
| `target/` | Интерфейсы целевой системы: `RequestExecutorProtocol`, `TargetPagedReaderProtocol`, `ApplyAdapterProtocol` |
| `secrets/` | Интерфейсы vault: `SecretProviderProtocol`, `SecretStoreProtocol`, `SecretCipherPort`, `VaultRepositoryPort` |
| `transform/` | Интерфейсы для источника и справочников: `SourceMapper`, `DictionaryProviderPort` |

## Правило

Порты определяют _что_, не _как_. Каждый порт — минимальный интерфейс для конкретной роли. Реализации — исключительно в `infra/`. Domain знает только о портах.
