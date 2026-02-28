# Vault Layer — Хранилище: SQLite Repository

> **Область применения:** Данный документ описывает слой хранилища vault — что представляет собой база данных vault,
> её schema, CRUD-интерфейс repository, модель транзакций, scoping по run_id и
> сопоставление ошибок.
>
> **Связанные документы:**
> - [vault-core.md](vault-core.md) — доменный поток конвейера (enrich → plan → apply)
> - [vault-crypto.md](vault-crypto.md) — конвертная шифровка, жизненный цикл DEK, провайдер ключей
> - [vault-delivery.md](vault-delivery.md) — доменные сервисы, политики и DI-проводка

---

## 1. Обзор

Vault — это **выделенная база данных SQLite**, которая хранит зашифрованные секреты независимо
от основной базы данных кэша. Её основное назначение — сохранять пары `(locator_hash, ciphertext)`
— зашифрованные поля данных сотрудников — между запусками ETL-конвейера.

Файл базы данных vault расположен по пути:
```
<cache_dir>/ankey_vault.sqlite3
```

Он отделён от основного кэша (`ankey_cache.sqlite3`) и базы данных идентификаторов
(`ankey_identity.sqlite3`). У каждой из них собственный жизненный цикл `SqliteEngine`.

### Что хранит vault

| Содержимое | Таблица | Ключевые столбцы |
|---------|-------|-------------|
| Зашифрованные секреты | `vault_secrets` | `dataset`, `field`, `locator_hash`, `run_id`, `ciphertext` |
| Обёрнутые DEK | `vault_dek` | `dek_version`, `wrapped_dek`, `wrap_key_version`, `is_active` |
| Стартовый проверочный зонд | `vault_probe` | `probe_name`, `ciphertext` |
| Метаданные версии schema | `vault_meta` | `key="schema_version"` |

---

## 2. Доменные модели

**Файл:** [`connector/domain/secrets/models.py`](../../../../connector/domain/secrets/models.py)

Все три модели являются замороженными датаклассами — неизменяемыми объектами-значениями без поведения.
Доменный слой никогда не присваивает открытый текст ни одному полю этих моделей.

### 2.1 `VaultSecretRecord`

```python
@dataclass(frozen=True)
class VaultSecretRecord:
    dataset: str          # Dataset identifier (e.g. "hr")
    field: str            # Field name (e.g. "password")
    locator_hash: str     # sha256 of canonical locator (see vault-delivery.md §3.1)
    locator_version: str  # Locator algorithm version (currently "v1")
    ciphertext: bytes | str  # Fernet-encrypted secret token
    cipher_algo: str      # Algorithm identifier: "FERNET_V1"
    key_version: str      # Master key version used to wrap the DEK
    dek_version: str      # DEK version (foreign key → vault_dek.dek_version)
    run_id: str | None    # ETL run scope; None = global (cross-run)
    created_at: str       # ISO 8601 UTC timestamp
    updated_at: str       # ISO 8601 UTC timestamp
    secret_id: int | None = None  # Auto-assigned by storage on read
```

**Инварианты:**
- `ciphertext` всегда является непрозрачным зашифрованным blob — никогда не строкой в открытом виде.
- `key_version` хранится исключительно в диагностических целях; реальный ключ ищется
  криптографическим слоем через `VaultKeyProviderPort.find_key(key_version)`.
- `run_id = None` обозначает глобальный scope (доступный для любого run_id-запроса через fallback).

### 2.2 `VaultDekRecord`

```python
@dataclass(frozen=True)
class VaultDekRecord:
    dek_version: str       # Unique DEK identifier (e.g. "dek_<uuid_hex>")
    wrapped_dek: bytes | str  # Fernet(master_key).encrypt(dek_plaintext)
    wrap_algo: str         # Wrap algorithm identifier: "FERNET_V1"
    wrap_key_version: str  # Which master key wrapped this DEK
    is_active: bool        # True = this DEK is used for new writes
    created_at: str
    updated_at: str
```

**Инварианты:**
- `wrapped_dek` непрозрачен — открытый текст DEK никогда не появляется в этой записи.
- В любой момент времени должна существовать не более **одной** строки с `is_active=True` (обеспечивается
  `upsert_dek()`, который атомарно деактивирует остальные).
- Старые неактивные записи DEK **никогда не удаляются** — они остаются для чтения
  секретов, зашифрованных с помощью предыдущих DEK.

### 2.3 `VaultProbeRecord`

```python
@dataclass(frozen=True)
class VaultProbeRecord:
    probe_name: str        # Fixed: "vault.system.healthcheck"
    ciphertext: bytes | str  # Fernet(DEK).encrypt("vault_startup_probe_v1")
    cipher_algo: str       # "FERNET_V1"
    key_version: str       # Master key version at probe creation time
    dek_version: str       # DEK used for this probe
    created_at: str
    updated_at: str
```

Зонд — это служебная запись, создаваемая при первом запуске, которая позволяет
`VaultStartupGuard` проверить доступность ключей и целостность хранилища до
того, как будут записаны реальные секреты.

---

## 3. Контракт порта: `SecretVaultRepositoryPort`

**Файл:** [`connector/domain/ports/secrets/repository.py`](../../../../connector/domain/ports/secrets/repository.py)

