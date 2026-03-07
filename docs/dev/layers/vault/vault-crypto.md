# Vault Layer — Crypto: Конвертное шифрование

> **Область охвата:** В этом документе описывается криптографический слой подсистемы vault —
> как открытые секреты превращаются в зашифрованные блобы, как Data Encryption Keys (DEK)
> генерируются и оборачиваются (wrap), а также как master keys загружаются из окружения.
>
> **Связанные документы:**
> - [vault-core.md](vault-core.md) — поток домена pipeline (enrich → plan → apply)
> - [vault-storage.md](vault-storage.md) — схема SQLite и репозиторий
> - [vault-delivery.md](vault-delivery.md) — доменные сервисы, политики и DI-проводка

---

## 1. Обзор

Криптографический слой vault реализует **конвертное шифрование** (envelope encryption):
двухуровневую иерархию ключей, при которой открытые секреты никогда не шифруются
напрямую долгоживущим master key. Вместо этого:

1. Короткоживущий **Data Encryption Key (DEK)** шифрует открытый секрет.
2. Master key шифрует (оборачивает, wrap) DEK.

Такое разделение обеспечивает ряд операционных преимуществ:

| Преимущество | Описание |
|---------|-------------|
| **Ротация ключей** | Смена master key — только re-wrap DEK, повторное шифрование всех секретов не нужно |
| **Изоляция DEK** | Компрометация одного DEK не раскрывает материал master key |
| **Fallback keyring** | Несколько версий master key параллельно для ротации без простоя |
| **Поверхность аудита** | Каждая зашифрованная запись хранит `key_version` и `dek_version` для трассировки |

### Алгоритм в одном предложении

> `ciphertext = Fernet(DEK).encrypt(plaintext)`,
> `wrapped_DEK = Fernet(master_key).encrypt(DEK)`.

Как шифрование секрета, так и оборачивание DEK используют один и тот же идентификатор
алгоритма `FERNET_V1`, который соответствует реализации `cryptography.fernet.Fernet`
(AES-128-CBC + HMAC-SHA256).

---

## 2. Архитектура

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Crypto layer (connector/infra/secrets/)                                   │
│                                                                            │
│  ┌─────────────────────────────────┐   ┌──────────────────────────────┐   │
│  │     FernetEnvelopeCipher        │   │    EnvVaultKeyProvider       │   │
│  │  (SecretCipherPort adapter)     │   │  (VaultKeyProviderPort adapt)│   │
│  │                                 │   │                              │   │
│  │  encrypt(plaintext, dek)        │   │  ANKEY_VAULT_MASTER_KEYS     │   │
│  │  decrypt(ciphertext, dek)       │   │  "v1:<key>,v2:<key>,..."     │   │
│  │  wrap_dek(dek, master_key)      │   │                              │   │
│  │  unwrap_dek(wrapped, master_key)│   │  get_active_key() -> MK[0]   │   │
│  └──────────────┬──────────────────┘   │  get_all_keys() -> tuple     │   │
│                 │                      │  find_key(ver) -> MK | None  │   │
│                 │ uses                 └──────────────────────────────┘   │
│                 ▼                                                          │
│  ┌─────────────────────────────────┐                                       │
│  │  cryptography.fernet.Fernet     │   AES-128-CBC + HMAC-SHA256          │
│  │  (third-party, pip)             │   urlsafe base64 token format         │
│  └─────────────────────────────────┘                                       │
└────────────────────────────────────────────────────────────────────────────┘

                 ▲ implements                        ▲ implements
                 │                                   │
┌────────────────────────────────┐  ┌──────────────────────────────────────┐
│  connector/domain/ports/       │  │  connector/domain/ports/             │
│  secrets/cipher.py             │  │  secrets/key_provider.py             │
│                                │  │                                      │
│  SecretCipherPort (Protocol)   │  │  VaultKeyProviderPort (Protocol)     │
│  VaultMasterKey (dataclass)    │  │  VaultMasterKey (dataclass)          │
└────────────────────────────────┘  └──────────────────────────────────────┘
```

### Разделение ответственностей

| Компонент | Знает о | Не знает о |
|-----------|-------------|---------------------|
| `FernetEnvelopeCipher` | Алгоритм Fernet, валидация token | Источник ключей, хранилище, доменные сервисы |
| `EnvVaultKeyProvider` | Разбор ENV-переменной, валидация Fernet-ключей | Операции шифрования, хранилище |
| Доменные сервисы (write/read) | Только контракты портов | Fernet, ENV-переменные, SQLite |

---

## 3. Контракты портов

### 3.1 `SecretCipherPort`

**Файл:** [`connector/domain/ports/secrets/cipher.py`](../../../../connector/domain/ports/secrets/cipher.py)

```python
class SecretCipherPort(Protocol):
    def encrypt(self, *, plaintext: str, dek_plaintext: bytes, cipher_algo: str) -> bytes | str: ...
    def decrypt(self, *, ciphertext: bytes | str, dek_plaintext: bytes, cipher_algo: str) -> str: ...
    def wrap_dek(self, *, dek_plaintext: bytes, master_key: str, wrap_algo: str) -> bytes | str: ...
    def unwrap_dek(self, *, wrapped_dek: bytes | str, master_key: str, wrap_algo: str) -> bytes: ...
```

**Инварианты контракта:**
- `plaintext` и `dek_plaintext` не должны появляться в исключениях или логах.
- Сбой целостности (`HMAC mismatch`) и сбой расшифровки (`wrong key`) должны быть
  различимы через доменные типы исключений (`SecretIntegrityError` vs `SecretDecryptionError`).
- `cipher_algo` / `wrap_algo` — явные идентификаторы алгоритма, не неявные;
  неизвестные алгоритмы должны порождать ошибку.

### 3.2 `VaultKeyProviderPort`

**Файл:** [`connector/domain/ports/secrets/key_provider.py`](../../../../connector/domain/ports/secrets/key_provider.py)

```python
class VaultKeyProviderPort(Protocol):
    def get_active_key(self) -> VaultMasterKey: ...
    def get_all_keys(self) -> tuple[VaultMasterKey, ...]: ...
    def find_key(self, key_version: str) -> VaultMasterKey | None: ...
```

**Назначение каждого метода:**

| Метод | Сценарий использования |
|--------|----------|
| `get_active_key()` | Путь записи: обернуть (wrap) новый DEK активным ключом |
| `get_all_keys()` | Путь разворачивания (unwrap): перебрать fallback-кандидатов, если подсказанный ключ не подошёл |
| `find_key(version)` | Путь разворачивания: получить конкретный ключ, которым изначально был обёрнут DEK |

### 3.3 `VaultMasterKey`

```python
@dataclass(frozen=True)
class VaultMasterKey:
    key_version: str    # Стабильный идентификатор, хранится в vault_dek.wrap_key_version
    key_material: str   # Fernet-ключ (urlsafe base64-кодированный 32-байтовый ключ)
    is_active: bool     # True только для первого ключа в keyring
