# connector/infra

## Назначение

Адаптеры к внешним системам. Реализует порты из `domain/ports/`, связывая бизнес-логику с конкретными технологиями: SQLite, HTTP, CSV, Fernet.

**Правило слоя:** `infra` зависит от `domain`, но `domain` никогда не импортирует из `infra`.

## Структура

| Подпапка | Что реализует |
|---|---|
| `sqlite/` | `SqliteEngine` — базовый адаптер SQLite (транзакции, WAL, pragmas) |
| `cache/` | `SqliteCacheGateway` + роли, репозиторий, бэкенды — реализация `CacheAdminPort`, `EnrichLookupPort` и др. |
| `identity/` | `SqliteIdentityRepository`, `SqlitePendingLinksRepository` |
| `secrets/` | `SqliteVaultRepository`, `FernetEnvelopeCipher`, `CompositeSecretProvider` |
| `target/` | `TargetGateway`, `TargetKernel`, HTTP-транспорт, Ankey-провайдер |
| `dictionaries/` | `PolarsDictionaryProvider`, `CsvDictionaryLoader` |
| `sources/` | `CsvSourceReader` (polars-бэкенд) |
| `polars/` | Shared Polars adapters для vectorized исполнения transport-neutral domain contracts |
| `topology/` | `SqliteTopologyTargetReader` — cache-backed adapter для target topology read seam |
| `logging/` | `create_command_logger()`, `EnsureFieldsFilter` |
| `artifacts/` | `PlanReader`, `PlanWriter`, `ReportRenderer` |

## Зависимости

**Зависит от:** `domain/ports/`, `domain/models.py`, `domain/diagnostics/`.  
**Внешние библиотеки:** `sqlite3`, `httpx`, `polars`, `cryptography`, `argon2-cffi`, `structlog`.  
**Используется:** `usecases/`, `delivery/cli/containers.py`.
