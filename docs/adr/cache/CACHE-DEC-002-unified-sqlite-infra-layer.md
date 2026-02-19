# CACHE-DEC-002: Единый SQLite-инфраструктурный слой (connector/infra/sqlite/)

> **Статус**: Принято
> **Дата принятия**: 2026-02-19
> **Решает проблему**: [CACHE-PROBLEM-002](./CACHE-PROBLEM-002-sqlite-infra-divergence.md)

---

## 📋 Контекст

Cache-слой и vault-слой имеют расходящиеся SQLite-реализации: разные точки входа, разные
transaction modes, разная обработка ошибок, разные подходы к миграциям. Добавление новой
SQLite-базы требует копирования механик из одного из них. Vault-слой смешивает DB-уровневую
(readonly detection) и domain-уровневую (probe validation) ответственность в одном классе
([CACHE-PROBLEM-002](./CACHE-PROBLEM-002-sqlite-infra-divergence.md)).

---

## 🎯 Решение

Создать пакет `connector/infra/sqlite/` как единый набор строительных блоков для всех
SQLite-баз проекта. Lifecycle (singleton, startup, shutdown) управляется DI-контейнером
(`dependency-injector`) — отдельных Descriptor/LifecycleManager классов не вводим.

Пакет предоставляет два компонента:

1. **`SqliteDbConfig`** — конфигурация одной DB (transaction mode, timeouts, PRAGMA)
2. **`SqliteEngine`** — унифицированный API для SQL-операций + фабричная функция `open_sqlite`

Vault-слой переходит на `SqliteEngine` вместо прямых вызовов `self._conn.execute()`.
`VaultStartupGuard` теряет `_is_storage_readonly()` (переносится в `SqliteEngine`) и вызывается
через `providers.Resource` в DI-контейнере.

Operational-таблицы (`identity_index`, `pending_links`, `identity_runtime_state`) выносятся
из `cache.sqlite3` в отдельный `identity.sqlite3`. Серверный overhead — ~3 дополнительных
file handle и ~150KB RAM — незначителен.

Вместе с таблицами переезжают и репозитории: `SqliteIdentityRepository` и
`SqlitePendingLinksRepository` переносятся из `connector/infra/cache/repository/` в новый
пакет `connector/infra/identity/sqlite/` — они не являются частью cache-слоя.

Конфигурация SQLite — `SqliteSettings` — реализуется как самостоятельная
`pydantic_settings.BaseSettings`, **без добавления полей в плоский `Settings`** (`config.py`).

**Файлы БД** (префикс `ankey_` убирается):

| DB | Файл | Содержимое |
|----|------|-----------|
| cache | `cache.sqlite3` | dataset-таблицы (users и т.д.) |
| vault | `vault.sqlite3` | secrets, DEK, probe |
| identity | `identity.sqlite3` | identity_index, pending_links, identity_runtime_state |

---

## 🏗️ Архитектурное решение

### Структура пакета

```
connector/infra/sqlite/
├── __init__.py
├── config.py      ← SqliteDbConfig
└── engine.py      ← SqliteEngine + open_sqlite()
```

`sqlite3.Connection` не экспортируется — остаётся приватной деталью реализации `engine.py`.

### Компоненты

**`SqliteDbConfig`** (`config.py`):
```python
@dataclass(frozen=True)
class SqliteDbConfig:
    transaction_mode: Literal["deferred", "immediate", "exclusive"] = "deferred"
    busy_timeout_ms: int = 5000
    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"
    foreign_keys: bool = True
    wal_autocheckpoint: int = 1000
    schema_retry_count: int = 0          # >0 включает retry при SQLITE_SCHEMA
```

**`SqliteEngine` + `open_sqlite`** (`engine.py`):
```python
def open_sqlite(config: SqliteDbConfig, path: str) -> SqliteEngine:
    """Открыть SQLite-соединение с нужными PRAGMA и вернуть готовый SqliteEngine."""
    conn = _open_raw_connection(config, path)   # приватная
    return SqliteEngine(conn, config)


class SqliteEngine:
    db_path: str                  # путь, переданный в open_sqlite (для diagnostics/logging)

    # существующее API без изменений
    def execute(self, sql, params=None): ...
    def fetchone(self, sql, params=None): ...
    def fetchall(self, sql, params=None): ...
    def executemany(self, sql, seq): ...

    def transaction(self, mode: str | None = None) -> ContextManager:
        """mode=None → использует config.transaction_mode"""
        ...

    def autobegin(self, mode: str | None = None) -> ContextManager:
        """Присоединиться к активной транзакции или начать новую.
        Используется вместо _write_unit()-паттерна в репозиториях."""
        ...

    # новое
    def is_readonly(self) -> bool:
        """Пытается BEGIN IMMEDIATE; readonly → True; иные ошибки — пробрасывает."""
        ...
    def execute_with_retry(self, sql, params, max_retries): ...
```