```

`key_version` — произвольная строка, задаваемая оператором (например, `"v1"`, `"2024-01-15"`).
`key_material` хранится в памяти и не должен появляться в логах.

---

## 4. `FernetEnvelopeCipher` — Реализация

**Файл:** [`connector/infra/secrets/fernet_envelope_cipher.py`](../../../../connector/infra/secrets/fernet_envelope_cipher.py)

```python
class FernetEnvelopeCipher(SecretCipherPort):
    def encrypt(self, *, plaintext: str, dek_plaintext: bytes, cipher_algo: str) -> bytes | str
    def decrypt(self, *, ciphertext: bytes | str, dek_plaintext: bytes, cipher_algo: str) -> str
    def wrap_dek(self, *, dek_plaintext: bytes, master_key: str, wrap_algo: str) -> bytes | str
    def unwrap_dek(self, *, wrapped_dek: bytes | str, master_key: str, wrap_algo: str) -> bytes
```

### 4.1 `encrypt(plaintext, dek_plaintext, cipher_algo)`

**Назначение:** Зашифровать строку открытого секрета с помощью DEK.

```
Алгоритм:
  1. Проверить cipher_algo == "FERNET_V1" (иначе SecretIntegrityError).
  2. Создать Fernet(dek_plaintext) — валидирует формат DEK.
  3. fernet.encrypt(plaintext.encode("utf-8")) → bytes token.
  4. Вернуть Fernet token (bytes).
```

Результирующий token встраивает временну́ю метку (спецификация Fernet), байт версии `0x80`, IV,
шифротекст и HMAC — всё в urlsafe base64.

**Путь сбоя:**
```
dek_plaintext неверного формата  →  SecretIntegrityError(reason="invalid_dek")
исключение при encrypt           →  SecretIntegrityError(reason="encrypt_failed")
```

### 4.2 `decrypt(ciphertext, dek_plaintext, cipher_algo)`

**Назначение:** Расшифровать Fernet token обратно в строку открытого текста.

```
Алгоритм:
  1. Проверить cipher_algo == "FERNET_V1".
  2. _normalize_token(ciphertext) → bytes (обрабатывает str и bytes на входе).
  3. _validate_token_shape(token) → быстрая структурная проверка до вызова Fernet.
  4. Создать Fernet(dek_plaintext).
  5. fernet.decrypt(token) → plaintext bytes.
  6. plaintext.decode("utf-8") → str.
```

**Зачем нужна предварительная валидация до вызова Fernet?**
`_validate_token_shape` (см. §4.5) жадно отклоняет деформированные token-ы, чтобы
до выполнения дорогостоящей проверки HMAC различить повреждённое хранилище
(`SecretIntegrityError`) и неверный ключ (`SecretDecryptionError`).

**Путь сбоя:**
```
пустой/неверный token         →  SecretIntegrityError(reason="empty_token" | "invalid_base64" | "invalid_fernet_envelope")
неверный ключ / HMAC mismatch →  SecretDecryptionError(reason="invalid_token")
другое исключение при decrypt →  SecretIntegrityError(reason="decrypt_failed")
невалидный UTF-8 plaintext    →  SecretIntegrityError(reason="invalid_utf8")
```

### 4.3 `wrap_dek(dek_plaintext, master_key, wrap_algo)`

**Назначение:** Обернуть (зашифровать) байты DEK master key для хранения.

```
Алгоритм:
  1. Проверить wrap_algo == "FERNET_V1".
  2. Создать Fernet(master_key.encode("utf-8")).
  3. fernet.encrypt(dek_plaintext) → wrapped DEK bytes.
  4. Вернуть bytes token.
```

DEK при оборачивании обрабатывается как непрозрачные бинарные данные (без строкового преобразования).

**Путь сбоя:**
```
неверный формат master key  →  SecretKeyConfigError(reason="invalid_master_key")
исключение при wrap         →  SecretIntegrityError(reason="wrap_failed")
```

### 4.4 `unwrap_dek(wrapped_dek, master_key, wrap_algo)`

**Назначение:** Развернуть (расшифровать) сохранённый wrapped DEK для восстановления байтов plaintext DEK.

```
Алгоритм:
  1. Проверить wrap_algo == "FERNET_V1".
  2. _normalize_token(wrapped_dek) → bytes.
  3. _validate_token_shape(token) → структурная проверка.
  4. Создать Fernet(master_key.encode("utf-8")).
  5. fernet.decrypt(token) → dek_plaintext bytes.
  6. Вернуть bytes (Fernet-совместимый DEK).
```

**Путь сбоя:**
```
неверная форма token              →  SecretIntegrityError(reason="invalid_base64" | "invalid_fernet_envelope")
неверный master key               →  SecretDecryptionError(reason="invalid_token")
другое исключение                 →  SecretIntegrityError(reason="unwrap_failed")
```

### 4.5 `_validate_token_shape(token: bytes)` — Быстрая предварительная валидация

**Файл:** [`connector/infra/secrets/fernet_envelope_cipher.py:164`](../../../../connector/infra/secrets/fernet_envelope_cipher.py#L164)

```python
def _validate_token_shape(token: bytes, *, context: str) -> None:
    decoded = base64.urlsafe_b64decode(token + b"=" * (-len(token) % 4))
    if len(decoded) < 9 or decoded[0] != 0x80:
        raise SecretIntegrityError(...)
```

**Что проверяется:**
1. Token является валидным urlsafe base64 (с допуском к паддингу).
2. Декодированные байты имеют длину не менее 9 байт.
3. Первый байт равен `0x80` — байт версии Fernet.

**Почему минимум 9 байт?**
Бинарный формат Fernet (до base64):
```
[version: 1 byte][timestamp: 8 bytes][IV: 16 bytes][ciphertext: ≥ 1 byte][HMAC: 32 bytes]
 = 0x80           = 8 bytes
```
Минимально структурно валидный token требует `version (1) + timestamp (8) = 9 байт`
до того, как библиотека Fernet вообще попытается его разобрать.

**Почему `0x80`?**
Fernet определяет байт версии `0x80` (128 decimal). Любое другое значение означает
либо другой алгоритм, либо повреждённое хранилище.

### 4.6 `_normalize_token(token: bytes | str)` — Нормализация входных данных

```python
def _normalize_token(token: bytes | str, *, context: str) -> bytes:
    if isinstance(token, bytes):
        if not token: raise SecretIntegrityError(reason="empty_token")
        return token
    if isinstance(token, str):
        raw = token.encode("utf-8")
        if not raw: raise SecretIntegrityError(reason="empty_token")
        return raw
    raise SecretIntegrityError(reason="invalid_token_type")
