# VAULT-PROBLEM-003: Master key at rest и необходимость unseal-runtime модели

> **Статус**: Закрыта через [VAULT-DEC-003](./VAULT-DEC-003-unseal-derived-master-key-runtime.md)
> **Дата создания**: 2026-04-28
> **Затронутые компоненты**: `VaultManagedEnvKeyringStore`, `EnvVaultKeyProvider`, `FernetEnvelopeCipher`, `VaultStartupGuard`, `SecretVaultReadService`, `SecretVaultWriteService`, `VaultKeyManagementUseCase`, `vault-management`

---

## 📋 Контекст

Vault-подсистема использует envelope encryption:

- `vault_secrets.ciphertext` хранит секреты, зашифрованные DEK;
- `vault_dek.wrapped_dek` хранит DEK, обёрнутый master key;
- master keyring сейчас хранится в managed env-файле, например `environment/vault.env`;
- `vault-management` управляет lifecycle master keyring через `init`, `rotate`, `rewrap`, `delete-key`, `run-maintenance`;
- admin password gate защищает операции управления vault через отдельный hash-файл.

Эта модель закрыла plaintext-хранение секретов и добавила управляемый lifecycle master keys ([VAULT-DEC-001](./VAULT-DEC-001-envelope-encrypted-vault-with-hexagonal-ports.md), [VAULT-DEC-002](./VAULT-DEC-002-vault-management-managed-env-keyring-and-rotation-lifecycle.md)).

При этом текущий проект фактически работает в session/batch-режиме: пользователь запускает CLI-команду, процесс выполняет ETL-поток и завершается. Для такого режима допустимо требовать интерактивный unseal перед выполнением vault-runtime операций.

---

## ⚠️ Проблема

Master key material хранится на диске в локальном managed env-файле.

Даже при правах `0600` это оставляет локальный secret at rest:

- компрометация файла `environment/vault.env` даёт attacker-у master key;
- компрометация `cache/ankey_vault.sqlite3` вместе с `environment/vault.env` раскрывает DEK и все persistent secrets;
- OS-права снижают риск, но не устраняют сам факт наличия master key на диске;
- текущая runtime-модель допускает process ENV/managed-file как источник keyring authority, что требует отдельного контроля доверенности источника.

Для batch-приложения возможно более строгая модель: master key не хранится на диске, а восстанавливается в RAM при запуске через unseal passphrase.

---

## 🔍 Симптомы

- **Симптом 1**: `environment/vault.env` содержит `ANKEY_VAULT_MASTER_KEYS=...` с фактическим master key material.
- **Симптом 2**: `VaultManagedEnvKeyringStore` сохраняет steady-state keyring в файл для последующих запусков.
- **Симптом 3**: `EnvVaultKeyProvider` и startup preload строят runtime key provider из material, который уже доступен процессу как строка.
- **Симптом 4**: security boundary фактически переносится на OS file permissions и дисциплину окружения запуска.
- **Симптом 5**: если полностью отказаться от persisted master key без замены модели, persistent secrets между запусками станут недоступны.

---

## 📊 Масштаб проблемы

- **Частота**: Всегда при использовании текущего managed env keyring.
- **Критичность**: Средняя для dev/local эксплуатации, высокая для production-like окружений с persistent vault secrets.
- **Затронуто**: `enrich`, `import plan`, `import apply`, `vault-management init/rotate/rewrap/delete-key/run-maintenance`, recovery после падения процесса, delayed apply/pending сценарии.

---

## 🧪 Как воспроизвести

1. Выполнить `vault-management init` с configured `vault_management.managed_env_file`.
2. Открыть configured managed env-файл, например `environment/vault.env`.
3. Убедиться, что файл содержит `ANKEY_VAULT_MASTER_KEYS=...`.
4. Скопировать `environment/vault.env` и `cache/ankey_vault.sqlite3` в отдельное окружение.
5. Запустить vault-runtime чтение с этим keyring.
6. **Ожидаемый результат**: master key не должен быть доступен на диске; для доступа нужен unseal secret, вводимый оператором.
7. **Фактический результат**: master key material доступен из файла при наличии доступа к filesystem.

---

## 🚫 Почему это проблема?