`open_sqlite` — единственная публичная точка входа. Возвращает готовый `SqliteEngine`,
`sqlite3.Connection` наружу не выходит никогда. Все соединения открываются с
`isolation_level=None` — явное управление транзакциями через `BEGIN`/`COMMIT`/`ROLLBACK`.

`transaction(mode=None)` — per-call override поверх `config.transaction_mode`. Vault обычно
использует `immediate` из конфига, но может переопределить для read-only транзакций.

`autobegin(mode=None)` — «мягкий» вариант `transaction()`: присоединяется к уже активной
транзакции (`conn.in_transaction`) или начинает новую. Используется в репозиториях вместо
паттерна `_write_unit()`. `_transaction_depth`-счётчик в engine не нужен — `isolation_level=None`
гарантирует, что `conn.in_transaction` отражает реальное состояние.

`is_readonly()` — пытается `BEGIN IMMEDIATE`; при ошибке readonly возвращает `True`;
прочие `sqlite3.OperationalError` пробрасывает. Не использует `sqlite_master`: проверка через
транзакцию выявляет реальную write-capability включая filesystem-уровень.

### Источник конфигурации: SqliteSettings

`SqliteDbConfig` строится из `SqliteSettings` в DI-контейнере. Прямые `os.getenv()` внутри
`db.py` и инфра-модулей — удаляются.

`SqliteSettings` — самостоятельная `pydantic_settings.BaseSettings`, **не добавляется в плоский
`Settings`** (`config.py`). `pydantic_settings` читает env vars, валидирует типы и диапазоны из
коробки; ручной parse-код (`_clamp_busy_timeout` и т.д.) не нужен. CLI-overrides прокидываются
при инстанциировании: `SqliteSettings(vault_sqlite_busy_timeout_ms=cli_value)`.

**Принцип**: глобальные дефолты + per-DB overrides (`None` = взять global).

**`SqliteSettings`** (`connector/config/app_settings.py`):
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class SqliteSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANKEY_", env_ignore_empty=True)

    # Глобальные дефолты
    sqlite_journal_mode: str = "WAL"
    sqlite_synchronous: str = "NORMAL"
    sqlite_busy_timeout_ms: int = 5000
    sqlite_wal_autocheckpoint: int = 1000

    # Vault overrides (None = использовать global)
    vault_db_path: str | None = None
    vault_sqlite_transaction_mode: str = "immediate"
    vault_sqlite_journal_mode: str | None = None
    vault_sqlite_busy_timeout_ms: int | None = None
    vault_sqlite_schema_retry_count: int = 2

    # Cache overrides
    cache_sqlite_transaction_mode: str = "deferred"
    cache_sqlite_journal_mode: str | None = None
    cache_sqlite_busy_timeout_ms: int | None = None

    # Identity
    identity_db_path: str | None = None   # None → {cache_dir}/identity.sqlite3
```

**Override chain в DI-контейнере:**
```python
def build_vault_db_config(s: SqliteSettings) -> SqliteDbConfig:
    return SqliteDbConfig(
        transaction_mode=s.vault_sqlite_transaction_mode,
        busy_timeout_ms=s.vault_sqlite_busy_timeout_ms or s.sqlite_busy_timeout_ms,
        journal_mode=s.vault_sqlite_journal_mode or s.sqlite_journal_mode,
        synchronous=s.sqlite_synchronous,
        wal_autocheckpoint=s.sqlite_wal_autocheckpoint,
        schema_retry_count=s.vault_sqlite_schema_retry_count,
    )

def build_cache_db_config(s: SqliteSettings) -> SqliteDbConfig:
    return SqliteDbConfig(
        transaction_mode=s.cache_sqlite_transaction_mode,
        busy_timeout_ms=s.cache_sqlite_busy_timeout_ms or s.sqlite_busy_timeout_ms,
        journal_mode=s.cache_sqlite_journal_mode or s.sqlite_journal_mode,
        synchronous=s.sqlite_synchronous,
        wal_autocheckpoint=s.sqlite_wal_autocheckpoint,
    )