```

Хранилище может возвращать token-ы как `bytes` (колонка SQLite BLOB) или как `str` (legacy/тесты).
Этот нормализатор гарантирует, что последующий вызов Fernet всегда получает `bytes`.

### 4.7 Выбор алгоритма (`_ensure_algo`)

```python
def _ensure_algo(algo: str, *, expected: str, algo_kind: str) -> None:
    if algo != expected:
        raise SecretIntegrityError(
            details={"reason": "unsupported_algorithm", "algo": algo, "expected": expected}
        )
```

В настоящее время поддерживается только `FERNET_V1`. Идентификатор алгоритма всегда
хранится рядом с шифротекстом в записи vault, поэтому будущая миграция на `FERNET_V2`
или `AES_GCM_V1` потребует только добавления нового условного ветвления здесь и в доменном
порту — без изменения схемы хранилища.

---

## 5. `EnvVaultKeyProvider` — Реализация

**Файл:** [`connector/infra/secrets/env_key_provider.py`](../../../../connector/infra/secrets/env_key_provider.py)

### 5.1 Формат переменной окружения

```
ANKEY_VAULT_MASTER_KEYS=v1:<fernet_key_1>,v2:<fernet_key_2>
```

| Компонент | Описание |
|-----------|-------------|
| `v1` | `key_version` — произвольная строка, хранится в `vault_dek.wrap_key_version` |
| `<fernet_key_1>` | `key_material` — 32-байтовый Fernet-ключ в urlsafe base64 |
| `,` | Разделитель между записями keyring |
| Позиция 0 | Первая запись → активный ключ (используется для всех операций записи) |
| Позиции 1..N | Fallback-ключи для разворачивания (unwrap) при ротации |

**Пример с двумя ключами (во время ротации):**
```
ANKEY_VAULT_MASTER_KEYS=v2:new-fernet-key-material,v1:old-fernet-key-material
```

После этого изменения: `v2` активен (используется для новых wrap DEK), `v1` — fallback
(может по-прежнему разворачивать существующие записи DEK, созданные с `v1`).

### 5.2 `parse_master_keyring(raw_value, env_var)`

```
Последовательность валидации:
  1. Ошибка, если raw_value равен None или пустой → SecretKeyConfigError(reason="empty_keyring")
  2. Разбить по "," → список записей; ошибка, если пустой → та же ошибка
  3. Для каждой записи:
     a. Должна содержать ":" → SecretKeyConfigError(reason="invalid_entry_format")
     b. Разбить по первому ":" → (key_version, key_material)
     c. key_version не должен быть пустым → SecretKeyConfigError(reason="empty_key_version")
     d. key_material не должен быть пустым → SecretKeyConfigError(reason="empty_key_material")
     e. key_version должен быть уникальным → SecretKeyConfigError(reason="duplicate_key_version")
     f. Fernet(key_material) должен выполниться успешно → SecretKeyConfigError(reason="invalid_fernet_key")
  4. Собрать список VaultMasterKey; индекс == 0 → is_active=True, остальные False.
  5. Вернуть tuple[VaultMasterKey, ...].
```

**Fail-fast:** Вся валидация выполняется в момент вызова `EnvVaultKeyProvider.__init__()`,
который вызывается при запуске контейнера. Неверный keyring немедленно блокирует запуск
процесса с исключением `SecretKeyConfigError(code="VAULT_STARTUP_KEY_CONFIG_ERROR")`.

### 5.3 Методы `EnvVaultKeyProvider`

```python
class EnvVaultKeyProvider(VaultKeyProviderPort):
    def get_active_key(self) -> VaultMasterKey:
        return self._active_key  # Pre-computed at __init__ as self._keys[0]

    def get_all_keys(self) -> tuple[VaultMasterKey, ...]:
        return self._keys  # In declaration order; first is active

    def find_key(self, key_version: str) -> VaultMasterKey | None:
        return self._keys_by_version.get(key_version)  # O(1) dict lookup
```

### 5.4 Что является валидным Fernet-ключом

Fernet-ключ — это **urlsafe base64-кодированное 32-байтовое значение**.

```python
# Генерация нового ключа:
from cryptography.fernet import Fernet
key = Fernet.generate_key()  # e.g. b'AaBbCc...=='
```

Провайдер валидирует каждый ключ, конструируя `Fernet(key.encode("utf-8"))` —
если конструктор не бросает исключение, ключ валиден. Частичный материал ключа
или сырые hex-строки не принимаются.

---

## 6. Конвертное шифрование — Сквозной поток

### 6.1 Путь записи (сохранение секрета)

```
Входные данные: plaintext="employee_password", dataset="hr", field="password", match_key="emp_001"

Шаг 1: Найти или создать активный DEK
        ┌──────────────────────────────────────────────┐
        │  get_active_dek() из репозитория              │
        │  → если None: сгенерировать новый DEK          │
        │      dek_plaintext = base64.urlsafe_b64encode(os.urandom(32))
        │      wrapped_dek   = cipher.wrap_dek(dek_plaintext, master_key.key_material)
        │      dek_record    = VaultDekRecord(dek_version="dek_<uuid>", ...)
        │      repository.upsert_dek(dek_record)        │
        └──────────────────────────────────────────────┘

Шаг 2: Вычислить хэш локатора (см. vault-delivery.md §3.1)
        locator_hash = sha256("v1|hr|password|{match_key:emp_001}")

Шаг 3: Зашифровать секрет
        ciphertext = cipher.encrypt(
            plaintext = "employee_password",
            dek_plaintext = dek_plaintext,    # в памяти, никогда не сохраняется
            cipher_algo = "FERNET_V1",
        )
        → Fernet(DEK).encrypt(b"employee_password")  ==>  bytes token

Шаг 4: Сохранить в vault_secrets
        VaultSecretRecord(
            dataset="hr", field="password",
            locator_hash=<sha256>,  locator_version="v1",
            ciphertext=<fernet_token>, cipher_algo="FERNET_V1",
            key_version="v1",       dek_version="dek_<uuid>",
            run_id=None,
            created_at=..., updated_at=...,
        )

Результат в хранилище:
  vault_dek:     dek_<uuid>  wrapped_dek=Fernet(master_key).encrypt(DEK)  is_active=1
  vault_secrets: locator_hash=sha256(...)  ciphertext=Fernet(DEK).encrypt(plaintext)
