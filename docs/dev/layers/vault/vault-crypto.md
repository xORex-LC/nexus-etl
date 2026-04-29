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
    ├── fernet_envelope_cipher.py  # FernetEnvelopeCipher
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

### Метод: `FernetEnvelopeCipher.encrypt()`

**Расположение**: `connector/infra/secrets/fernet_envelope_cipher.py`

**Сигнатура**:
```python
def encrypt(self, *, plaintext: str, dek_plaintext: bytes, cipher_algo: str) -> bytes:
```

**Назначение**: зашифровать plaintext секрета Data Encryption Key, не раскрывая
master wrapping key на path шифрования пользовательского значения.

**Алгоритм**:
```text
1. Проверить, что cipher_algo == FERNET_V1.
2. Построить Fernet(dek_plaintext).
3. Закодировать plaintext как UTF-8.
4. Вернуть Fernet token bytes.
5. Ошибки ключа маппятся в SecretKeyConfigError, ошибки token/decrypt в SecretIntegrityError.
```

**Инварианты**:
- plaintext не логируется и не попадает в exception details;
- `dek_plaintext` должен быть Fernet-compatible key material;
- результат хранится как opaque ciphertext BLOB/TEXT в storage layer.

### Метод: `FernetEnvelopeCipher.wrap_dek()`

**Расположение**: `connector/infra/secrets/fernet_envelope_cipher.py`

**Сигнатура**:
```python
def wrap_dek(self, *, dek_plaintext: bytes, master_key: str, wrap_algo: str) -> bytes:
```

**Назначение**: обернуть DEK текущим runtime master wrapping key.

**Алгоритм**:
```text
1. Проверить wrap_algo == FERNET_V1.
2. Построить Fernet(master_key).
3. Зашифровать DEK как opaque bytes.
4. Вернуть wrapped_dek для vault_dek.
```

**Edge cases**:
- неверный `master_key` format → `SecretKeyConfigError`;
- повреждённый `wrapped_dek` при unwrap → `SecretIntegrityError` или
  `SecretDecryptionError`, в зависимости от стадии отказа.

### Сквозной алгоритм записи секрета

```text
Input: dataset, match_key/source_ref, {field: plaintext}
  ↓
SecretVaultWriteService получает active VaultMasterKey
  ↓
Если active DEK отсутствует:
  - генерирует 32 random bytes;
  - кодирует как Fernet key;
  - wrap_dek(DEK, active master key);
  - сохраняет VaultDekRecord.
  ↓
Для каждого secret field:
  - locator_hash = SecretLocatorService.build_locator_hash(...);
  - ciphertext = FernetEnvelopeCipher.encrypt(plaintext, DEK);
  - upsert VaultSecretRecord(dataset, field, locator_hash, run_id, key_version, dek_version).
```

**Свойство безопасности**: master wrapping key не шифрует пользовательские
секреты напрямую; он используется только для wrap/unwrap DEK.

### Сквозной алгоритм чтения секрета

```text
Input: dataset, field, source_ref, run_id/default_run_id
  ↓
SecretVaultReadService нормализует source_ref.match_key
  ↓
Строит locator_hash тем же алгоритмом, что write path
  ↓
Читает VaultSecretRecord с precedence exact run_id → global NULL
  ↓
Читает VaultDekRecord(record.dek_version)
  ↓
Пробует unwrap DEK:
  1. ключ с wrap_key_version;
  2. fallback keys из provider, если они есть.
  ↓
decrypt(ciphertext, DEK) → plaintext secret
```

**Семантика отсутствия**:
- нет `source_ref.match_key` → `None`;
- нет secret record → `None`;
- есть record, но не удалось прочитать/расшифровать → controlled `Secret*Error`.

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
| Ciphertext не является Fernet token | `SecretIntegrityError` без раскрытия ciphertext |
| `vault_unseal_meta` содержит завышенные KDF params | `SecretKeyConfigError`, derive не запускает экстремальный Argon2id |

### Таксономия ошибок