def build_identity_db_config(s: SqliteSettings) -> SqliteDbConfig:
    return SqliteDbConfig(
        transaction_mode="deferred",
        busy_timeout_ms=s.sqlite_busy_timeout_ms,
        journal_mode=s.sqlite_journal_mode,
        synchronous=s.sqlite_synchronous,
        wal_autocheckpoint=s.sqlite_wal_autocheckpoint,
    )
```

**Параметры и их обоснование**:

| Параметр | Default | Зачем конфигурировать |
|----------|---------|----------------------|
| `sqlite_journal_mode` | `WAL` | WAL для прод, `DELETE`/`MEMORY` для тестов |
| `sqlite_synchronous` | `NORMAL` | `FULL` для max durability, `OFF` для тестовой скорости |
| `sqlite_busy_timeout_ms` | `5000` | При конкурентном доступе; в prod может потребоваться увеличить |
| `sqlite_wal_autocheckpoint` | `1000` | При тяжёлой записи уменьшают, иначе WAL-файл растёт |
| `vault_sqlite_schema_retry_count` | `2` | Устойчивость к `SQLITE_SCHEMA` |
| `identity_db_path` | `None` | Override пути (например, tmpfs для эфемерных данных) |

Намеренно не выносим (`mmap_size`, `cache_size_kb`, `temp_store`) — тюнинг производительности,
не deploy-параметры.

### Lifecycle через DI-контейнер

Три `Singleton`-провайдера — три соединения, открытых на весь runtime. Новая DB = ещё
один `Singleton`, без дополнительного lifecycle-кода:

```python
# Startup resource generators
def vault_startup_resource(engine: SqliteEngine) -> Iterator[None]:
    ensure_vault_schema(engine)          # инфра: DDL / миграции таблиц vault
    guard = VaultStartupGuard(
        repository=SqliteVaultRepository(engine),
        cipher=FernetEnvelopeCipher(),
        key_provider=EnvVaultKeyProvider(),
    )
    guard.ensure_ready()                 # домен: keyring + probe readiness
    yield                                # runtime — соединение живёт в Singleton
    # shutdown: соединение закрывается Singleton-провайдером

def cache_startup_resource(engine: SqliteEngine, specs: list[CacheSpec]) -> Iterator[None]:
    ensure_cache_ready(engine, specs)    # schema v1..N + dataset-таблицы
    yield

def identity_startup_resource(engine: SqliteEngine) -> Iterator[None]:
    ensure_identity_schema(engine)       # DDL: identity_index, pending_links, runtime_state
    yield


# connector/delivery/cli/containers.py
class SqliteContainer(containers.DeclarativeContainer):
    settings = providers.Dependency(instance_of=SqliteSettings)
    cache_specs = providers.Dependency(instance_of=list)  # список CacheSpec

    cache_engine = providers.Singleton(
        open_sqlite,
        config=providers.Factory(build_cache_db_config, s=settings),
        path=providers.Factory(get_cache_db_path, s=settings),
    )
    vault_engine = providers.Singleton(
        open_sqlite,
        config=providers.Factory(build_vault_db_config, s=settings),
        path=providers.Factory(get_vault_db_path, s=settings),
    )
    identity_engine = providers.Singleton(
        open_sqlite,
        config=providers.Factory(build_identity_db_config, s=settings),
        path=providers.Factory(get_identity_db_path, s=settings),
    )

    cache_ready = providers.Resource(
        cache_startup_resource,
        engine=cache_engine,
        specs=cache_specs,
    )
    vault_ready = providers.Resource(
        vault_startup_resource,
        engine=vault_engine,
    )
    identity_ready = providers.Resource(
        identity_startup_resource,
        engine=identity_engine,
    )