```

### 6.2 Путь чтения (получение секрета)

```
Входные данные: dataset="hr", field="password", source_ref={"match_key": "emp_001"}, run_id=None

Шаг 1: Вычислить хэш локатора (тот же алгоритм, что и на пути записи)
        locator_hash = sha256("v1|hr|password|{match_key:emp_001}")

Шаг 2: Загрузить запись секрета
        record = repository.get_secret(
            dataset="hr", field="password",
            locator_hash=locator_hash, locator_version="v1",
            run_id=None,
        )
        → VaultSecretRecord или None

Шаг 3: Загрузить запись DEK
        dek_record = repository.get_dek(dek_version=record.dek_version)

Шаг 4: Развернуть (unwrap) DEK с приоритетом по keyring
        candidates = [find_key(record.key_version)] + get_all_keys()  # dedup
        for candidate in candidates:
            try:
                dek_plaintext = cipher.unwrap_dek(
                    wrapped_dek=dek_record.wrapped_dek,
                    master_key=candidate.key_material,
                    wrap_algo="FERNET_V1",
                )
                break  # success
            except (SecretDecryptionError, SecretIntegrityError):
                continue  # try next key
        else:
            raise SecretDecryptionError(reason="dek_unwrap_failed")

Шаг 5: Расшифровать секрет
        plaintext = cipher.decrypt(
            ciphertext = record.ciphertext,
            dek_plaintext = dek_plaintext,
            cipher_algo = "FERNET_V1",
        )
        return plaintext  # "employee_password"
```

### 6.3 Сводка жизненного цикла DEK

```
Состояние    │ Условие                          │ Действие
─────────────┼──────────────────────────────────┼──────────────────────────────
Нет DEK      │ Первая запись или после ротации  │ Сгенерировать DEK, wrap, сохранить
Активный DEK │ Обычные операции записи          │ Повторно использовать, unwrap в памяти
Ротированный │ После ротации master key         │ Старый wrapped_dek остаётся читаемым
DEK          │                                  │ через fallback keyring
Неактивный   │ is_active=0 (установлен upsert_dek)│ Доступен для чтения через get_dek(ver)
DEK          │                                  │ Не может быть выбран для записи
```

---

## 7. Ротация ключей

### 7.1 Что меняется при ротации

При введении нового master key меняется только **master key**. Сам DEK и все
шифротексты в `vault_secrets` остаются неизменными.

### 7.2 Процедура ротации без простоя

```
# До ротации: ANKEY_VAULT_MASTER_KEYS=v1:<old_key>

Шаг 1: Добавить новый ключ первым (активным):
        ANKEY_VAULT_MASTER_KEYS=v2:<new_key>,v1:<old_key>
        → Новые wrap DEK используют v2; старые wrapped DEK по-прежнему читаемы через fallback v1.

Шаг 2: При следующей записи создаётся новый DEK, обёрнутый v2 (если нужно).
        Существующие vault_secrets остаются зашифрованными под старым DEK (обёрнутым v1).

Шаг 3: (Опционально) Операция re-wrap DEK:
        Загрузить активный DEK → развернуть с fallback v1 → повторно обернуть активным ключом v2 →
        upsert_dek(новый VaultDekRecord с wrap_key_version="v2")
        Все последующие операции чтения используют v2 для разворачивания этого DEK.

Шаг 4: Когда все DEK ссылаются на v2, удалить v1:
        ANKEY_VAULT_MASTER_KEYS=v2:<new_key>
```

### 7.3 Алгоритм выбора ключей-кандидатов

Как `SecretVaultReadService`, так и `SecretVaultWriteService` используют один и тот же
паттерн при разворачивании DEK:

```python
def _candidate_master_keys(self, wrap_key_version: str) -> list[VaultMasterKey]:
    candidates = []
    hinted = self._key_provider.find_key(wrap_key_version)  # O(1) lookup
    if hinted is not None:
        candidates.append(hinted)          # Hinted key first (fast path)
    for key in self._key_provider.get_all_keys():
        if hinted and key.key_version == hinted.key_version:
            continue                        # Skip duplicate
        candidates.append(key)             # Full keyring as fallback
    return candidates
```

**Приоритет:**
1. Ключ, записанный в метаданных `wrap_key_version` (наиболее вероятный для успеха).
2. Все остальные ключи в порядке keyring (ротация/fallback).

Это означает, что обычные операции чтения всегда сначала пробуют наиболее вероятный ключ,
не перебирая весь keyring. Только при ротации ключей или сценариях восстановления
срабатывают fallback-ключи.

---

## 8. Инварианты безопасности

### 8.1 Отсутствие plaintext в исключениях и логах

Как `FernetEnvelopeCipher`, так и `EnvVaultKeyProvider` спроектированы так, что
ни plaintext-секрет, ни материал ключа не появляются в словарях `details` исключений или
в полях структурированных логов:

```python
# ПЛОХО (чего код избегает):
raise SecretDecryptionError(details={"plaintext": plaintext})

# ХОРОШО (что делает код):
raise SecretDecryptionError(
    details={"reason": "invalid_token", "cipher_algo": cipher_algo}
)
```

В `details` попадают только контекст алгоритма/операции — никогда полезная нагрузка.

### 8.2 Различение исключений с учётом времени

`InvalidToken` от `cryptography.fernet` отображается в `SecretDecryptionError`,
тогда как структурные/форматные ошибки — в `SecretIntegrityError`. Это разграничение
позволяет вызывающему коду:
- При `SecretIntegrityError`: расценить как повреждение хранилища; залогировать + оповестить.
- При `SecretDecryptionError`: попробовать следующий fallback-ключ; если все провалились — поднять исключение.

### 8.3 Защита от пустого шифротекста

`_normalize_token` и `_validate_token_shape` отклоняют пустые token-ы ещё до
любой попытки расшифровки. Это предотвращает неявные сбои, при которых пустой
BLOB в базе данных мог бы быть ошибочно интерпретирован как успешная расшифровка
«пустого plaintext».

### 8.4 Валидация Fernet-ключей при запуске

`EnvVaultKeyProvider` валидирует все ключи keyring, конструируя объект `Fernet`
для каждого из них во время `__init__`. Усечённые строки, строки только в hex
или с неверным base64-паддингом немедленно завершаются с `SecretKeyConfigError`,
блокируя запуск процесса.

### 8.5 Энтропия DEK

Новые DEK генерируются как:
```python
dek_plaintext = base64.urlsafe_b64encode(os.urandom(32))
```

- `os.urandom(32)` обеспечивает 256 бит энтропии на уровне ОС.
- `base64.urlsafe_b64encode` производит точный формат, требуемый `Fernet(key)`.
- Полученный DEK никогда не сохраняется в открытом виде — в хранилище попадает только
  результат `Fernet(master_key).encrypt(dek)`.

---

## 9. Таксономия ошибок

**Файл:** [`connector/domain/secrets/errors.py`](../../../../connector/domain/secrets/errors.py)

Все ошибки vault наследуют от `VaultDomainError(RuntimeError)` и несут
строку `code` и словарь `details`.

| Класс исключения | `code` | Возникает когда |
|----------------|--------|-------------|
| `SecretKeyConfigError` | `VAULT_STARTUP_KEY_CONFIG_ERROR` | Неверный/отсутствующий keyring в ENV |
| `SecretIntegrityError` | `SECRET_INTEGRITY_ERROR` | Token повреждён, плохой base64, неверный формат, сбой HMAC не связанный с ключом |
| `SecretDecryptionError` | `SECRET_DECRYPTION_ERROR` | Неверный ключ — Fernet `InvalidToken` при unwrap или decrypt |

### Поля detail ошибок (безопасны для логирования, без утечки секретов)

```python
# SecretKeyConfigError
{
    "env_var": "ANKEY_VAULT_MASTER_KEYS",
    "reason": "empty_keyring" | "invalid_entry_format" | "invalid_fernet_key" | ...,
    "entry_index": 0,          # которая запись не прошла (0-based)
    "key_version": "v1",       # если версия была разобрана
}