| Ошибка | Когда используется | Безопасные details |
|--------|--------------------|--------------------|
| `SecretKeyConfigError` | неподдержанный algo, неверный key format, неверная passphrase, плохие KDF params | `reason`, `kdf_algo`, `param`, `key_version` |
| `SecretIntegrityError` | malformed token/ciphertext/wrapped DEK | `reason`, `cipher_algo`, `wrap_algo` |
| `SecretDecryptionError` | token валиден по форме, но не decrypt-ится выбранным key/DEK | `reason`, `dek_version`, `key_version` |
| `VaultStartupKeyValidationError` | probe не открывается derived key | `reason`, `probe_name`, `dek_version` |

Details не должны содержать plaintext secret, passphrase, DEK plaintext,
master key material, HMAC digest или ciphertext bytes.

### ⚠️ Инварианты системы

- Master key не хранится на диске.
- В DB хранится только metadata для проверки passphrase и wrapped DEK.
- DEK шифрует секреты; master wrapping key шифрует DEK.
- `vault_probe` остаётся финальной проверкой, что key реально открывает vault.
- `mlock`, secure zeroing и `ptrace/prctl` в этой итерации не реализованы.
- DEK создаётся через cryptographically secure random source и хранится только
  как wrapped value.
- `cipher_algo` и `wrap_algo` пишутся per-record, чтобы будущая crypto migration
  могла быть явной, а не inferred из глобального состояния.
- `key_version` в secret/probe/dek metadata нужен для трассировки и выбора
  candidate key, но не является секретом.

### ⏱️ Performance заметки

- Argon2id defaults: memory 64 MiB, `time_cost=3`, `parallelism=4`, output 32 bytes.
- KDF выполняется при unseal/startup, а не на каждый secret read/write.
- После первого derive `UnsealedVaultKeyProvider` кеширует active key в памяти процесса.
- Fernet encrypt/decrypt выполняется на уровне отдельных secret fields; стоимость
  линейна от числа secret fields и размера plaintext.
- Rotate/re-wrap не расшифровывает пользовательские secrets: он unwrap/wrap-ит
  только DEK, поэтому стоимость линейна от количества DEK, а не от количества
  secret records.

### Соображения по тестированию

- Для unit-тестов crypto-адаптера используйте реальные Fernet keys, а не
  hardcoded invalid strings.
- Для domain/usecase тестов допускается `StaticVaultKeyProvider`, если тест
  не проверяет Argon2id/HMAC.
- Для unseal тестов проверяйте deterministic derive на одинаковой metadata и
  failure на wrong passphrase.
- Для storage/integration тестов проверяйте, что plaintext не появляется в
  `vault_secrets.ciphertext`.
- Для regression guard полезен grep по runtime markers:
  `ANKEY_VAULT_MASTER_KEYS`, `EnvVaultKeyProvider`, `VaultManagedEnvKeyringStore`.

### FAQ

**Почему Fernet используется и для secret ciphertext, и для wrapped DEK?**
Это один audited primitive в двух разных ролях. Разделение ролей задаётся ключом:
DEK шифрует пользовательский secret, master wrapping key шифрует DEK.

**Почему DEK хранится как Fernet-compatible base64 key, а не raw bytes?**
`cryptography.fernet.Fernet` принимает именно urlsafe base64 encoded 32-byte key.
Поэтому DEK генерируется как 32 random bytes и кодируется в формат Fernet key.

**Можно ли использовать один и тот же материал для DEK и master key?**
Нет. DEK генерируется отдельно и может rewrap-иться без перешифрования всех
секретов. Master wrapping key выводится из passphrase и не persisted.

**Что меняется при смене unseal passphrase?**
Создаётся новая `vault_unseal_meta`, из новой passphrase выводится новый master
wrapping key, все DEK unwrap-ятся старым key и wrap-ятся новым key. Secret
ciphertext не меняется.

**Что произойдёт, если process завершится?**
In-memory `VaultMasterKey` исчезает. При следующем запуске оператор снова вводит
unseal passphrase, provider выводит тот же key из metadata.

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