- Master key at rest увеличивает blast radius при локальной компрометации файлов.
- Envelope encryption теряет часть смысла, если рядом с vault DB лежит key material, раскрывающий DEK.
- Managed env keyring удобен для automation, но плохо соответствует session-mode CLI, где оператор может вводить unseal secret при каждом запуске.
- Нельзя перейти к модели "ключа нет на диске" без пересмотра bootstrap, startup guard, rotate semantics и recovery.
- Если сделать master key purely session-random, persistent secrets станут нечитаемы при следующем запуске.

---

## 💡 Возможные решения (обсуждение)

> Этот раздел фиксирует варианты до принятия финального решения. Документ не утверждает реализацию.

### Вариант 1: Оставить managed env keyring и усилить OS-права
- **Идея**: Продолжать хранить master keyring в `environment/vault.env`, но строго проверять mode/owner и убрать process ENV fallback.
- **Плюсы**: Минимальный объём изменений, совместимо с текущим `rotate/rewrap`.
- **Минусы**: Master key всё равно остаётся на диске.

### Вариант 2: Зашифрованный master key file
- **Идея**: Хранить encrypted master key на диске и расшифровывать его при старте отдельным password/root key.
- **Плюсы**: Master key material не лежит plaintext-файлом.
- **Минусы**: Появляется новый root secret; если он хранится рядом или в ENV, проблема переносится, а не решается.

### Вариант 3: Unseal passphrase + KDF + HMAC/probe
- **Идея**: При `init` оператор задаёт unseal passphrase. Система через KDF (`argon2id`/другой approved KDF) выводит master wrapping key, сохраняет salt/params и HMAC-check в SQLite, но не сохраняет master key. При запуске оператор вводит passphrase, система выводит key заново, проверяет HMAC и выполняет startup probe decrypt.
- **Плюсы**: Master key не хранится на диске; persistent vault остаётся читаемым между запусками при вводе той же passphrase; модель хорошо подходит session/batch CLI.
- **Минусы**: Нужно изменить bootstrap, runtime startup, rotate semantics, тесты и UX; Python не гарантирует полноценное zeroing всех копий secret material.

### Вариант 4: Внешний KMS/OS keyring/systemd credentials
- **Идея**: Делегировать root secret внешнему trust provider.
- **Плюсы**: Более сильная security boundary и меньше custom crypto/lifecycle.
- **Минусы**: Повышает операционную сложность и выходит за текущий dev/self-contained scope.

### Вариант 5: Session-only vault без persistent secrets
- **Идея**: Каждый run создаёт новый session master key/DEK, а secrets удаляются после successful apply.
- **Плюсы**: На диске не нужен persistent key; проще runtime-модель.
- **Минусы**: Несовместимо с delayed apply, retry между запусками, pending flows и текущими persistent secret lifecycle политиками.

### Предварительное направление

Наиболее перспективным выглядит вариант 3:

```text
unseal passphrase
  -> KDF + salt/params из SQLite
  -> in-memory master wrapping key
  -> HMAC check
  -> vault_probe / DEK unwrap verification
  -> runtime SecretVaultReadService/SecretVaultWriteService
```

Для `rotate` в этой модели preliminary semantics должны измениться:

```text
old unseal passphrase -> old master key -> unwrap DEK
new unseal passphrase -> new master key -> wrap DEK
update KDF/HMAC/probe metadata
```

---

## 🔗 Связанные документы

- [VAULT-PROBLEM-001](./VAULT-PROBLEM-001-plaintext-dev-vault-and-missing-crypto-lifecycle.md)
- [VAULT-DEC-001](./VAULT-DEC-001-envelope-encrypted-vault-with-hexagonal-ports.md)
- [VAULT-PROBLEM-002](./VAULT-PROBLEM-002-missing-vault-management-and-key-lifecycle-automation.md)
- [VAULT-DEC-002](./VAULT-DEC-002-vault-management-managed-env-keyring-and-rotation-lifecycle.md)
- [Vault Crypto](../../dev/layers/vault/vault-crypto.md)
- [Vault Delivery](../../dev/layers/vault/vault-delivery.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-04-28 | Проблема зафиксирована после обсуждения отказа от master key at rest и перехода к unseal-runtime модели |
| 2026-04-28 | Предварительно выделены варианты: managed env hardening, encrypted key file, unseal passphrase + KDF/HMAC/probe, внешний KMS, session-only vault |