# SecretIntegrityError
{
    "reason": "invalid_dek" | "encrypt_failed" | "invalid_base64" |
              "invalid_fernet_envelope" | "invalid_utf8" | "empty_token" |
              "unsupported_algorithm",
    "cipher_algo": "FERNET_V1",
    "context": "ciphertext" | "wrapped_dek",
}

# SecretDecryptionError
{
    "reason": "invalid_token",
    "cipher_algo": "FERNET_V1",  # или "wrap_algo": "FERNET_V1" для DEK unwrap
}
```

---

## 10. Руководство по расширению

### 10.1 Добавление нового алгоритма шифрования

1. Добавить новую константу: `AES_GCM_V1 = "AES_GCM_V1"`.
2. Добавить ветку в каждый метод `FernetEnvelopeCipher` (или создать отдельный класс).
3. Обновить `_ensure_algo` или добавить диспетчеризацию по методам.
4. Сохранить новое значение `cipher_algo` в `VaultSecretRecord.cipher_algo` — существующие
   записи с `FERNET_V1` продолжат корректно расшифровываться через старую ветку.
5. Миграция схемы не требуется (алгоритм хранится per-record).

### 10.2 Добавление нового провайдера ключей

Реализовать `VaultKeyProviderPort` как класс, совместимый с `Protocol`:

```python
class KmsVaultKeyProvider:
    def get_active_key(self) -> VaultMasterKey: ...
    def get_all_keys(self) -> tuple[VaultMasterKey, ...]: ...
    def find_key(self, key_version: str) -> VaultMasterKey | None: ...
```

Подключить его в `VaultContainer` вместо `EnvVaultKeyProvider`. Доменные сервисы
изменений не требуют — они зависят только от интерфейса порта.

### 10.3 Замена Fernet DEK-ом под управлением KMS

Для окружений, где материал DEK никогда не должен покидать Hardware Security Module (HSM):
1. Реализовать `SecretCipherPort.wrap_dek()` / `unwrap_dek()` с вызовом KMS API.
2. Хранимый `wrapped_dek` становится непрозрачным KMS ciphertext blob.
3. `SecretCipherPort.encrypt()` / `decrypt()` по-прежнему используют локальный Fernet
   с `dek_plaintext`, предоставленным KMS и находящимся в памяти только на время операции.

---

## 11. Взаимодействие слоёв

| Слой | Роль |
|-------|------|
| **Доменные порты** (`connector/domain/ports/secrets/`) | Определяют протоколы `SecretCipherPort` и `VaultKeyProviderPort` |
| **Инфра / crypto-адаптеры** (`connector/infra/secrets/`) | `FernetEnvelopeCipher`, `EnvVaultKeyProvider` — конкретные реализации |
| **Доменные сервисы** (`connector/domain/secrets/`) | Используют только порты; оркестрируют encrypt/decrypt через `_ensure_active_dek` + `_unwrap_dek` |
| **Delivery / DI** (`connector/delivery/cli/containers.py`) | Подключает `FernetEnvelopeCipher` и `EnvVaultKeyProvider` как Singleton-ы в `VaultContainer` |

### Направление зависимостей

```
Domain services
     │ depends on (ports only)
     ▼
SecretCipherPort ◄─── FernetEnvelopeCipher  (infra)
VaultKeyProviderPort ◄── EnvVaultKeyProvider  (infra)
     ▲
     │ wires
VaultContainer (delivery)
```

---

## 12. Типичные сценарии

### Сценарий A: Первый запуск, данные vault отсутствуют

1. Вызывается `VaultStartupGuard.ensure_ready()`.
2. Проба не найдена → хранилище доступно для записи → создать пробу.
3. `_ensure_active_dek()` не находит DEK → генерирует DEK → оборачивает активным master key → сохраняет.
4. `cipher.encrypt(probe_payload, dek)` → создаёт шифротекст.
5. `repository.upsert_probe(...)` → сохраняет пробу.
6. `_verify_probe()` → читает пробу → разворачивает DEK → расшифровывает → подтверждает совпадение полезной нагрузки.

### Сценарий B: Обычная запись (секреты уже существуют)

1. Вызывается `SecretVaultWriteService.put_many()`.
2. `get_active_dek()` → находит существующую запись DEK.
3. `_unwrap_dek()` → сначала пробует подсказанный ключ (`wrap_key_version`) → успех.
4. `cipher.encrypt(plaintext, dek_plaintext)` × N полей → N шифротекстов.
5. `repository.upsert_secret(...)` × N → фиксируется в одной транзакции.

### Сценарий C: После ротации master key

1. Старый DEK имеет `wrap_key_version = "v1"`, новый master key — `v2`.
2. `_candidate_master_keys("v1")` → возвращает `[find_key("v1"), ..., key_v2]`.
3. Пробуем `v1` → `SecretDecryptionError` (v1 удалён из keyring) → пробуем следующий.
4. Пробуем `v2` → … тоже провал, если DEK действительно был обёрнут v1, а v1 удалён.
5. **Правильная процедура:** v1 должен оставаться в keyring как fallback до тех пор,
   пока все DEK не будут повторно обёрнуты с v2.

### Сценарий D: Повреждённый шифротекст в хранилище

1. Вызывается `cipher.decrypt()` с повреждённым token.
2. `_validate_token_shape()` → декодирование base64 не удаётся → `SecretIntegrityError(reason="invalid_base64")`.
3. Вызывающий код (`SecretVaultReadService`) повторно поднимает `SecretIntegrityError`.
4. Вышестоящий слой фиксирует ошибку, не выполняет повтор.

---

## 13. Важные детали реализации

### 13.1 Бинарный формат Fernet Token

```
[version: 1 byte = 0x80]
[timestamp: 8 bytes, big-endian UNIX seconds]
[IV: 16 bytes, random]
[ciphertext: PKCS7-padded AES-128-CBC, variable]
[HMAC-SHA256: 32 bytes, over version+timestamp+IV+ciphertext]
```

Всё закодировано в urlsafe base64. Накладные расходы по сравнению с plaintext:
~56 байт до base64, плюс PKCS7-паддинг plaintext.

### 13.2 Повторное использование DEK для нескольких полей

В рамках одного вызова `put_many()` все поля используют один и тот же активный DEK:

```python
with self._repository.transaction():
    active_master_key = self._key_provider.get_active_key()
    dek_record, dek_plaintext = self._ensure_active_dek(...)
    for field, plaintext in secrets.items():
        ciphertext = cipher.encrypt(plaintext=plaintext, dek_plaintext=dek_plaintext, ...)
        repository.upsert_secret(VaultSecretRecord(..., dek_version=dek_record.dek_version))
