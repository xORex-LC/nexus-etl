# Vault Layer — Crypto

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [📐 UML диаграммы](#-uml-диаграммы)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма зависимостей](#диаграмма-зависимостей)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
  - [🚨 Failure Modes](#-failure-modes)
  - [⚠️ Инварианты системы](#️-инварианты-системы)
  - [⏱️ Performance заметки](#️-performance-заметки)
- [🛠️ Как расширять](#️-как-расширять)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Crypto-слой vault реализует envelope encryption и runtime unseal
модель master wrapping key.

**Ключевая ответственность**: шифровать пользовательские секреты через DEK,
оборачивать DEK master wrapping key, выводить master wrapping key из operator
passphrase через Argon2id и проверять passphrase через HMAC metadata.

**Расположение в кодовой базе**: `connector/infra/secrets`,
`connector/domain/secrets`, `connector/domain/ports/secrets`.

Master key material больше не хранится на диске и не читается из process ENV.
При runtime-запуске delivery layer запрашивает unseal passphrase, composition root
передаёт её в `UnsealedVaultKeyProvider`, а provider лениво выводит in-memory
`VaultMasterKey` по metadata из таблицы `vault_unseal_meta`.

---

## 🏗️ Архитектура слоя

### Основные компоненты

```text
connector/
├── domain/ports/secrets/
│   ├── cipher.py          # SecretCipherPort
│   ├── key_provider.py    # VaultKeyProviderPort, VaultMasterKey
│   └── repository.py      # SecretVaultRepositoryPort
├── domain/secrets/
│   ├── secret_vault_read_service.py
│   ├── secret_vault_write_service.py
│   ├── vault_startup_guard.py
│   └── models.py         # VaultDekRecord, VaultUnsealMetadata
└── infra/secrets/
    ├── fernet_cipher.py  # FernetEnvelopeCipher
    ├── unseal.py         # VaultUnsealService, UnsealedVaultKeyProvider
    └── sqlite/           # persisted DEK/probe/unseal metadata
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Overview | [Vault UML index](../../../uml/vault/README.md) | Индекс актуальных и исторических диаграмм vault |

### 🎭 Применённые паттерны

#### Adapter: `FernetEnvelopeCipher`

**Где применяется**: infra adapter реализует `SecretCipherPort`.

**Реализация в коде**:
- **Port**: `SecretCipherPort` в `connector/domain/ports/secrets/cipher.py`
- **Adapter**: `FernetEnvelopeCipher` в `connector/infra/secrets/fernet_cipher.py`

**Зачем**: domain-сервисы работают с абстрактным cipher port и не зависят от
`cryptography.fernet`.

#### Provider: `UnsealedVaultKeyProvider`

**Где применяется**: runtime key-provider для read/write/startup vault сервисов.

**Реализация в коде**:
- **Port**: `VaultKeyProviderPort`
- **Adapter**: `UnsealedVaultKeyProvider`
- **Crypto service**: `VaultUnsealService`

**Зачем**: passphrase остаётся runtime input, а key material не записывается в
ENV, config или managed-файл.

### Диаграмма зависимостей

```text
Delivery prompt
  → AppContainer.vault_unseal_passphrase
  → VaultContainer
  → UnsealedVaultKeyProvider
  → VaultUnsealService + vault_unseal_meta
  → SecretVaultReadService / SecretVaultWriteService
  → FernetEnvelopeCipher
```

---

## 🔑 Ключевые абстракции

### Интерфейсы/Порты

| Интерфейс | Назначение | Где используется |
|-----------|------------|------------------|
| `SecretCipherPort` | Encrypt/decrypt секретов и wrap/unwrap DEK | read/write services, startup guard, management usecase |
| `VaultKeyProviderPort` | Дать active key и keyring candidates | read/write services, startup guard |
| `SecretVaultRepositoryPort` | Хранить secret/DEK/probe/unseal metadata | domain services, management usecase |

### Основные классы

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
| `FernetEnvelopeCipher` | Fernet adapter для ciphertext и wrapped DEK | `encrypt()`, `decrypt()`, `wrap_dek()`, `unwrap_dek()` |
| `VaultUnsealService` | Argon2id/HMAC unseal logic | `create_metadata()`, `derive_key()` |
| `UnsealedVaultKeyProvider` | In-memory runtime key provider | `get_active_key()`, `get_all_keys()`, `find_key()` |

---

## 🗂️ Модели данных

### Dataclass: `VaultUnsealMetadata`

**Назначение**: хранит параметры KDF/HMAC, по которым можно проверить
operator passphrase и вывести master wrapping key.

**Структура**:
```python
@dataclass(frozen=True)
class VaultUnsealMetadata:
    key_version: str
    kdf_algo: str
    kdf_salt: bytes
    kdf_time_cost: int
    kdf_memory_cost_kib: int
    kdf_parallelism: int
    kdf_hash_len: int
    hmac_algo: str
    hmac_salt: bytes
    hmac_digest: bytes
    created_at: str
    updated_at: str
```

**Lifecycle**:
1. **Создание**: `vault-management init` создаёт metadata и startup probe.
2. **Проверка**: runtime/startup и `status --verify` выводят key из passphrase
   и сравнивают HMAC.
3. **Ротация**: `vault-management rotate` создаёт новую metadata и rewrap-ит DEK
   в одной DB transaction.

### Dataclass: `VaultMasterKey`

**Назначение**: in-memory представление active master wrapping key.

**Инварианты**:
- `key_material` Fernet-compatible: urlsafe base64 encoded 32 bytes.
- В steady-state keyring содержит один active key.
- Объект не persisted; он существует только в памяти процесса.

---

## 📊 Ключевые методы и алгоритмы

### Обзор сложных методов

| Метод | Сложность | Назначение |
|-------|-----------|------------|
| `VaultUnsealService.create_metadata()` | O(Argon2id cost) | Создать salts, вывести raw key, сохранить HMAC digest |
| `VaultUnsealService.derive_key()` | O(Argon2id cost) | Проверить passphrase через HMAC и вернуть runtime key |
| `SecretVaultReadService.get_secret()` | O(k) по key candidates | Найти secret, unwrap DEK, decrypt ciphertext |

### Метод: `VaultUnsealService.derive_key()`

**Расположение**: `connector/infra/secrets/unseal.py`

**Сигнатура**:
```python
def derive_key(self, *, passphrase: str, metadata: VaultUnsealMetadata) -> VaultMasterKey:
```

**Назначение**: вывести master wrapping key из passphrase и проверить, что
passphrase соответствует persisted unseal metadata.

**Алгоритм**:
```text
1. Проверить, что passphrase не пустой.
2. Проверить поддерживаемый KDF: argon2id.
3. Вывести raw 32-byte key через Argon2id с параметрами metadata.
4. Рассчитать HMAC-SHA256(raw_key, prefix + hmac_salt).
5. Сравнить digest через hmac.compare_digest().
6. Вернуть VaultMasterKey(key_version=metadata.key_version, key_material=base64(raw_key)).
```

**Failure modes**:
- пустая passphrase → `SecretKeyConfigError(reason="unseal_passphrase_empty")`;
- неподдерживаемый KDF/HMAC → `SecretKeyConfigError`;
- HMAC mismatch → `SecretKeyConfigError(reason="unseal_passphrase_invalid")`.

---

## 🔄 Взаимодействие с другими слоями

| Слой | Взаимодействие |
|------|----------------|
| Delivery | Запрашивает passphrase, передаёт её в composition root, не делает KDF/HMAC |
| Usecase | Оркестрирует `init/status/rotate/rewrap`, вызывает `VaultUnsealService` через protocol |
| Domain | Read/write/startup guard используют `VaultKeyProviderPort` и `SecretCipherPort` |
| Infra storage | SQLite хранит DEK, probe, secret records и `vault_unseal_meta` |

---

## 🔌 Контракты и границы

- `VaultContainer` не читает ENV, файлы и не спрашивает пользователя.
- `VaultUnsealService` не знает о Typer, SQLite connection lifecycle и CLI options.
- `UnsealedVaultKeyProvider` не создаёт metadata; он только читает metadata и выводит key.
- `FernetEnvelopeCipher` не знает о vault lifecycle и не выбирает key versions.
- Никакой runtime path не принимает `ANKEY_VAULT_MASTER_KEYS` как источник master key.

---

## 💡 Типичные сценарии

1. **Первичная инициализация**
   - `vault-management init`
   - admin password prompt
   - new unseal passphrase prompt twice
   - create `vault_unseal_meta`, DEK and startup probe

2. **Runtime pipeline**
   - `enrich`, `import plan` или `import apply`
   - delivery prompt получает unseal passphrase
   - startup guard проверяет HMAC и probe
   - read/write сервисы работают через in-memory key provider

3. **Rotate passphrase**
   - `vault-management rotate`
   - old passphrase проверяет текущий key
   - new passphrase создаёт новую metadata
   - все DEK rewrap-ятся на новый key version

---

## 📌 Важные детали

### 🚨 Failure Modes

| Сценарий | Поведение |
|----------|-----------|
| Vault не initialized | runtime startup падает с key config/startup error |
| Неверная unseal passphrase | HMAC mismatch до unwrap/probe |
| HMAC прошёл, но probe не decrypt | startup guard блокирует запуск |
| DEK wrap повреждён | read path возвращает controlled decryption/read error |

### ⚠️ Инварианты системы

- Master key не хранится на диске.
- В DB хранится только metadata для проверки passphrase и wrapped DEK.
- DEK шифрует секреты; master wrapping key шифрует DEK.
- `vault_probe` остаётся финальной проверкой, что key реально открывает vault.
- `mlock`, secure zeroing и `ptrace/prctl` в этой итерации не реализованы.

### ⏱️ Performance заметки

- Argon2id defaults: memory 64 MiB, `time_cost=3`, `parallelism=4`, output 32 bytes.
- KDF выполняется при unseal/startup, а не на каждый secret read/write.
- После первого derive `UnsealedVaultKeyProvider` кеширует active key в памяти процесса.

---

## 🛠️ Как расширять

- Для другой KDF/HMAC версии добавлять новый алгоритм в `VaultUnsealService` и
  новую metadata версию; старые metadata нельзя silently reinterpret.
- Для внешнего KMS/HSM реализовать новый `VaultKeyProviderPort`, не меняя
  read/write services.
- Для automation secret source добавлять отдельный delivery/composition-root
  input, не возвращая ENV keyring как runtime authority.

---

## 🔗 Связанные документы

- [vault-core.md](vault-core.md)
- [vault-storage.md](vault-storage.md)
- [vault-delivery.md](vault-delivery.md)
- [VAULT-DEC-003](../../../adr/vault/VAULT-DEC-003-unseal-derived-master-key-runtime.md)
