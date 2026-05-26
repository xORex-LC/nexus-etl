# connector/domain/ports/secrets

## Назначение

Интерфейсы для работы с vault секретов.

## Порты

| Файл | Порт | Назначение |
|---|---|---|
| `provider.py` | `SecretProviderProtocol` | Чтение секрета по ключу (dataset, field, row_id, …) |
| `provider.py` | `SecretStoreProtocol` | Запись пачки секретов (`put_many`) |
| `cipher.py` | `SecretCipherPort` | Шифрование/дешифрование DEK |
| `key_provider.py` | `KeyProvider` / `VaultMasterKey` | Получение мастер-ключа vault |
| `repository.py` | `SecretVaultRepositoryPort` | CRUD vault-записей в хранилище |
| `locator.py` | `Locator` | Разрешение ссылки на секрет по row_id / match_key |

## Реализация

→ `infra/secrets/` (`SqliteVaultRepository`, `CompositeSecretProvider`, `FernetEnvelopeCipher`)