```

`dek_plaintext` существует только в стековом фрейме `put_many()`. Он никогда
не присваивается атрибуту экземпляра и не сохраняется.

### 13.3 Версия алгоритма проставляется per-record

`cipher_algo` и `wrap_algo` хранятся как строковые колонки в `vault_secrets`
и `vault_dek`. Это означает перспективную идентификацию алгоритма per-record:
старые записи продолжают корректно расшифровываться после обновления шифра, потому что
хранимое значение управляет диспетчеризацией, а не глобальный флаг конфигурации.

### 13.4 `SecretKeyConfigError` vs `SecretIntegrityError`

Эти два типа ошибок служат разным диагностическим целям:

| Ошибка | Означает | Действие оператора |
|-------|-------|-----------------|
| `SecretKeyConfigError` | Keyring неверно настроен — плохая ENV-переменная | Исправить `ANKEY_VAULT_MASTER_KEYS` и перезапустить |
| `SecretIntegrityError` | Шифротекст или структура DEK недействительны | Исследовать повреждение хранилища; проверить резервную копию |
| `SecretDecryptionError` | Использован неверный ключ | Убедиться, что версия ключа присутствует в keyring |

---

## 14. Контракты и границы

| Граница | Входные данные | Выходные данные | Ошибки |
|---------|-------|--------|--------|
| `cipher.encrypt()` | `plaintext: str`, `dek_plaintext: bytes`, `cipher_algo: str` | `bytes` Fernet token | `SecretIntegrityError` |
| `cipher.decrypt()` | `ciphertext: bytes\|str`, `dek_plaintext: bytes`, `cipher_algo: str` | `str` plaintext | `SecretDecryptionError`, `SecretIntegrityError` |
| `cipher.wrap_dek()` | `dek_plaintext: bytes`, `master_key: str`, `wrap_algo: str` | `bytes` wrapped DEK | `SecretKeyConfigError`, `SecretIntegrityError` |
| `cipher.unwrap_dek()` | `wrapped_dek: bytes\|str`, `master_key: str`, `wrap_algo: str` | `bytes` DEK plaintext | `SecretDecryptionError`, `SecretIntegrityError` |
| `key_provider.get_active_key()` | — | `VaultMasterKey` | Никогда не бросает (предварительно валидирован) |
| `key_provider.find_key(ver)` | `key_version: str` | `VaultMasterKey \| None` | Никогда не бросает |
| `EnvVaultKeyProvider.__init__()` | ENV `ANKEY_VAULT_MASTER_KEYS` | валидированный keyring | `SecretKeyConfigError` |

---

## 15. Характеристики производительности

### 15.1 Стоимость Fernet-шифрования

| Операция | Стоимость CPU | Примечания |
|-----------|----------|-------|
| `encrypt(plaintext, dek)` | ~50–200 µs | Блочный шифр AES-128-CBC + HMAC-SHA256 |
| `decrypt(ciphertext, dek)` | ~50–200 µs | Проверка HMAC + расшифровка AES-128-CBC |
| `wrap_dek(dek, master_key)` | ~50–200 µs | То же, что encrypt (DEK ~44 байта) |
| `unwrap_dek(wrapped, master_key)` | ~50–200 µs | То же, что decrypt |
| `build_key_fingerprint(key)` | ~5 µs | sha256 от salt + текст ключа |

Стоимость определяется вычислением HMAC-SHA256, а не AES. На современном оборудовании
(CPU 2 ГГц) пропускная способность составляет приблизительно 5 000–20 000 операций в секунду
на ядро для типичных размеров полей данных сотрудника (< 256 байт).

### 15.2 Накладные расходы провайдера ключей

`EnvVaultKeyProvider` — Singleton: вся валидация и разбор ключей выполняются однократно
при запуске контейнера:

```python
# При запуске (однократно):
raw = os.environ.get("ANKEY_VAULT_MASTER_KEYS")
keys = parse_master_keyring(raw)   # O(N) где N = количество ключей

# В рантайме (за операцию):
active_key = provider.get_active_key()    # O(1) — предварительно вычислено
found_key = provider.find_key("v1")      # O(1) — поиск в dict
```

Keyring неизменяем после конструирования — без блокировок, без конкуренции.

### 15.3 Производительность многопольной записи

В `put_many()` DEK загружается/разворачивается **один раз** за вызов, а не за поле:

```python
dek_record, dek_plaintext = self._ensure_active_dek(...)  # One DEK load
for field, plaintext in secrets.items():
    ciphertext = cipher.encrypt(plaintext=plaintext, dek_plaintext=dek_plaintext, ...)
    # DEK reused — no DEK lookup per field
```

Стоимость масштабируется как `O(1)` операций с DEK + `O(N)` операций encrypt для N полей.

---

## 16. Инварианты крипто-гибкости

Текущая реализация спроектирована для миграции алгоритмов:

### 16.1 Метки алгоритма per-record

Каждый `VaultSecretRecord` хранит `cipher_algo` и `key_version`:
```
vault_secrets:  cipher_algo="FERNET_V1", key_version="v1", dek_version="dek_abc"
vault_dek:      wrap_algo="FERNET_V1",   wrap_key_version="v1"
```

Это означает, что старые записи могут расшифровываться старым алгоритмом даже после
введения нового, поскольку алгоритм проставлен на каждой записи.

### 16.2 Паттерн диспетчеризации алгоритмов

```python
# Текущий вариант (в FernetEnvelopeCipher.decrypt):
def decrypt(self, *, ciphertext, dek_plaintext, cipher_algo):
    _ensure_algo(cipher_algo, expected="FERNET_V1", algo_kind="cipher")
    ...

