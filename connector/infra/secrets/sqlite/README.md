# connector/infra/secrets/sqlite

## Назначение

SQLite-реализация vault-репозитория. Хранит зашифрованные секреты, DEK (Data Encryption Key) и probe-запись для верификации master key.

## Файлы

| Файл | Назначение |
|---|---|
| `schema.py` | Определения таблиц: `vault_secrets`, `vault_dek`, `vault_probe`, `vault_management_meta` |
| `repository.py` | `SqliteVaultRepository` — реализует `SecretVaultRepositoryPort`: `put_many()`, `get_by_locator()`, `get_dek()`, `put_dek()`, `get_probe()`, `put_probe()`, транзакции `BEGIN IMMEDIATE` |

## Стратегия поиска секрета

1. Поиск по `match_key` + `run_id` (run-specific)
2. Fallback: по `locator_hash` + `locator_version` (cross-run)

## Зависимости

**Зависит от:** `infra/sqlite/engine.py`, `domain/secrets/models.py`, `domain/ports/secrets/repository.py`.  
**Используется:** `infra/secrets/composite_provider.py`, `usecases/management/vault/usecase.py`.