```python
class SecretVaultRepositoryPort(Protocol):
    def transaction(self) -> ContextManager[None]: ...
    def upsert_secret(self, record: VaultSecretRecord) -> None: ...
    def get_secret(self, *, dataset, field, locator_hash, locator_version, run_id) -> VaultSecretRecord | None: ...
    def delete_secret(self, *, dataset, field, locator_hash, locator_version, run_id) -> int: ...
    def upsert_dek(self, record: VaultDekRecord) -> None: ...
    def get_dek(self, *, dek_version: str) -> VaultDekRecord | None: ...
    def get_active_dek(self) -> VaultDekRecord | None: ...
    def upsert_probe(self, record: VaultProbeRecord) -> None: ...
    def get_probe(self, *, probe_name: str) -> VaultProbeRecord | None: ...
```

Порт является `Protocol` (структурная типизация). `SqliteVaultRepository` —
единственная production-реализация. Порт позволяет легко создавать тестовые дублёры
без SQLite.

---

## 4. SQLite Schema

**Файл:** [`connector/infra/secrets/sqlite/schema.py`](../../../../connector/infra/secrets/sqlite/schema.py)

Текущая `SCHEMA_VERSION = 1`.

### 4.1 `vault_meta`

```sql
CREATE TABLE IF NOT EXISTS vault_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
)
```

Хранилище ключ-значение специального назначения. В настоящее время содержит одну строку:
```
key="schema_version", value="1"
```

Используется функцией `ensure_vault_schema()` для определения необходимости DDL-миграций.

### 4.2 `vault_dek`

```sql
CREATE TABLE IF NOT EXISTS vault_dek (
    dek_version      TEXT PRIMARY KEY,
    wrapped_dek      BLOB NOT NULL,
    wrap_algo        TEXT NOT NULL,
    wrap_key_version TEXT NOT NULL,
    is_active        INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
)
```

| Столбец | Тип | Описание |
|--------|------|-------------|
| `dek_version` | `TEXT PRIMARY KEY` | Уникальный идентификатор на основе UUID (`dek_<uuid_hex>`) |
| `wrapped_dek` | `BLOB` | Байты DEK, обёрнутые Fernet |
| `wrap_algo` | `TEXT` | Алгоритм обёртки (`"FERNET_V1"`) |
| `wrap_key_version` | `TEXT` | Версия мастер-ключа, которым обёрнут данный DEK |
| `is_active` | `INTEGER 0|1` | Ограничение CHECK предотвращает некорректные значения |
| `created_at` | `TEXT` | ISO 8601 UTC (хранится как строка) |
| `updated_at` | `TEXT` | ISO 8601 UTC |

**Индекс:**
```sql
CREATE INDEX IF NOT EXISTS idx_vault_dek_active
ON vault_dek(is_active, updated_at)
```

Оптимизирует `get_active_dek()` — упорядочивание по `(is_active=1, updated_at DESC)`.

### 4.3 `vault_secrets`

```sql
CREATE TABLE IF NOT EXISTS vault_secrets (
    secret_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset        TEXT NOT NULL,
    field          TEXT NOT NULL,
    locator_hash   TEXT NOT NULL,
    locator_version TEXT NOT NULL,
    run_id         TEXT,                  -- NULL = global scope
    ciphertext     BLOB NOT NULL,
    cipher_algo    TEXT NOT NULL,
    key_version    TEXT NOT NULL,
    dek_version    TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    FOREIGN KEY (dek_version) REFERENCES vault_dek(dek_version)
)
```

| Столбец | Описание |
|--------|-------------|
| `secret_id` | Автоинкрементный PK для упорядочивания внутри одного locator-scope |
| `dataset` | Идентификатор датасета (например, `"hr"`, `"employees"`) |
| `field` | Имя поля внутри датасета (например, `"password"`, `"pin"`) |
| `locator_hash` | `sha256(locator)` — детерминированный адрес секрета |
| `locator_version` | `"v1"` — версия алгоритма locator |
| `run_id` | Идентификатор ETL-запуска или `NULL` для глобального scope |
| `ciphertext` | Fernet-токен (BLOB) |
| `cipher_algo` | `"FERNET_V1"` — штамп алгоритма на уровне записи |
| `key_version` | Версия мастер-ключа на момент записи (для диагностики) |
| `dek_version` | Ссылается на `vault_dek.dek_version` |

**Уникальный индекс (scope для upsert):**
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_vault_secret_unique_scope
ON vault_secrets(dataset, field, locator_version, locator_hash, COALESCE(run_id, ''))
```

`COALESCE(run_id, '')` делает NULL и пустую строку эквивалентными для уникальности —
только одна запись глобального scope может существовать для комбинации `(dataset, field, locator)`.

**Индекс поиска:**
```sql
CREATE INDEX IF NOT EXISTS idx_vault_secret_lookup
ON vault_secrets(dataset, field, locator_version, locator_hash, run_id)
```

Оптимизирует запросы `get_secret()`, фильтрующие по всем пяти столбцам.

### 4.4 `vault_probe`

```sql
CREATE TABLE IF NOT EXISTS vault_probe (
    probe_name   TEXT PRIMARY KEY,
    ciphertext   BLOB NOT NULL,
    cipher_algo  TEXT NOT NULL,
    key_version  TEXT NOT NULL,
    dek_version  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
)
```

Таблица с одной строкой (ключ — `probe_name = "vault.system.healthcheck"`). Запись зонда
создаётся один раз при первом запуске и обновляется каждый раз, когда `VaultStartupGuard`
создаёт новый зонд (после повторной инициализации или ротации DEK).

### 4.5 Диаграмма сущностей

```
vault_meta
  key, value

vault_dek
  dek_version (PK) ◄──────────────────────────────────────────┐
  wrapped_dek, wrap_algo, wrap_key_version, is_active           │  FK
  created_at, updated_at                                        │
                                                                │