```

`containers.py` полностью заменяет `bootstrap.py`.

### TO BE: структура модулей

```
connector/
├── config/
│   ├── config.py                    ← БЕЗ ИЗМЕНЕНИЙ (SQLite-поля не добавляются)
│   └── app_settings.py              ← добавить SqliteSettings (Pydantic BaseSettings)
│
├── infra/
│   ├── sqlite/                      ← NEW: общий SQLite-слой
│   │   ├── __init__.py
│   │   ├── config.py                ← SqliteDbConfig
│   │   └── engine.py                ← SqliteEngine + open_sqlite
│   │
│   ├── cache/
│   │   ├── backends/sqlite/
│   │   │   ├── db.py                ← УДАЛИТЬ (openCacheDb)
│   │   │   ├── engine.py            ← УДАЛИТЬ (re-export на переходный период)
│   │   │   ├── schema.py            ← УРЕЗАТЬ: только dataset-таблицы (users и т.д.)
│   │   │   └── handlers/            ← без изменений
│   │   ├── repository/
│   │   │   ├── cache_repository.py          ← без изменений
│   │   │   ├── identity_repository.py       ← УДАЛИТЬ (переехал в identity/)
│   │   │   └── pending_links_repository.py  ← УДАЛИТЬ (переехал в identity/)
│   │   ├── roles/                   ← без изменений
│   │   ├── cache_gateway.py         ← без изменений
│   │   ├── cache_spec.py            ← без изменений
│   │   └── dsl_runtime.py           ← без изменений
│   │
│   ├── identity/                    ← NEW
│   │   └── sqlite/
│   │       ├── __init__.py
│   │       ├── schema.py                    ← identity schema (split из cache)
│   │       ├── identity_repository.py       ← из cache/repository/
│   │       └── pending_links_repository.py  ← из cache/repository/
│   │
│   ├── secrets/
│   │   ├── sqlite/
│   │   │   ├── db.py                ← УДАЛИТЬ (VaultSqliteDb)
│   │   │   ├── schema.py            ← без изменений
│   │   │   └── repository.py        ← АДАПТИРОВАТЬ (conn→engine, _write_unit→autobegin)
│   │   └── ...                      ← без изменений
│   │
│   └── target/, logging/, sources/, artifacts/  ← без изменений
│
└── delivery/cli/
    ├── app.py                       ← добавить CLI-опции SQLite
    ├── bootstrap.py                 ← УДАЛИТЬ
    ├── containers.py                ← NEW: SqliteContainer
    └── ...                          ← без изменений