# Будущий паттерн диспетчеризации нескольких алгоритмов:
def decrypt(self, *, ciphertext, dek_plaintext, cipher_algo):
    if cipher_algo == "FERNET_V1":
        return self._decrypt_fernet_v1(ciphertext, dek_plaintext)
    elif cipher_algo == "AES_GCM_V1":
        return self._decrypt_aes_gcm_v1(ciphertext, dek_plaintext)
    else:
        raise SecretIntegrityError(details={"reason": "unsupported_algorithm"})
```

### 16.3 Независимость версий ключей

Версии master key (`"v1"`, `"v2"`) полностью независимы от версий алгоритма шифрования
(`"FERNET_V1"`). Ротация ключей не подразумевает смену алгоритма,
а обновление алгоритма не делает существующие версии ключей недействительными.

---

## 17. Соображения по тестированию

### 17.1 Генерация тестовых ключей

```python
from cryptography.fernet import Fernet

# Сгенерировать валидный тестовый ключ:
key = Fernet.generate_key().decode()  # e.g. "AAAA...=="

# Формат для ENV-переменной:
env_value = f"testkey1:{key}"
os.environ["ANKEY_VAULT_MASTER_KEYS"] = env_value
```

### 17.2 Проверка формы token в тестах

```python
from cryptography.fernet import Fernet
import base64

key = Fernet.generate_key()
fernet = Fernet(key)
token = fernet.encrypt(b"test_secret")

# Verify structure:
decoded = base64.urlsafe_b64decode(token + b"=" * (-len(token) % 4))
assert decoded[0] == 0x80          # Fernet version byte
assert len(decoded) >= 9 + 16 + 32  # version + timestamp + IV + HMAC minimum
```

### 17.3 Тестовый дублёр для `SecretCipherPort`

```python
class PlaintextCipher:
    """Test-only cipher that stores plaintext as-is (NEVER use in production)."""
    def encrypt(self, *, plaintext, dek_plaintext, cipher_algo): return plaintext.encode()
    def decrypt(self, *, ciphertext, dek_plaintext, cipher_algo):
        return ciphertext.decode() if isinstance(ciphertext, bytes) else ciphertext
    def wrap_dek(self, *, dek_plaintext, master_key, wrap_algo): return dek_plaintext
    def unwrap_dek(self, *, wrapped_dek, master_key, wrap_algo):
        return wrapped_dek if isinstance(wrapped_dek, bytes) else wrapped_dek.encode()
```

### 17.4 Тестовый дублёр для `VaultKeyProviderPort`

```python
from connector.domain.ports.secrets.key_provider import VaultMasterKey

class FixedKeyProvider:
    def __init__(self, key_material: str, version: str = "test_v1"):
        self._key = VaultMasterKey(key_version=version, key_material=key_material, is_active=True)

    def get_active_key(self) -> VaultMasterKey: return self._key
    def get_all_keys(self) -> tuple[VaultMasterKey, ...]: return (self._key,)
    def find_key(self, key_version: str) -> VaultMasterKey | None:
        return self._key if key_version == self._key.key_version else None
