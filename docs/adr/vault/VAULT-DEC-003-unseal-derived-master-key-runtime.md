# VAULT-DEC-003: Unseal-derived master key в runtime памяти

> **Статус**: Принято
> **Дата принятия**: 2026-04-28
> **Решает проблему**: [VAULT-PROBLEM-003](./VAULT-PROBLEM-003-master-key-at-rest-and-unseal-runtime.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

После VAULT-DEC-002 vault получил envelope encryption и управляемый lifecycle master keyring, но master key material хранился в managed env-файле. Для batch/session CLI режима это избыточный риск: оператор может вводить unseal secret при каждом запуске, а persistent vault остаётся читаемым между запусками через deterministic KDF.

---

## 🎯 Решение

Перейти на unseal-runtime модель:

```text
unseal passphrase
  -> Argon2id(salt/params from vault_unseal_meta)
  -> runtime Fernet-compatible master wrapping key
  -> HMAC-SHA256 check
  -> VaultStartupGuard probe verification
```

Master key не сохраняется на диске и не принимается из process ENV. На диске остаются только KDF/HMAC metadata в SQLite и wrapped DEK.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые компоненты**:
- `VaultUnsealService` — Argon2id derivation + HMAC verification.
- `UnsealedVaultKeyProvider` — lazy in-memory `VaultKeyProviderPort`.
- `vault_unseal_meta` — singleton SQLite table для KDF/HMAC metadata.

**Изменения**:
- `VaultContainer` получает passphrase через composition root и больше не читает ENV/файлы.
- `vault-management init/status/rotate/rewrap` работают с unseal passphrase.
- `rotate` означает смену passphrase и rewrap всех DEK.
- `delete-key`, `run-maintenance`, managed env keyring и auto-rotation удалены.

### Интерфейсы

```python
class VaultUnsealServiceProtocol(Protocol):
    def create_metadata(
        self, *, passphrase: str, key_version: str, now_utc: str
    ) -> tuple[VaultUnsealMetadata, VaultMasterKey]: ...

    def derive_key(self, *, passphrase: str, metadata: VaultUnsealMetadata) -> VaultMasterKey: ...
```

```python
class SecretVaultRepositoryPort(Protocol):
    def get_unseal_metadata(self) -> VaultUnsealMetadata | None: ...
    def upsert_unseal_metadata(self, metadata: VaultUnsealMetadata) -> None: ...
```

### Поток данных

```text
Runtime command requiring vault
  -> delivery prompt asks unseal passphrase
  -> AppContainer.vault_unseal_passphrase override
  -> SqliteContainer.vault_ready
  -> UnsealedVaultKeyProvider derives key
  -> VaultStartupGuard validates DEK/probe
  -> SecretVaultReadService / SecretVaultWriteService use existing ports
```

---

## ✅ Почему это решение?

**Преимущества**:
- Master key material больше не лежит рядом с vault DB.
- Сохраняется persistent vault между CLI-запусками.
- Read/write сервисы остаются на существующем `VaultKeyProviderPort`.
- Нет второго источника истины для key material.

**Недостатки**:
- Нет unattended runtime без оператора.
- Python не гарантирует полноценный secure zeroing всех копий secret material.
- `mlock`/`ptrace` hardening отложены.

**Отклонено**:
- Managed env hardening: key всё равно at rest.
- Encrypted key file: переносит проблему на новый root secret.
- External KMS: выходит за dev/self-contained scope.

---

## 🛠️ Реализация

| Файл | Изменение |
|------|-----------|
| `connector/infra/secrets/unseal.py` | Argon2id/HMAC и in-memory key provider |
| `connector/usecases/management/vault/usecase.py` | init/status/rotate/rewrap под unseal model |
| `connector/delivery/cli/containers.py` | VaultContainer и startup resource без ENV/managed keyring |
| `connector/infra/secrets/sqlite/schema.py` | `vault_unseal_meta`, schema v3 |

### Инварианты

1. `ANKEY_VAULT_MASTER_KEYS` не является runtime input.
2. `vault_unseal_meta` не содержит plaintext passphrase/master key.
3. `status` не требует unseal, `status --verify` требует passphrase.
4. `rotate` требует старую и новую passphrase; старая должна пройти HMAC/probe.

---

## 🧪 Валидация решения

**Тесты**:
- Argon2id derivation deterministic для одинаковых metadata/passphrase.
- Неверная passphrase падает на HMAC check.
- SQLite repository сохраняет/читает `vault_unseal_meta`.
- `init`, `rotate`, `rewrap`, `status --verify` покрыты usecase/CLI тестами.

**Метрики успеха**:
- В production code отсутствуют `EnvVaultKeyProvider`, `VaultManagedEnvKeyringStore`, `ANKEY_VAULT_MASTER_KEYS`.
- CLI help не содержит `delete-key` и `run-maintenance`.

---

## ⚠️ Риски и ограничения

- Passphrase-only модель требует оператора при каждом vault runtime запуске.
- На этом этапе нет schema migration: dev vault DB может быть пересоздана.
- `mlock`, secure zeroing и `ptrace/prctl` не реализуются в этой итерации.

---

## 🔗 Связанные документы

- [VAULT-PROBLEM-003](./VAULT-PROBLEM-003-master-key-at-rest-and-unseal-runtime.md)
- [VAULT-DEC-001](./VAULT-DEC-001-envelope-encrypted-vault-with-hexagonal-ports.md)
- [VAULT-DEC-002](./VAULT-DEC-002-vault-management-managed-env-keyring-and-rotation-lifecycle.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-04-28 | Принята unseal-runtime модель без master key at rest |