```

### Изменения в существующих компонентах

| Компонент | Тип изменения | Суть |
|-----------|---------------|------|
| `connector/infra/cache/backends/sqlite/engine.py` | Перенос | `SqliteEngine` → `connector/infra/sqlite/engine.py`; старый модуль — re-export до переключения |
| `connector/infra/cache/backends/sqlite/db.py` | Удаление | `openCacheDb` удаляется; engine создаётся DI-контейнером |
| `connector/infra/cache/backends/sqlite/schema.py` | Разделение | identity-таблицы → `connector/infra/identity/sqlite/schema.py`; в cache остаются только dataset-таблицы |
| `connector/infra/cache/repository/identity_repository.py` | Перенос | → `connector/infra/identity/sqlite/identity_repository.py` |
| `connector/infra/cache/repository/pending_links_repository.py` | Перенос | → `connector/infra/identity/sqlite/pending_links_repository.py` |
| `connector/infra/secrets/sqlite/db.py` | Удаление | `VaultSqliteDb` удаляется |
| `connector/infra/secrets/sqlite/repository.py` | Адаптация | `self._conn` → `self._engine`; `_write_unit()` → `engine.autobegin()` |
| `connector/domain/secrets/vault_startup_guard.py` | Упрощение | `_is_storage_readonly()` → `engine.is_readonly()` (инфра-метод); guard запускается в `vault_startup_resource` |
| `connector/config/app_settings.py` | Добавить | `SqliteSettings` (Pydantic `BaseSettings`); `config.py` не меняется |
| `connector/delivery/cli/app.py` | Добавить | CLI-опции для SQLite (override в `SqliteSettings`) |
| `connector/delivery/cli/bootstrap.py` | Заменить | Полностью заменяется на `containers.py` |

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **Нет велосипедного lifecycle-manager**: `dependency-injector` `Singleton` управляет lifetime
- ✅ **Минимальный пакет**: 2 файла — config + engine
- ✅ **`sqlite3.Connection` инкапсулирован**: наружу выходит только `SqliteEngine`
- ✅ **Декларативная регистрация**: новая DB = один `Singleton` в контейнере
- ✅ **`transaction(mode=None)`**: per-call override сохраняет гибкость при дефолте из конфига
- ✅ **`autobegin()`**: паттерн «join or begin» инкапсулирован в engine; убирает `_write_unit()`-велосипед из репозиториев
- ✅ **`isolation_level=None`**: единое явное управление транзакциями; устраняет конфликт с Python implicit autocommit
- ✅ **`SqliteSettings` на Pydantic**: env vars, типы, валидация из коробки; `config.py` не разрастается; задаёт паттерн для будущей полной миграции
- ✅ **Чистое именование**: `cache.sqlite3`, `vault.sqlite3`, `identity.sqlite3` без бренд-префиксов
- ✅ **3 DB практически бесплатно**: ~9 file handles, ~450KB RAM — незначительный overhead

**Недостатки (компромиссы)**:
- ⚠️ Внедрение `dependency-injector` меняет wiring всего приложения
- ⚠️ Рефакторинг `SqliteVaultRepository` (`self._conn` → `self._engine`) требует проверки транзакционной семантики
- ⚠️ Миграция схемы: identity-таблицы переносятся из `cache.sqlite3` в `identity.sqlite3` (данных нет — без миграции)

**Альтернативы, которые отклонили**:
- ❌ **SqliteDbLifecycleManager**: велосипед поверх того, что DI даёт из коробки
- ❌ **2 DB (оставить identity в cache)**: архитектурно менее чисто; при 3 файлах серверный overhead незначителен (~3 file handles, ~150KB RAM)
- ❌ **`open_connection → sqlite3.Connection`**: позволяет обойти `SqliteEngine`, нарушает инкапсуляцию

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/infra/sqlite/config.py` | Создать `SqliteDbConfig` |
| `connector/infra/sqlite/engine.py` | Создать `SqliteEngine` + `open_sqlite` |
| `connector/infra/identity/sqlite/schema.py` | Создать: identity schema (split из cache) |
| `connector/infra/identity/sqlite/identity_repository.py` | Перенести из `cache/repository/` |
| `connector/infra/identity/sqlite/pending_links_repository.py` | Перенести из `cache/repository/` |
| `connector/config/app_settings.py` | Создать `SqliteSettings` (Pydantic `BaseSettings`) |
| `connector/delivery/cli/containers.py` | Создать DI-контейнер (3 Singleton + 3 Resource) + startup resource generators |
| `connector/infra/cache/backends/sqlite/db.py` | Удалить `openCacheDb` |
| `connector/infra/cache/backends/sqlite/engine.py` | Re-export → удалить после переключения |
| `connector/infra/cache/backends/sqlite/schema.py` | Урезать до dataset-таблиц; identity убрать |
| `connector/infra/cache/repository/identity_repository.py` | Удалить (переехал) |
| `connector/infra/cache/repository/pending_links_repository.py` | Удалить (переехал) |
| `connector/infra/secrets/sqlite/db.py` | Удалить `VaultSqliteDb` |
| `connector/infra/secrets/sqlite/repository.py` | `self._conn` → `self._engine`; `_write_unit()` → `engine.autobegin()` |
| `connector/domain/secrets/vault_startup_guard.py` | `_is_storage_readonly()` → `engine.is_readonly()`; метод удаляется из guard |
| `connector/delivery/cli/app.py` | Добавить CLI-опции SQLite |
| `connector/delivery/cli/bootstrap.py` | Удалить (заменён `containers.py`) |

### Инварианты

1. **`sqlite3.Connection` инкапсулирован**: только `open_sqlite` создаёт соединение; наружу — только `SqliteEngine`
2. **Config immutability**: `SqliteDbConfig` — frozen dataclass
3. **Engine per DB**: каждый DB-id имеет ровно один `SqliteEngine`-синглтон в контейнере
4. **transaction mode**: дефолт из `config.transaction_mode`, per-call override через `transaction(mode=...)`
5. **`isolation_level=None`**: все соединения открываются в режиме явного управления транзакциями; `conn.in_transaction` достаточен для проверки активной транзакции — `_transaction_depth`-счётчик не нужен
6. **`db_path` в engine**: `SqliteEngine.db_path` хранит путь файла; PRAGMA `database_list` для диагностики не нужна

---

## 🧪 Валидация решения