```

---

## 18. Справочник по режимам сбоев

### 18.1 Режимы сбоев криптографического слоя

| Сбой | Первопричина | Поднимается в | Устранение |
|---------|-----------|-----------|------------|
| `SecretKeyConfigError(reason="empty_keyring")` | `ANKEY_VAULT_MASTER_KEYS` не задан или пустой | `parse_master_keyring()` | Задать ENV-переменную с валидным ключом |
| `SecretKeyConfigError(reason="invalid_fernet_key")` | Материал ключа не является валидным base64-32-bytes | `_validate_fernet_key()` | Перегенерировать ключ с `Fernet.generate_key()` |
| `SecretKeyConfigError(reason="duplicate_key_version")` | Две записи с одинаковой строкой версии | `parse_master_keyring()` | Обеспечить уникальность имён версий |
| `SecretIntegrityError(reason="invalid_dek")` | `dek_plaintext` не является валидным Fernet-ключом | `_build_fernet_from_dek()` | Повреждение DEK — проверить таблицу vault_dek |
| `SecretIntegrityError(reason="invalid_base64")` | Блоб шифротекста повреждён в БД | `_validate_token_shape()` | Повреждение хранилища; исследовать резервную копию |
| `SecretIntegrityError(reason="invalid_fernet_envelope")` | Декодированные байты не начинаются с 0x80 | `_validate_token_shape()` | Повреждение хранилища или неверный алгоритм |
| `SecretDecryptionError(reason="invalid_token")` | Неверный master key для DEK unwrap | `unwrap_dek()` → Fernet поднимает `InvalidToken` | Убедиться, что версия ключа присутствует в keyring |
| `SecretIntegrityError(reason="decrypt_failed")` | Неожиданное исключение во время decrypt | `decrypt()` | Общий сбой; проверить логи для выяснения причины |

### 18.2 Режимы сбоев провайдера ключей

| Сбой | Первопричина | Устранение |
|---------|-----------|------------|
| Процесс завершается сразу при запуске | `parse_master_keyring` поднимает `SecretKeyConfigError` | Исправить `ANKEY_VAULT_MASTER_KEYS` |
| DEK unwrap проваливается со всеми кандидатами | Keyring не содержит ключ, которым был обёрнут DEK | Добавить недостающую версию ключа обратно в keyring |
| `SecretDecryptionError` каскадирует в `SecretStoreError` | Сервис записи перехватывает и повторно оборачивает | Проверить `details.reason` для разграничения сбоя DEK и секрета |

---

## 19. Часто задаваемые вопросы

### Q: Почему используется Fernet как для оборачивания DEK, так и для шифрования секретов (один алгоритм для обоих)?

Fernet выбран потому что:
1. Это схема **аутентифицированного шифрования** — HMAC-SHA256 обеспечивает целостность
   в дополнение к конфиденциальности, устраняя классы атак padding oracle и bit-flipping.
2. Библиотека `cryptography` уже является продуктовой зависимостью с сильной поддержкой.
3. Использование одного алгоритма для обеих операций сокращает количество примитивов и
   упрощает аудиты безопасности.
4. Встраивание временно́й метки в Fernet не создаёт проблем — метка не чувствительна
   с точки зрения безопасности и не принудительна (мы не передаём `time_valid` в Fernet).

### Q: Почему DEK генерируется как `base64.urlsafe_b64encode(os.urandom(32))`, а не как `Fernet.generate_key()`?

`Fernet.generate_key()` также производит `base64.urlsafe_b64encode(os.urandom(32))` — это
идентичные операции. Явная форма используется в кодовой базе, чтобы в комментариях
чётко документировать конструкцию. Обе формы производят валидный Fernet-ключ.

### Q: Может ли DEK быть тем же, что и master key?

Технически оба используют один формат (оба являются Fernet-ключами), но они служат разным ролям:
- **Master key**: долгоживущий, ротируется нечасто, хранится только в окружении.
- **DEK**: среднеживущий, хранится в базе данных vault (в зашифрованном виде), может ротироваться свободнее.

Использование одного ключа для обоих устранило бы преимущество конвертного шифрования —
разделение иерархии ключей является архитектурным инвариантом.

### Q: Что произойдёт, если `ANKEY_VAULT_MASTER_KEYS` изменится во время работы?

`EnvVaultKeyProvider` — Singleton, он читает ENV-переменную **один раз** при запуске
контейнера. Изменения переменной окружения после запуска не имеют эффекта до
перезапуска процесса. Это намеренно: смена ключей требует явного перезапуска,
чтобы валидация startup guard выполнялась с новым keyring.

### Q: Можно ли вызвать `encrypt()` без DEK (прямое шифрование master key)?

Нет. Дизайн `SecretCipherPort` требует DEK для каждого вызова `encrypt()`.
Прямое шифрование master key нарушило бы конвертную модель и предотвратило бы:
1. Эффективную ротацию ключей (потребовалось бы перешифрование всех секретов, а не только DEK).
2. Независимое управление жизненным циклом DEK.

### Q: Используется ли временна́я метка Fernet в token для принудительного TTL?

Нет. Vault не использует встроенный параметр `max_age` / TTL Fernet.
`fernet.decrypt(token)` вызывается без аргумента `ttl`, поэтому встроенная
временна́я метка игнорируется в целях истечения срока. Будущее принудительное TTL
(при необходимости) будет реализовано на прикладном уровне через `created_at` / `ttl_seconds`
в метаданных `VaultSecretRecord`, а не через TTL Fernet token.

### Q: Каков риск, если `key_material` утечёт в строку лога?

Если материал master key (поле `key_material` у `VaultMasterKey`) окажется в логах,
злоумышленник с доступом к логам сможет:
1. Развернуть (unwrap) все DEK (прочитав `vault_dek.wrapped_dek` и объединив с утёкшим ключом).
2. Расшифровать все секреты (прочитав `vault_secrets.ciphertext` + развёрнутые DEK).

Именно поэтому `key_material` никогда не появляется в `details` исключений или полях
`structlog` ни в каком из кодов vault. Все детали ошибок используют `key_version`
(нечувствительную строку) вместо этого.

---

## 20. Сводка инвариантов

Криптографический слой всегда поддерживает следующие инварианты:

| Инвариант | Обеспечивается |
|-----------|------------|
| `key_material` никогда в логах или исключениях | `FernetEnvelopeCipher`, `EnvVaultKeyProvider` — в details только `key_version` |
| Plaintext-секрет никогда в логах или исключениях | `SecretVaultWriteService`, `SecretVaultReadService` — в details только locator/reason |
| `dek_plaintext` никогда не сохраняется | Оба сервиса — присваивается только локальной переменной, не атрибуту экземпляра |
| Идентичность алгоритма должна быть явной | `_ensure_algo()` отклоняет любое значение, отличное от `FERNET_V1` |
| Неверные token-ы отклоняются до вызова Fernet | `_validate_token_shape()` при каждом decrypt/unwrap |
| Пустой шифротекст отклоняется | `_normalize_token()` до `_validate_token_shape()` |
| Уникальность версий ключей принудительна | `parse_master_keyring()` ведёт множество `seen_versions` |
| Активный ключ всегда keyring[0] | `EnvVaultKeyProvider.__init__` устанавливает `is_active=index==0` |
| Валидность Fernet-ключей проверяется при запуске | `_validate_fernet_key()` для каждой записи keyring |
| Энтропия DEK из случайности ОС | `os.urandom(32)` — не модуль `random` |

---

## 21. Vault-Management Crypto Lifecycle (DEC-002)

### 21.1 Managed keyring storage contract

`VaultManagedEnvKeyringStore` хранит keyring в managed env-файле формата:

```dotenv
ANKEY_VAULT_MASTER_KEYS=mk_2026_03_07:<fernet_key>
```

Крипто-важные свойства:
- сохраняется только `key_version:key_material` (без plaintext секретов/DEK);
- запись атомарна: `tmp -> fsync(file) -> rename -> fsync(dir)`;
- права файла принудительно `0600`;
- lifecycle-операции сериализуются через `flock`.

### 21.2 Single-key steady-state и bridge keyring

В steady-state keyring содержит ровно один active master key.

Во время `rotate` допустимо временное состояние `bridge keyring` (`new,old`) для crash-safe протокола:
1. Сохранить `bridge keyring`.
2. Rewrap всех DEK на `new`.
3. Финализировать keyring до `new only`.
4. Выполнить `VaultStartupGuard` post-verify.

Если процесс прерван до шага 3, `run-maintenance` обнаруживает bridge и завершает safe-finalization.

### 21.3 Runtime source precedence

Crypto runtime читает ключи через `EnvVaultKeyProvider`, поэтому эффективный источник всегда:
1. `ANKEY_VAULT_MASTER_KEYS` в runtime env (если задан и валиден),
2. иначе managed env-файл подгружается в runtime env при startup.

Это сохраняет единый криптографический read-path и исключает fork логики для разных keyring источников.

### 21.4 Password gate и криптографическая проверка

`VaultAdminPasswordGate` не шифрует данные vault и не участвует в DEK/master key операциях.
Его зона ответственности:
- верификация доступа к manual lifecycle-операциям;
- проверка plaintext password против argon2id hash из ENV;
- отсутствие утечки `password/password_hash` в logs/errors.

---

## 22. Связанные документы

- [vault-core.md](vault-core.md) — Поток pipeline: как сервисы write/read подключаются к
  `SecretStoreProtocol` и `SecretProviderProtocol`
- [vault-storage.md](vault-storage.md) — Где `ciphertext`, `wrapped_dek` и
  `key_version` размещаются в схеме SQLite
- [vault-delivery.md](vault-delivery.md) — DI-проводка `VaultContainer` и
  поток крипто-валидации `VaultStartupGuard`

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-27 | Создан документ Vault Cryptography | xORex-LC |
| 2026-03-07 | Добавлен раздел DEC-002: managed keyring lifecycle, bridge protocol и runtime precedence | xORex-LC |
