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
    # существующее API без изменений
    def execute(self, sql, params=None): ...
    def fetchone(self, sql, params=None): ...
    def fetchall(self, sql, params=None): ...
    def executemany(self, sql, seq): ...

    def transaction(self, mode: str | None = None) -> ContextManager:
        """mode=None → использует config.transaction_mode"""
        ...

    # новое
    def is_readonly(self) -> bool: ...
    def execute_with_retry(self, sql, params, max_retries): ...
```

`open_sqlite` — единственная публичная точка входа. Возвращает готовый `SqliteEngine`,
`sqlite3.Connection` наружу не выходит никогда.

`transaction(mode=None)` — per-call override поверх `config.transaction_mode`. Vault обычно
использует `immediate` из конфига, но может переопределить для read-only транзакций.

### Источник конфигурации: SqliteSettings

`SqliteDbConfig` строится из `SqliteSettings` в DI-контейнере. Прямые `os.getenv()` внутри
`db.py` и инфра-модулей — удаляются.

**Принцип**: глобальные дефолты + per-DB overrides (`None` = взять global).

**Плоская модель `Settings`** (config.py):
```python
# Глобальные дефолты
sqlite_journal_mode: str = "WAL"
sqlite_synchronous: str = "NORMAL"
sqlite_busy_timeout_ms: int = 5000
sqlite_wal_autocheckpoint: int = 1000

# Vault — per-DB overrides (None = использовать global)
vault_db_path: str | None = None
vault_sqlite_journal_mode: str | None = None
vault_sqlite_busy_timeout_ms: int | None = None
vault_sqlite_transaction_mode: str = "immediate"
vault_sqlite_schema_retry_count: int = 2

# Cache — per-DB overrides
cache_sqlite_journal_mode: str | None = None
cache_sqlite_busy_timeout_ms: int | None = None
cache_sqlite_transaction_mode: str = "deferred"

# Identity — path override (параметры берут global дефолты)
identity_db_path: str | None = None   # None → {cache_dir}/identity.sqlite3
```

**Slice `SqliteSettings`** (app_settings.py → впоследствии Pydantic, см. CONFIG-DEC-002):
```python
@dataclass(frozen=True)
class SqliteSettings:
    # Глобальные дефолты
    journal_mode: str; synchronous: str
    busy_timeout_ms: int; wal_autocheckpoint: int
    # Vault
    vault_db_path: str | None
    vault_transaction_mode: str; vault_journal_mode: str | None
    vault_busy_timeout_ms: int | None; vault_schema_retry_count: int
    # Cache
    cache_transaction_mode: str; cache_journal_mode: str | None
    cache_busy_timeout_ms: int | None
    # Identity (только path override, PRAGMA = global)
    identity_db_path: str | None
```

**Override chain в DI-контейнере:**
```python
def build_vault_db_config(s: SqliteSettings) -> SqliteDbConfig:
    return SqliteDbConfig(
        transaction_mode=s.vault_transaction_mode,
        busy_timeout_ms=s.vault_busy_timeout_ms or s.busy_timeout_ms,
        journal_mode=s.vault_journal_mode or s.journal_mode,
        synchronous=s.synchronous,
        wal_autocheckpoint=s.wal_autocheckpoint,
        schema_retry_count=s.vault_schema_retry_count,
    )

def build_cache_db_config(s: SqliteSettings) -> SqliteDbConfig:
    return SqliteDbConfig(
        transaction_mode=s.cache_transaction_mode,
        busy_timeout_ms=s.cache_busy_timeout_ms or s.busy_timeout_ms,
        journal_mode=s.cache_journal_mode or s.journal_mode,
        synchronous=s.synchronous,
        wal_autocheckpoint=s.wal_autocheckpoint,
    )

def build_identity_db_config(s: SqliteSettings) -> SqliteDbConfig:
    return SqliteDbConfig(
        transaction_mode="deferred",
        busy_timeout_ms=s.busy_timeout_ms,
        journal_mode=s.journal_mode,
        synchronous=s.synchronous,
        wal_autocheckpoint=s.wal_autocheckpoint,
    )
```

**Параметры и их обоснование**:

| Параметр | Default | Зачем конфигурировать |
|----------|---------|----------------------|
| `journal_mode` | `WAL` | WAL для прод, `DELETE`/`MEMORY` для тестов |
| `synchronous` | `NORMAL` | `FULL` для max durability, `OFF` для тестовой скорости |
| `busy_timeout_ms` | `5000` | При конкурентном доступе; в prod может потребоваться увеличить |
| `wal_autocheckpoint` | `1000` | При тяжёлой записи уменьшают, иначе WAL-файл растёт |
| `vault_schema_retry_count` | `2` | Устойчивость к `SQLITE_SCHEMA` |
| `identity_db_path` | `None` | Override пути (например, tmpfs для эфемерных данных) |

Намеренно не выносим (`mmap_size`, `cache_size_kb`, `temp_store`) — тюнинг производительности,
не deploy-параметры.

### Lifecycle через DI-контейнер

Три `Singleton`-провайдера — три соединения, открытых на весь runtime. Новая DB = ещё
один `Singleton`, без дополнительного lifecycle-кода:

```python
# connector/delivery/cli/containers.py
class SqliteContainer(containers.DeclarativeContainer):
    settings = providers.Dependency(instance_of=SqliteSettings)

    cache_engine = providers.Singleton(
        open_sqlite,
        config=providers.Factory(build_cache_db_config, s=settings),
        path=providers.Factory(get_cache_db_path, s=settings),   # → cache.sqlite3
    )
    vault_engine = providers.Singleton(
        open_sqlite,
        config=providers.Factory(build_vault_db_config, s=settings),
        path=providers.Factory(get_vault_db_path, s=settings),   # → vault.sqlite3
    )
    identity_engine = providers.Singleton(
        open_sqlite,
        config=providers.Factory(build_identity_db_config, s=settings),
        path=providers.Factory(get_identity_db_path, s=settings), # → identity.sqlite3
    )

    vault_ready = providers.Resource(
        vault_startup_resource,   # generator: ensure_ready(engine) → yield → cleanup
        engine=vault_engine,
    )