**Тесты**:
- `test_open_sqlite_applies_pragma()` — PRAGMA journal_mode/synchronous/foreign_keys применяются
- `test_open_sqlite_returns_engine()` — возвращает `SqliteEngine`, не `Connection`
- `test_engine_transaction_default_mode()` — `BEGIN DEFERRED` / `BEGIN IMMEDIATE` по конфигу
- `test_engine_transaction_override_mode()` — per-call override работает
- `test_engine_is_readonly_via_begin_immediate()` — readonly detection через `BEGIN IMMEDIATE`; проверяет `sqlite3.OperationalError` с readonly-сообщением
- `test_engine_is_readonly_propagates_other_errors()` — не-readonly `OperationalError` пробрасывается
- `test_engine_autobegin_standalone()` — `autobegin()` без активной транзакции открывает `BEGIN`
- `test_engine_autobegin_join()` — `autobegin()` внутри активной транзакции присоединяется без нового `BEGIN`
- `test_engine_execute_with_retry_schema()` — retry при SQLITE_SCHEMA
- `test_vault_startup_guard_uses_engine_is_readonly()` — guard вызывает `engine.is_readonly()`, не обращается к сырому conn

**Проверка корректности**:
1. Все существующие cache-тесты проходят (Engine API не меняется)
2. Vault-тесты проходят: `SqliteVaultRepository` работает через `SqliteEngine`
3. Identity-репозиторий получает `identity_engine` из DI — не `cache_engine`

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Одно соединение на DB (singleton). Connection pool — за рамками текущего решения
- Migration rollback не реализован: миграции однонаправленные

**Риски**:
- ⚠️ `dependency-injector` меняет весь wiring; `bootstrap.py` удаляется полностью → Митигация: `containers.py` покрыт интеграционными тестами до удаления `bootstrap.py`
- ⚠️ Рефакторинг `SqliteVaultRepository` → Митигация: vault-тесты покрывают транзакционные сценарии
- ⚠️ Schema разделение (cache → identity) при отсутствии данных → без риска, но нужны тесты схемы

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `SqliteCacheGateway` | Косвенное | Получает `cache_engine` из DI-контейнера |
| `SqliteIdentityRepository` | Прямое | Переезжает в `infra/identity/sqlite/`; получает `identity_engine` из DI |
| `SqlitePendingLinksRepository` | Прямое | Переезжает в `infra/identity/sqlite/`; получает `identity_engine` из DI |
| `SqliteVaultRepository` | Прямое | `self._conn` → `self._engine`; `_write_unit()` → `engine.autobegin()` |
| `VaultStartupGuard` | Прямое | `_is_storage_readonly()` → `engine.is_readonly()`; guard запускается в `vault_startup_resource` |
| `bootstrap.py` | Удаление | Заменяется `containers.py` |
| Architecture tests | Проверка | Domain не импортирует `connector/infra/sqlite` напрямую |

---

## 🔗 Связанные документы

- [CACHE-PROBLEM-002](./CACHE-PROBLEM-002-sqlite-infra-divergence.md) — решаемая проблема
- [CONFIG-DEC-002](../config/CONFIG-DEC-002-pydantic-settings-migration.md) — `SqliteSettings` переедет на Pydantic
- `connector/infra/cache/backends/sqlite/engine.py` — текущий `SqliteEngine` (источник)
- `connector/infra/secrets/sqlite/db.py` — vault DB (целевой объект рефакторинга)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-19 | Решение принято по итогам архитектурного ревью vault-слоя |
| 2026-02-19 | Пересмотрено: SqliteDbDescriptor + SqliteDbLifecycleManager заменены на `dependency-injector` |
| 2026-02-19 | Финализировано: 3 DB (`cache`, `vault`, `identity`); пакет сокращён до 2 файлов; `open_sqlite → SqliteEngine`; `transaction(mode=None)`; `bootstrap.py` заменяется `containers.py` |
| 2026-02-19 | Уточнено по итогам ревью кода: добавлены `autobegin()`, `db_path`, `isolation_level=None`; `is_readonly()` через `BEGIN IMMEDIATE` вместо `sqlite_master`; расписаны startup resource generators для всех 3 DB; устранены несогласованности в таблицах компонентов и тестов |
| 2026-02-19 | Дополнено: TO BE дерево модулей; `SqliteIdentityRepository` + `SqlitePendingLinksRepository` переезжают в `connector/infra/identity/sqlite/`; `SqliteSettings` — самостоятельная Pydantic `BaseSettings`, поля в `config.py` не добавляются; override chain переименован под Pydantic field names |
