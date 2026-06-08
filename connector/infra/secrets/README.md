# connector/infra/secrets

## Назначение

Инфраструктура хранения и управления секретами. Реализует vault на базе SQLite с Fernet-шифрованием и Argon2id key derivation.

## Структура

| Подпапка/файл | Назначение |
|---|---|
| `sqlite/` | `SqliteVaultRepository` — CRUD зашифрованных записей (секреты, DEK, probe) |
| `management/` | `AdminPasswordGate` — проверка admin-пароля через Argon2id |
| `fernet_envelope_cipher.py` | `FernetEnvelopeCipher` — реализует `SecretCipherPort`: wrap/unwrap DEK через Fernet |
| `composite_provider.py` | `CompositeSecretProvider` — chain-of-responsibility: ENV → file → prompt |
| `dict_provider.py` | `DictSecretProvider` — in-memory provider (для тестов) |
| `prompt_provider.py` | `PromptSecretProvider` — интерактивный ввод секрета; умеет уважать `InteractiveIoGate`, чтобы prompt не зеркалировался обратно в observability console |
| `unseal.py` | `VaultUnsealService` — Argon2id KDF, создание и верификация master key по probe |

## Иерархия ключей

```
admin password → Argon2id → master key → wrap/unwrap DEK → encrypt/decrypt secret
```

## Зависимости

**Зависит от:** `infra/sqlite/engine.py`, `domain/ports/secrets/`, `domain/secrets/models.py`, `cryptography`, `argon2-cffi`.  
**Используется:** `delivery/cli/containers.py` (`VaultContainer`, `VaultAdminPasswordGate`) и interactive secret lookup paths.