```

`containers.py` полностью заменяет `bootstrap.py`.

### Изменения в существующих компонентах

| Компонент | Тип изменения | Суть |
|-----------|---------------|------|
| `connector/infra/cache/backends/sqlite/engine.py` | Перенос | `SqliteEngine` → `connector/infra/sqlite/engine.py`; старый модуль — re-export до переключения |
| `connector/infra/cache/backends/sqlite/db.py` | Удаление | `openCacheDb` удаляется; engine создаётся DI-контейнером |
| `connector/infra/cache/backends/sqlite/schema.py` | Разделение | Часть схемы (identity-таблицы) переносится в `connector/infra/identity/sqlite/schema.py` |
| `connector/infra/secrets/sqlite/db.py` | Удаление | `VaultSqliteDb` удаляется |
| `connector/infra/secrets/sqlite/repository.py` | Адаптация | `self._conn.execute()` → `self._engine.execute()` |
| `connector/domain/secrets/vault_startup_guard.py` | Упрощение | `_is_storage_readonly()` удаляется; вызывается через `providers.Resource` |
| `connector/config/config.py` | Добавить | ~14 SQLite-полей в `Settings` с валидацией |
| `connector/config/app_settings.py` | Добавить | `SqliteSettings` slice + маппинг |
| `connector/delivery/cli/app.py` | Добавить | CLI-опции для SQLite параметров |
| `connector/delivery/cli/settings_slice_map.py` | Обновить | `SqliteSettings` в слайсы DB-команд |
| `connector/delivery/cli/bootstrap.py` | Заменить | Полностью заменяется на `containers.py` |

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **Нет велосипедного lifecycle-manager**: `dependency-injector` `Singleton` управляет lifetime
- ✅ **Минимальный пакет**: 2 файла — config + engine
- ✅ **`sqlite3.Connection` инкапсулирован**: наружу выходит только `SqliteEngine`
- ✅ **Декларативная регистрация**: новая DB = один `Singleton` в контейнере
- ✅ **`transaction(mode=None)`**: per-call override сохраняет гибкость при дефолте из конфига
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
| `connector/delivery/cli/containers.py` | Создать DI-контейнер (3 Singleton + 1 Resource) |
| `connector/infra/cache/backends/sqlite/db.py` | Удалить `openCacheDb` |
| `connector/infra/cache/backends/sqlite/engine.py` | Re-export → удалить после переключения |
| `connector/infra/cache/backends/sqlite/schema.py` | Выделить identity-схему отдельно |
| `connector/infra/secrets/sqlite/db.py` | Удалить `VaultSqliteDb` |
| `connector/infra/secrets/sqlite/repository.py` | `self._conn` → `self._engine` |
| `connector/domain/secrets/vault_startup_guard.py` | Удалить `_is_storage_readonly` |
| `connector/config/config.py` | Добавить ~14 SQLite-полей с валидацией |
| `connector/config/app_settings.py` | Добавить `SqliteSettings` |
| `connector/delivery/cli/app.py` | Добавить CLI-опции SQLite |
| `connector/delivery/cli/settings_slice_map.py` | Добавить `SqliteSettings` в слайсы |
| `connector/delivery/cli/bootstrap.py` | Удалить (заменён `containers.py`) |

### Инварианты

1. **`sqlite3.Connection` инкапсулирован**: только `open_sqlite` создаёт соединение; наружу — только `SqliteEngine`
2. **Config immutability**: `SqliteDbConfig` — frozen dataclass
3. **Engine per DB**: каждый DB-id имеет ровно один `SqliteEngine`-синглтон в контейнере
4. **transaction mode**: дефолт из `config.transaction_mode`, per-call override через `transaction(mode=...)`

---

## 🧪 Валидация решения

**Тесты**:
- `test_open_sqlite_applies_pragma()` — PRAGMA journal_mode/synchronous/foreign_keys применяются
- `test_open_sqlite_returns_engine()` — возвращает `SqliteEngine`, не `Connection`
- `test_engine_transaction_default_mode()` — `BEGIN DEFERRED` / `BEGIN IMMEDIATE` по конфигу
- `test_engine_transaction_override_mode()` — per-call override работает
- `test_engine_is_readonly()` — readonly detection через sqlite_master
- `test_engine_execute_with_retry_schema()` — retry при SQLITE_SCHEMA
- `test_vault_startup_guard_uses_engine_is_readonly()` — guard не обращается к сырому conn

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
| `SqliteIdentityRepository` | Прямое | Переходит на `identity_engine` из DI |
| `SqliteVaultRepository` | Прямое | `self._conn` → `self._engine` |
| `VaultStartupGuard` | Прямое | Удалить `_is_storage_readonly`; вызываться через `providers.Resource` |
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