vault_secrets                                                   │
  secret_id (PK AUTOINCREMENT)                                  │
  dataset, field, locator_hash, locator_version, run_id (UNIQUE)│
  ciphertext, cipher_algo, key_version                          │
  dek_version ──────────────────────────────────────────────────┘
  created_at, updated_at

vault_probe
  probe_name (PK)
  ciphertext, cipher_algo, key_version, dek_version
  created_at, updated_at
```

---

## 5. `SqliteVaultRepository` — Реализация

**Файл:** [`connector/infra/secrets/sqlite/repository.py`](../../../../connector/infra/secrets/sqlite/repository.py)

```python
class SqliteVaultRepository(SecretVaultRepositoryPort):
    def __init__(self, engine: SqliteEngine): ...
```

Repository оборачивает экземпляр `SqliteEngine`. Он не владеет жизненным циклом engine —
этим управляет ресурс `SqliteContainer.vault_ready`.

### 5.1 `transaction()`

```python
@contextmanager
def transaction(self) -> Iterator[None]:
    with self._engine.transaction(mode="immediate"):
        yield
```

**Открывает `BEGIN IMMEDIATE`** — немедленно получает блокировку записи, предотвращая вход
других писателей. Это критически важно для атомарного паттерна активации DEK + запись секрета
в `SecretVaultWriteService.put_many()`.

**Защиты:**
- Вложенная transaction → `RuntimeError("Nested vault transactions are not supported")`.
- Ошибка SQLite во время `BEGIN` → `SecretStoreError` (сопоставляется через `_map_store_error`).

### 5.2 `upsert_secret(record: VaultSecretRecord)`

```sql
INSERT INTO vault_secrets(dataset, field, locator_hash, locator_version, run_id,
    ciphertext, cipher_algo, key_version, dek_version, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT DO UPDATE SET
    ciphertext = excluded.ciphertext,
    cipher_algo = excluded.cipher_algo,
    key_version = excluded.key_version,
    dek_version = excluded.dek_version,
    updated_at = excluded.updated_at
```

Целью `ON CONFLICT` является уникальный индекс
`(dataset, field, locator_version, locator_hash, COALESCE(run_id,''))`.

При конфликте обновляются только крипто-столбцы — locator и
`created_at` остаются неизменными. Это делает upsert идемпотентным для повторных запусков приёма данных.

### 5.3 `get_secret(...)` — Scoping по run_id

Запрос чтения реализует **двухуровневый приоритет run_id**:

```
Порядок поиска:
  1. Точное совпадение run_id (секрет с run-scope)
  2. NULL run_id (секрет с глобальным scope)
  → Возвращает первую совпадающую строку по этому приоритету.
```

**Когда `run_id` задан:**
```sql
SELECT ...
FROM vault_secrets
WHERE dataset = ?
  AND field = ?
  AND locator_hash = ?
  AND locator_version = ?
  AND (run_id = ? OR run_id IS NULL)     -- exact OR global
ORDER BY
  CASE WHEN run_id = ? THEN 0 ELSE 1 END,  -- exact before global
  updated_at DESC,                           -- most recent first
  secret_id DESC                             -- stable tiebreak
LIMIT 1
```

**Когда `run_id` равен `None`:**
```sql
SELECT ...
FROM vault_secrets
WHERE dataset = ?
  AND field = ?
  AND locator_hash = ?
  AND locator_version = ?
  AND run_id IS NULL    -- global scope only
ORDER BY updated_at DESC, secret_id DESC
LIMIT 1
```

### 5.4 `delete_secret(...)` — Удаление с учётом scope

Удаляет по полному locator-scope:

```sql
-- run_id provided:
DELETE FROM vault_secrets
WHERE dataset = ? AND field = ? AND locator_hash = ?
  AND locator_version = ? AND run_id = ?

-- run_id = None:
DELETE FROM vault_secrets
WHERE dataset = ? AND field = ? AND locator_hash = ?
  AND locator_version = ? AND run_id IS NULL
```

Возвращает `int` — количество удалённых строк (0, если не найдено; в норме 1).

### 5.5 `upsert_dek(record: VaultDekRecord)`

Upsert DEK содержит встроенную **гарантию атомарности** с использованием `autobegin`:

```python
with self._engine.autobegin():
    # Step 1: Deactivate all other active DEKs
    UPDATE vault_dek SET is_active = 0, updated_at = ?
    WHERE is_active = 1 AND dek_version != ?

    # Step 2: Upsert the new DEK record
    INSERT INTO vault_dek(...)
    ON CONFLICT(dek_version) DO UPDATE SET ...
```

Это гарантирует, что в любой момент существует только один активный DEK. При гонке нескольких
записей `BEGIN IMMEDIATE` SQLite в охватывающей transaction (вызываемой `VaultStartupGuard`
и `SecretVaultWriteService`) предотвращает одновременные вызовы upsert_dek.

### 5.6 `get_active_dek()`

```sql
SELECT ...
FROM vault_dek
WHERE is_active = 1
ORDER BY updated_at DESC, dek_version DESC
LIMIT 1
```

Возвращает наиболее недавно обновлённый активный DEK. В нормальной работе существует ровно
один активный DEK. `ORDER BY` обеспечивает стабильный результат, даже если `is_active=1`
каким-то образом имеет несколько строк (защитное упорядочивание).

### 5.7 `get_dek(dek_version)`

```sql
SELECT ... FROM vault_dek WHERE dek_version = ? LIMIT 1
```

Прямой поиск по версии. Используется в пути чтения, когда известен `dek_version` записи секрета.
Не фильтрует по `is_active` — допускает чтение неактивных (исторических) DEK.

### 5.8 `upsert_probe(record: VaultProbeRecord)`

```sql
INSERT INTO vault_probe(probe_name, ciphertext, cipher_algo, key_version,
    dek_version, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(probe_name) DO UPDATE SET
    ciphertext = excluded.ciphertext, ...
```

Всегда выполняет upsert по `probe_name`. Если зонд уже существует, он перезаписывается
новым шифрованием (происходит при ротации ключа/DEK).

### 5.9 `get_probe(probe_name)`

```sql
SELECT ... FROM vault_probe WHERE probe_name = ? LIMIT 1
```

Возвращает запись зонда или `None`, если vault никогда не был инициализирован.

---

## 6. Модель транзакций

### 6.1 Путь записи (секреты)

```
SecretVaultWriteService.put_many()
  └─ repository.transaction()           ← BEGIN IMMEDIATE
       ├─ key_provider.get_active_key()  (no I/O)
       ├─ _ensure_active_dek()
       │    ├─ repository.get_active_dek()   ← SELECT
       │    └─ (if None) repository.upsert_dek(...)  ← INSERT/UPDATE
       └─ for field, plaintext in secrets:
            ├─ locator.build_locator_hash(...)  (no I/O)
            ├─ cipher.encrypt(...)              (no I/O)
            └─ repository.upsert_secret(...)    ← INSERT/UPDATE
     END (implicit commit on context manager exit)
```

Все операции одного вызова `put_many()` выполняются в рамках единственной транзакции `IMMEDIATE`.

### 6.2 Стартовый зонд (guard)

```
VaultStartupGuard.ensure_ready()
  ├─ key_provider.get_active_key()          (no I/O)
  ├─ storage_probe.is_readonly()            (SqliteEngine method)
  ├─ repository.get_probe(probe_name)       ← SELECT (autobegin/read)
  └─ (if None, not readonly) _create_probe()
       ├─ _ensure_active_dek()
       │    └─ repository.upsert_dek(...)   ← autobegin write
       └─ repository.upsert_probe(...)      ← autobegin write
  └─ _verify_probe()                        (read + decrypt, no writes)
```

Создание зонда НЕ использует `transaction()` (без `BEGIN IMMEDIATE`). Каждый
вызов `upsert_dek` / `upsert_probe` использует `execute_with_retry` в режиме autobegin.
Это намеренно: запуск — операция однопроцессная.

### 6.3 Удержание (delete)

```
VaultRetentionService.on_apply_success()
  └─ for field in secret_fields:
       ├─ locator.build_locator_hash(...)
       └─ repository.delete_secret(...)     ← autobegin write, per-field
```

Удаления **не оборачиваются в единую transaction** намеренно — retention
является попыткой лучших усилий, а ошибки учитываются в `counters["errors"]`, а не поднимаются.

---

## 7. Scoping по run_id

### 7.1 Концепция

Каждая запись секрета имеет необязательный столбец `run_id`:

| Значение `run_id` | Смысл |
|---------------|---------|
| `NULL` | Глобальный scope — доступен из любого запуска |
| `"run_abc123"` | Привязан к конкретному ETL-запуску |

### 7.2 Scope записи

`SecretVaultWriteService.put_many()` получает `run_id` от вызывающей стороны:

```python
write_service.put_many(
    dataset="hr",
    match_key="emp_001",
    secrets={"password": "secret123"},
    run_id="run_abc123",   # or None for global
)
```

### 7.3 Scope чтения и fallback

`SecretVaultReadService.get_secret()` определяет `run_id` из контекста вызова:

```python
effective_run_id = run_id if run_id is not None else self._default_run_id
```

Затем SQL-запрос использует двухуровневый приоритет:

```
effective_run_id = "run_abc123"
  → Look for: run_id = "run_abc123"  first (run-scoped)
  → Fallback: run_id IS NULL          (global)
  → Return the first match

effective_run_id = None
  → Look for: run_id IS NULL only     (global only)
```

### 7.4 Сценарии использования run-scope

| Сценарий | Стратегия run_id |
|----------|----------------|
| Одиночный ETL-запуск (без перекрытия) | `run_id=None` (глобальный) |
| Параллельные запуски с одинаковым match_key | `run_id=<run_id>` для изоляции секретов |
| Canary-развёртывание (частичный vault) | `run_id=<canary_run_id>` |
| Ручное повторное поглощение / backfill | `run_id=<specific_run>` |

---

## 8. Жизненный цикл schema

**Файл:** [`connector/infra/secrets/sqlite/schema.py`](../../../../connector/infra/secrets/sqlite/schema.py)

### 8.1 `ensure_vault_schema(engine: SqliteEngine) -> int`

Вызывается во время `vault_startup_resource()` до `VaultStartupGuard.ensure_ready()`.

```
Алгоритм:
  1. _create_meta(engine)        → CREATE TABLE IF NOT EXISTS vault_meta
  2. current_version = _get_schema_version(engine) or 0
  3. if current_version == 0:
       _create_vault_tables(engine)   → CREATE TABLE vault_dek, vault_secrets, vault_probe + indexes
       _set_schema_version(engine, 1)
       return 1
  4. if current_version < SCHEMA_VERSION:
       _migrate_to_latest(engine, current_version)
       _set_schema_version(engine, SCHEMA_VERSION)
       return SCHEMA_VERSION
  5. return current_version   (already up to date)
```

### 8.2 Паттерн миграции

```python
def _migrate_to_latest(engine: SqliteEngine, current_version: int) -> None:
    if current_version < 1:
        _create_vault_tables(engine)
```

Миграции выполняются последовательно и аддитивно. Будущие миграции следуют тому же
паттерну `if current_version < N:`. Каждая миграция идемпотентна благодаря
DDL `CREATE TABLE IF NOT EXISTS`.

### 8.3 Хранение версии schema

```sql
INSERT INTO vault_meta(key, value) VALUES ('schema_version', '1')
ON CONFLICT(key) DO UPDATE SET value = excluded.value
```

---

## 9. Сопоставление ошибок

**Файл:** [`connector/infra/secrets/sqlite/repository.py`](../../../../connector/infra/secrets/sqlite/repository.py)

Все исключения `sqlite3.DatabaseError` из операций записи сопоставляются с
`SecretStoreError`, а из операций чтения — с `SecretReadError`.

### 9.1 Категории ошибок

```python
def _build_error_details(exc, *, op, extra_details):
    reason = "sqlite_error"
    if _is_busy_timeout(exc):
        reason = "busy_timeout"
    elif _is_schema_changed(exc):
        reason = "schema_changed"
    details = {
        "reason": reason,
        "op": op,
        "db_path": self._engine.db_path,
        "current_pid": os.getpid(),
        "sqlite_error": str(exc),
    }
    if reason == "schema_changed":
        details["schema_retries"] = SQLITE_SCHEMA_MAX_RETRIES
    if reason == "busy_timeout":
        details["lock_holder_pid"] = "unknown"
    ...
```

| `reason` | Условие SQLite | Сопоставляемое исключение |
|---------|-----------------|-----------------|
| `"busy_timeout"` | `SQLITE_BUSY`, `SQLITE_LOCKED`, "database is locked" | `SecretStoreError` / `SecretReadError` |
| `"schema_changed"` | `SQLITE_SCHEMA`, "schema has changed" | `SecretStoreError` / `SecretReadError` |
| `"sqlite_error"` | Любой другой `DatabaseError` | `SecretStoreError` / `SecretReadError` |

### 9.2 Логика `_is_busy_timeout(exc)`

```python
def _is_busy_timeout(exc: sqlite3.DatabaseError) -> bool:
    error_code = getattr(exc, "sqlite_errorcode", None)
    if error_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        return True
    message = str(exc).lower()
    return "database is locked" in message or "database is busy" in message
```

Двойное обнаружение: числовой код ошибки SQLite (Python ≥ 3.11) И сопоставление строки
для более старых версий Python.

### 9.3 Логика `_is_schema_changed(exc)`

```python
def _is_schema_changed(exc: sqlite3.DatabaseError) -> bool:
    error_code = getattr(exc, "sqlite_errorcode", None)
    if error_code == sqlite3.SQLITE_SCHEMA:
        return True
    return "schema has changed" in str(exc).lower()
```

`SQLITE_SCHEMA` указывает на изменение DDL между подготовкой оператора и
его выполнением. Repository использует `execute_with_retry` с максимальным числом
повторов `SQLITE_SCHEMA_MAX_RETRIES = 2` для данного случая.

### 9.4 Контекст ошибки в `details`

Все детали ошибки безопасны для логирования:
- `db_path`: путь к файлу базы данных SQLite
- `current_pid`: идентификатор процесса (для многопроцессной диагностики)
- `sqlite_error`: сообщение исключения (без секретных данных)
- `op`: имя операции repository (`"upsert_secret"`, `"get_dek"` и т.д.)

---

## 10. `_ensure_schema()` во время `__init__`

```python
def __init__(self, engine: SqliteEngine):
    self._engine = engine
    self._ensure_schema()
```

```python
def _ensure_schema(self) -> None:
    try:
        ensure_vault_schema(self._engine)
    except sqlite3.DatabaseError as exc:
        raise self._map_store_error(exc, op="schema_bootstrap", extra_details={"stage": "startup"})
```

Инициализация schema выполняется синхронно в момент создания repository.
Если база данных недоступна или повреждена, запуск немедленно завершается ошибкой
`SecretStoreError(reason=..., op="schema_bootstrap")`.

---

## 11. Функции сопоставления строк

Приватные функции уровня модуля преобразуют «сырые» объекты `sqlite3.Row` в типизированные датаклассы:

```python
def _row_to_secret_record(row: sqlite3.Row | None) -> VaultSecretRecord | None:
    if row is None:
        return None
    return VaultSecretRecord(
        dataset=str(row["dataset"]),
        field=str(row["field"]),
        locator_hash=str(row["locator_hash"]),
        locator_version=str(row["locator_version"]),
        ciphertext=row["ciphertext"],     # bytes (BLOB column)
        cipher_algo=str(row["cipher_algo"]),
        key_version=str(row["key_version"]),
        dek_version=str(row["dek_version"]),
        run_id=str(row["run_id"]) if row["run_id"] is not None else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        secret_id=int(row["secret_id"]) if row["secret_id"] is not None else None,
    )
```

`ciphertext` и `wrapped_dek` возвращаются как Python `bytes` из BLOB-столбцов —
без преобразования в строку, с сохранением точного бинарного токена.

---

## 12. Взаимодействие слоёв

| Слой | Роль |
|-------|------|
| **Доменные модели** (`connector/domain/secrets/models.py`) | `VaultSecretRecord`, `VaultDekRecord`, `VaultProbeRecord` — контракты данных |
| **Доменный порт** (`connector/domain/ports/secrets/repository.py`) | `SecretVaultRepositoryPort` — контракт интерфейса |
| **Infra-repository** (`connector/infra/secrets/sqlite/repository.py`) | `SqliteVaultRepository` — реализация на SQLite |
| **Infra-schema** (`connector/infra/secrets/sqlite/schema.py`) | `ensure_vault_schema()` — жизненный цикл DDL |
| **Infra-engine** (`connector/infra/sqlite/engine.py`) | `SqliteEngine` — управление соединением, retry, autobegin |
| **Delivery** (`connector/delivery/cli/containers.py`) | `SqliteContainer` открывает engine; `VaultContainer` внедряет его в `SqliteVaultRepository` |

### Направление зависимостей

```
SqliteVaultRepository
     │ depends on
     ├── SqliteEngine          (infra/sqlite)
     └── VaultSecretRecord     (domain/secrets/models)
         VaultDekRecord
         VaultProbeRecord
         SecretStoreError      (domain/secrets/errors)
         SecretReadError

SecretVaultRepositoryPort (domain/ports/secrets/repository)
     ▲ implements
     └── SqliteVaultRepository
```

---

## 13. Типичные сценарии

### Сценарий A: Новая база данных vault

1. `vault_startup_resource(engine)` вызывает `ensure_vault_schema(engine)`.
2. Создаётся `vault_meta`; `current_version = 0`.
3. `_create_vault_tables()` выполняет всё DDL `CREATE TABLE IF NOT EXISTS`.
4. `vault_meta` обновляется до `schema_version=1`.
5. Далее выполняется `VaultStartupGuard.ensure_ready()`.

### Сценарий B: Запись секрета (нормальный запуск)

1. `write_service.put_many(dataset="hr", match_key="emp_001", secrets={"pw": "secret"})`.
2. `repository.transaction()` → `BEGIN IMMEDIATE`.
3. `repository.get_active_dek()` → SELECT возвращает существующий DEK.
4. DEK разворачивается в памяти (криптографический слой).
5. `cipher.encrypt("secret", dek_plaintext)` → байты Fernet-токена.
6. `repository.upsert_secret(VaultSecretRecord(...))`.
7. Транзакция фиксируется → секрет сохранён надёжно.

### Сценарий C: Чтение секрета (фаза apply)

1. `read_service.get_secret(dataset="hr", field="pw", source_ref={"match_key":"emp_001"})`.
2. `locator.build_locator_hash(...)` → строка sha256.
3. `repository.get_secret(..., run_id=None)` → читает строку `run_id IS NULL`.
4. `repository.get_dek(record.dek_version)` → запись DEK.
5. DEK разворачивается → `cipher.decrypt(record.ciphertext, dek)` → `"secret"`.

### Сценарий D: Попытка параллельной записи (заблокированная БД)

1. Два процесса одновременно пытаются выполнить `repository.transaction()`.
2. Первый получает `BEGIN IMMEDIATE` → продолжает работу.
3. Второй: `sqlite3.OperationalError: database is locked`.
4. `_is_busy_timeout()` → `True`.
5. Поднимается `SecretStoreError(details={"reason":"busy_timeout", "op":"transaction_begin"})`.
6. Вышестоящий слой фиксирует сбой записи и продолжает работу.

### Сценарий E: Миграция schema (будущее)

1. Новый код запускается с `SCHEMA_VERSION = 2`.
2. `ensure_vault_schema()` читает `current_version = 1`.
3. Вызывается `_migrate_to_latest(engine, 1)`.
4. Новая миграция добавляет столбец/индекс.
5. `_set_schema_version(engine, 2)`.

---

## 14. Важные детали реализации

### 14.1 `COALESCE(run_id, '')` в уникальном индексе

Уникальный индекс использует `COALESCE(run_id, '')`, а не `run_id` напрямую, потому что
SQLite считает `NULL != NULL` — две строки с `run_id IS NULL` в столбце `UNIQUE` не конфликтовали бы.
`COALESCE(NULL, '')` сводит все строки глобального scope к `''`, обеспечивая
соблюдение ограничения: не более одной записи глобального scope на locator.

### 14.2 `AUTOINCREMENT` для упорядочивания

`secret_id INTEGER PRIMARY KEY AUTOINCREMENT` обеспечивает монотонно возрастающие ID.
Это используется как стабильный критерий разбивки при ничьей в `ORDER BY secret_id DESC`, когда временные метки `updated_at`
идентичны (например, две быстрые записи в одну секунду).

### 14.3 Внешний ключ DEK

`vault_secrets.dek_version REFERENCES vault_dek(dek_version)` объявлен, но
применение внешних ключей в SQLite отключено по умолчанию (требует `PRAGMA foreign_keys=ON`).
Приложение в настоящее время не включает эту прагму — ограничение носит
информационный характер для инструментов и документации.

### 14.4 Логика retry (`execute_with_retry`)

```python
SQLITE_SCHEMA_MAX_RETRIES = 2
```

Метод `SqliteEngine.execute_with_retry()` выполняет повторные попытки при ошибках `SQLITE_SCHEMA`
до `SQLITE_SCHEMA_MAX_RETRIES` раз. Это покрывает редкий случай, когда изменения DDL
(из другого процесса или соединения) делают подготовленный оператор недействительным между подготовкой
и выполнением. После исчерпания попыток ошибка сопоставляется с `SecretStoreError`.

### 14.5 Временные метки в виде текста ISO 8601

`created_at` и `updated_at` хранятся как `TEXT` в формате ISO 8601 UTC
(из `connector.common.time.getUtcNowIso()`). Отсутствие в SQLite собственного типа
datetime компенсируется согласованным текстовым форматом, который корректно сортируется
как строка.

### 14.6 Без мягкого удаления

Записи жёстко удаляются через `delete_secret()`. Флага `deleted_at`
или паттерна tombstone не существует. `VaultRetentionService` удаляет эфемерные секреты
немедленно после успешного apply — без пути восстановления.

---

## 15. Контракты и границы

| Операция | Предусловия | Успех | Ошибки |
|-----------|--------------|---------|--------|
| `transaction()` | Engine открыт, не в nested transaction | Yield, фиксация при выходе | `SecretStoreError(reason="busy_timeout")` |
| `upsert_secret(record)` | Внутри transaction | 1 строка вставлена/обновлена | `SecretStoreError` |
| `get_secret(...)` | Engine открыт | `VaultSecretRecord` или `None` | `SecretReadError` |
| `delete_secret(...)` | Engine открыт | `int` удалённых строк (0, если не найдено) | `SecretStoreError` |
| `upsert_dek(record)` | Внутри autobegin scope | DEK сохранён, остальные деактивированы | `SecretStoreError` |
| `get_active_dek()` | Engine открыт | `VaultDekRecord` или `None` | `SecretReadError` |
| `get_dek(dek_version)` | Engine открыт | `VaultDekRecord` или `None` | `SecretReadError` |
| `upsert_probe(record)` | Engine открыт | Зонд сохранён | `SecretStoreError` |
| `get_probe(name)` | Engine открыт | `VaultProbeRecord` или `None` | `SecretReadError` |
| `ensure_vault_schema()` | Engine открыт | Возвращается `SCHEMA_VERSION` | `SecretStoreError(op="schema_bootstrap")` |

---

## 16. Характеристики производительности

### 16.1 Стратегия индексирования

Таблица `vault_secrets` имеет два индекса:

**`idx_vault_secret_unique_scope`** (уникальный индекс):
```sql
ON vault_secrets(dataset, field, locator_version, locator_hash, COALESCE(run_id, ''))
```
- Используется `upsert_secret()` для обнаружения конфликтов.
- Обеспечивает одну строку на `(dataset, field, locator, run_scope)`.
- Не используется напрямую для SELECT-запросов (для этого лучше подходит lookup-индекс).

**`idx_vault_secret_lookup`** (неуникальный):
```sql
ON vault_secrets(dataset, field, locator_version, locator_hash, run_id)
```
- Используется `get_secret()` для извлечения строк.
- Покрывает точный список столбцов, используемых в предложении WHERE.
- `run_id` стоит последним — допускает range scan для `AND (run_id = ? OR run_id IS NULL)`.

### 16.2 План выполнения запроса `get_secret()`

Двухуровневый запрос по run_id:
```sql
WHERE dataset = ? AND field = ? AND locator_hash = ? AND locator_version = ?
  AND (run_id = ? OR run_id IS NULL)
ORDER BY CASE WHEN run_id = ? THEN 0 ELSE 1 END, updated_at DESC, secret_id DESC
LIMIT 1
```

SQLite использует `idx_vault_secret_lookup` для сужения кандидатов
до строк, совпадающих по `(dataset, field, locator_version, locator_hash)`, а затем
фильтрует по предикату `run_id`. С покрывающим индексом это
поиск по B-дереву + небольшой range scan — типично O(log N) с горсткой
строк для проверки на locator.

### 16.3 План выполнения запроса `get_active_dek()`

```sql
WHERE is_active = 1
ORDER BY updated_at DESC, dek_version DESC
LIMIT 1
```

`idx_vault_dek_active` покрывает `(is_active, updated_at)`. В нормальной работе
существует ровно одна активная строка, поэтому это фактически O(1) поиск по индексу.

### 16.4 Оценка размера базы vault

Для типичного HR-датасета с 5 000 сотрудниками и 3 секретными полями каждый:

| Таблица | Оценочное число строк | Оценочный размер |
|-------|---------------|----------------|
| `vault_secrets` | 15 000 | ~3–5 МБ (Fernet-токены ~200 байт каждый) |
| `vault_dek` | 1–3 | Пренебрежимо мало |
| `vault_probe` | 1 | Пренебрежимо мало |
| `vault_meta` | 1 | Пренебрежимо мало |

В эфемерном режиме строки `vault_secrets` удаляются после apply, поэтому размер в установившемся режиме
значительно меньше.

---

## 17. FAQ и часто задаваемые вопросы

### В: Почему vault — отдельный файл SQLite, а не часть кэша?

Vault содержит чувствительные данные (зашифрованные секреты), которые требуют иных
прав доступа, процедур резервного копирования и управления жизненным циклом, чем операционный
кэш. Разделение файлов:
- Позволяет устанавливать разные права доступа к файловой системе для каждого файла.
- Делает явными операции резервного копирования/восстановления vault.
- Предотвращает случайное раскрытие через инструменты просмотра кэша.

### В: Почему `get_secret()` возвращает `None`, а не поднимает исключение при отсутствии записи?

`None` указывает, что vault не содержит данного секрета — возможно, потому что:
1. Секрет никогда не был записан (vault не был активен для этой строки во время enrich).
2. Секрет уже удалён (эфемерный режим, очистка после apply).
3. Locator-scope не совпадает.

Это **нормальное операционное состояние**, а не ошибка. Конвейер apply
обрабатывает `None`, считая поле «недоступным», и может пропустить его или
залогировать соответствующим образом. Поднятие исключения вынудило бы вызывающих перехватывать
его для ожидаемого условия.

### В: Что происходит, если `upsert_dek()` вызывается, пока другой писатель находится в транзакции?

`upsert_dek()` использует `autobegin` (не `BEGIN IMMEDIATE`). При вызове вне
контекстного менеджера `transaction()` он может конфликтовать с другим писателем.
На практике `upsert_dek()` всегда вызывается изнутри контекста `transaction()`
(через `SecretVaultWriteService`) или из `VaultStartupGuard`, который
выполняется до начала любой обработки конвейера (однопроцессный запуск).

### В: Почему временные метки хранятся как TEXT, а не INTEGER (UNIX epoch)?

1. **Читаемость**: строки ISO 8601 (`"2024-01-15T10:30:00Z"`) читаемы
   при просмотре базы без преобразования.
2. **Корректная сортировка**: строки ISO 8601 сортируются лексикографически в том же
   порядке, что и хронологически — `ORDER BY updated_at DESC` работает корректно.
3. **Согласованность**: остальная часть приложения использует текст ISO 8601 для временных меток.

### В: Как `COALESCE(run_id, '')` в уникальном индексе влияет на обработку NULL?

Без `COALESCE` SQLite считает `NULL != NULL`, поэтому две строки с `run_id IS NULL`
не конфликтовали бы. С `COALESCE(NULL, '')` обе сводятся к пустой строке `''`,
что вызывает ожидаемый конфликт. Это обеспечивает не более одной записи глобального scope
на `(dataset, field, locator)`.

### В: Что если в `vault_dek` несколько строк с `is_active=1` (ошибка)?

`get_active_dek()` использует `ORDER BY updated_at DESC, dek_version DESC LIMIT 1`
для всегда возврата наиболее свежего активного DEK. `upsert_dek()` атомарно
деактивирует остальные через `UPDATE vault_dek SET is_active=0 WHERE is_active=1 AND dek_version != ?`
перед вставкой/обновлением нового. В параллельных сценариях блокировка SQLite
`BEGIN IMMEDIATE` предотвращает это с самого начала.

---

## 18. Обслуживание и эксплуатация

### 18.1 Ручная инспекция vault

```sql
-- Check vault_dek status
SELECT dek_version, wrap_key_version, is_active, created_at, updated_at
FROM vault_dek ORDER BY created_at;

-- Count secrets by dataset/field
SELECT dataset, field, run_id, COUNT(*) as secret_count
FROM vault_secrets GROUP BY dataset, field, run_id;

-- Check startup probe
SELECT probe_name, key_version, dek_version, created_at, updated_at
FROM vault_probe;

-- Schema version
SELECT * FROM vault_meta;
```

### 18.2 Повторная обёртка DEK (ручная)

В настоящее время автоматизированного инструмента нет — выполняется вручную через скрипт миграции:
```python
# Pseudo-code for manual DEK re-wrap:
old_record = repository.get_active_dek()
dek_plaintext = cipher.unwrap_dek(old_record.wrapped_dek, old_key)
new_wrapped = cipher.wrap_dek(dek_plaintext, new_key)
new_record = VaultDekRecord(
    dek_version=old_record.dek_version,  # Same version, different wrap
    wrapped_dek=new_wrapped,
    wrap_key_version="v2",
    is_active=True,
    ...
)
repository.upsert_dek(new_record)
```

### 18.3 Аварийное восстановление

Если зонд vault повреждён, но `vault_secrets` целы:
1. Определить, какие значения `dek_version` существуют в `vault_secrets`.
2. Проверить, какой версией мастер-ключа обёрнут каждый DEK (`wrap_key_version`).
3. Убедиться, что соответствующие мастер-ключи присутствуют в `ANKEY_VAULT_MASTER_KEYS`.
4. Удалить или восстановить строку `vault_probe`.
5. Перезапустить: `VaultStartupGuard` пересоздаст зонд.

---

## 19. Справочник режимов сбоя

### 19.1 Режимы сбоя слоя хранилища

| Сбой | Первопричина | Ошибка | Способ устранения |
|---------|-----------|-------|------------|
| `SecretStoreError(reason="busy_timeout")` | Другой процесс удерживает блокировку записи | `upsert_secret`, `transaction` | Проверить зависшие процессы; реализовать retry в слое оркестрации |
| `SecretStoreError(reason="schema_changed")` | Параллельное изменение DDL | Любая запись | Обычно временный; repository повторяет до 2 раз |
| `SecretStoreError(reason="schema_bootstrap", stage="startup")` | Файл БД недоступен | `_ensure_schema` | Проверить права доступа к файлу; корректен ли путь `cache_dir`? |
| `SecretReadError(reason="dek_not_found")` | DEK, на который ссылается секрет, отсутствует | `get_secret` → `get_dek` возвращает None | DEK удалён вручную; восстановить из резервной копии |
| `SecretStoreError(op="upsert_dek")` | Запись в БД не удалась при создании DEK | `_ensure_active_dek` | Проблема хранилища; проверить свободное место на диске |
| Файл хранилища удалён в процессе работы | Внешний процесс или проблема файловой системы | Любая операция | Без возможности устранения; требуется перезапуск |

### 19.2 Режимы сбоя миграции schema

| Сбой | Первопричина | Способ устранения |
|---------|-----------|------------|
| DDL миграции завершается ошибкой | Schema применена частично | Проверить `vault_meta.schema_version`; завершить DDL вручную |
| Таблица `vault_meta` отсутствует | БД повреждена | Пересоздать с нуля, если секреты не сохранены |
| Несоответствие `SCHEMA_VERSION` (даунгрейд) | Старый код работает на новой schema | Никогда не понижать версию schema; код должен быть только прямосовместимым |

---

## 20. Связанные документы

- [vault-core.md](vault-core.md) — Интеграция с конвейером: как `SecretVaultRepositoryPort`
  используется сервисами записи и чтения
- [vault-crypto.md](vault-crypto.md) — Что хранится в `ciphertext` и `wrapped_dek`;
  семантика версий ключей
- [vault-delivery.md](vault-delivery.md) — DI-проводка: `SqliteContainer`, `VaultContainer`
  и то, как `vault_startup_resource` оркестрирует schema + guard
