# Cache Infrastructure

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [📊 Database Schema](#-database-schema)
- [🛠️ Как расширять](#️-как-расширять)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Реализация хранилища cache на основе SQLite с поддержкой role-based адаптеров

**Ключевая ответственность**:
- Реализация Cache Ports для SQLite backend
- Управление SQLite соединением и транзакциями
- CRUD операции над cache таблицами (snapshot данных)
- Управление служебными таблицами (meta, pending_links, identity_map, runtime_state)
- Dynamic DDL (CREATE TABLE на основе CacheSpec)
- Schema migrations

**Расположение в кодовой базе**:
- `connector/infra/cache/` — корневой модуль инфраструктуры
- `connector/infra/cache/backends/sqlite/` — SQLite backend
- `connector/infra/cache/roles/` — Role-based адаптеры
- `connector/infra/cache/repository/` — Repositories для служебных таблиц

---

## 🏗️ Архитектура слоя

### Layered Architecture (6 уровней)

```
Level 6: Role-Based Adapters
├─ CacheAdminAdapter, EnrichLookupAdapter, ResolveRuntimeAdapter, etc.
└─ Реализуют Cache Ports для Domain

Level 5: Gateway (Unified Facade)
├─ SqliteCacheGateway
└─ Единая точка входа, координация repositories

Level 4: Repositories
├─ SqliteCacheRepository (snapshot таблицы)
├─ SqliteIdentityRepository (identity_map)
└─ SqlitePendingLinksRepository (pending_links)

Level 3: Handlers
├─ GenericCacheHandler (dataset-specific CRUD)
└─ Генерация SQL для конкретного датасета

Level 2: Schema & Type Mapping
├─ Schema (CREATE TABLE, indexes)
└─ Type mapping (Python types → SQLite types)

Level 1: Engine
├─ SqliteEngine (thin wrapper над sqlite3)
└─ Connection management, transactions, raw SQL execution
```

### Основные компоненты

```
cache_infra/
├── backends/
│   └── sqlite/
│       ├── engine.py                    # Level 1: SqliteEngine
│       ├── schema.py                    # Level 2: DDL, migrations
│       ├── handlers/
│       │   └── generic_handler.py       # Level 3: GenericCacheHandler
│       └── repository/
│           ├── cache_repository.py      # Level 4: Snapshot tables
│           ├── identity_repository.py   # Level 4: Identity map
│           └── pending_links_repository.py  # Level 4: Pending links
│
├── cache_gateway.py                     # Level 5: Unified facade
│
└── roles/                               # Level 6: Port implementations
    ├── admin.py                         # CacheAdminPort adapter
    ├── cache_refresh.py                 # CacheRefreshPort adapter
    ├── enrich_lookup.py                 # EnrichLookupPort adapter
    ├── match_runtime.py                 # MatchRuntimePort adapter
    ├── resolve_runtime.py               # ResolveRuntimePort adapter
    ├── apply_runtime.py                 # ApplyRuntimePort adapter
    ├── planning_runtime.py              # PlanningRuntimePort adapter
    └── bundle.py                        # SqliteCacheRolePorts bundle
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [Infrastructure Class Diagram](../../uml/cache/cache_infra_class.png) | Структура классов инфраструктуры |
| Component | [Component Diagram](../../uml/cache/cache_component_overview.png) | Связь между engine, repositories, gateway |
| Deployment | [Backend Diagram](../../uml/cache/cache_deployment_backends.png) | SQLite backend + возможные будущие backends |

**PlantUML исходники**: `docs/uml/cache/*.puml`

### 🎭 Применённые паттерны

#### Паттерн 1: Ports & Adapters (реализация)

**Где применяется**: Адаптеры реализуют Cache Ports для SQLite

**Реализация в коде**:
```python
# Port (domain/ports/cache/roles.py)
class CacheAdminPort(Protocol):
    def upsert(self, dataset: str, write_model: dict) -> UpsertResult: ...

# Adapter (infra/cache/roles/admin.py)
class SqliteCacheAdminAdapter:
    def __init__(self, gateway: SqliteCacheGateway):
        self._gateway = gateway

    def upsert(self, dataset: str, write_model: dict) -> UpsertResult:
        # Конкретная реализация для SQLite
        return self._gateway.cache.upsert(dataset, write_model)
```

**Зачем**: Domain не зависит от SQLite, можно подменить на PostgreSQL/Redis без изменения domain

#### Паттерн 2: Facade (Gateway)

**Где применяется**: `SqliteCacheGateway` — единая точка входа к cache

**Реализация**:
```python
class SqliteCacheGateway:
    """Unified facade для всех cache операций"""

    def __init__(self, engine: SqliteEngine):
        self.engine = engine
        self.cache = SqliteCacheRepository(engine)
        self.identity = SqliteIdentityRepository(engine)
        self.pending = SqlitePendingLinksRepository(engine)

    @classmethod
    def open(cls, settings: Settings, cache_specs: Iterable[CacheSpec]):
        engine = SqliteEngine.connect(settings.cache_db_path)
        ensure_cache_ready(engine, cache_specs)
        return cls.from_engine(engine, cache_specs)
```

**Зачем**: Упрощает инициализацию, скрывает сложность работы с multiple repositories

#### Паттерн 3: Repository Pattern

**Где применяется**: Repositories для разных служебных таблиц

**Реализация**:
- `SqliteCacheRepository` — для snapshot таблиц (employees, organizations, etc.)
- `SqliteIdentityRepository` — для `identity_map` таблицы
- `SqlitePendingLinksRepository` — для `pending_links` таблицы

**Зачем**: Изоляция логики доступа к данным, каждый repository отвечает за свою область

#### Паттерн 4: Handler Strategy

**Где применяется**: `GenericCacheHandler` для dataset-specific операций

**Реализация**:
```python
class GenericCacheHandler:
    def __init__(self, spec: CacheSpec):
        self._spec = spec
        # Строит SQL на основе spec

    def upsert(self, engine: SqliteEngine, write_model: dict) -> UpsertResult:
        sql = f"INSERT INTO {self._spec.table} (...) VALUES (...) ON CONFLICT (...) DO UPDATE ..."
        engine.execute(sql, params)
```

**Зачем**: Один handler на любой датасет, generic SQL generation

---

## 🔑 Ключевые абстракции

### Core Classes

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
| `SqliteEngine` | Low-level wrapper над sqlite3 | `execute()`, `fetchone()`, `fetchall()`, `transaction()` |
| `GenericCacheHandler` | Dataset-specific CRUD | `upsert()`, `count()`, `clear()`, `rebuild()`, `find()` |
| `SqliteCacheRepository` | Repository для snapshot таблиц | `upsert()`, `count()`, `find()`, `clear()`, `get_meta()`, `set_meta()` |
| `SqliteIdentityRepository` | Repository для identity_map | `find_candidates()`, `set_runtime_state()`, `get_runtime_state()` |
| `SqlitePendingLinksRepository` | Repository для pending_links | `add_pending()`, `mark_resolved()`, `sweep_expired()` |
| `SqliteCacheGateway` | Unified facade | `open()`, `close()`, `transaction()`, + доступ к repositories |

### Role-Based Adapters

| Adapter | Реализует Port | Используется в |
|---------|---------------|---------------|
| `SqliteCacheAdminAdapter` | `CacheAdminPort` | Admin операции (upsert, count, clear) |
| `SqliteCacheRefreshAdapter` | `CacheRefreshPort` | Refresh операции |
| `SqliteEnrichLookupAdapter` | `EnrichLookupPort` | Enrich lookup операции |
| `SqliteMatchRuntimeAdapter` | `MatchRuntimePort` | Match runtime state |
| `SqliteResolveRuntimeAdapter` | `ResolveRuntimePort` | Pending links lifecycle |
| `SqliteApplyRuntimeAdapter` | `ApplyRuntimePort` | Identity sync после apply |
| `SqlitePlanningRuntimeAdapter` | `PlanningRuntimePort` | Unified planning port |

---

## 📊 Database Schema

### Service Tables (служебные)

#### `meta` — Метаданные кэша

```sql
CREATE TABLE meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
```

**Ключи**:
- `schema_version` — версия схемы cache (текущая: 6)
- `{dataset}.schema_hash` — SHA256 schema датасета
- `{dataset}.sync_hash` — SHA256 sync spec датасета
- `{dataset}.last_sync` — timestamp последней синхронизации

**Пример**:
```sql
INSERT INTO meta VALUES ('schema_version', '6');
INSERT INTO meta VALUES ('employees.schema_hash', 'abc123...');
```

---

#### `pending_links` — Unresolved FK ссылки

```sql
CREATE TABLE pending_links (
  pending_id INTEGER PRIMARY KEY AUTOINCREMENT,
  dataset TEXT NOT NULL,
  source_row_id TEXT NOT NULL,
  field TEXT NOT NULL,
  lookup_key TEXT NOT NULL,
  status TEXT NOT NULL,                -- pending, resolved, conflict, expired
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  last_attempt_at TEXT,
  expires_at TEXT,
  reason TEXT,
  payload TEXT
);

CREATE INDEX idx_pending_links_dataset_status ON pending_links(dataset, status);
CREATE INDEX idx_pending_links_source_row_id ON pending_links(source_row_id);
```

**Lifecycle**:
1. `add_pending()` → status = 'pending'
2. `touch_attempt()` → attempts++
3. `mark_resolved()` → status = 'resolved'
4. `sweep_expired()` → status = 'expired' и удаление

---

#### `identity_map` — Identity resolution mapping

```sql
CREATE TABLE identity_map (
  dataset TEXT NOT NULL,
  identity_key TEXT NOT NULL,
  resolved_id TEXT NOT NULL,
  PRIMARY KEY (dataset, identity_key)
);
```

**Использование**: Matcher использует для хранения resolved identity ключей.

**Пример**:
```sql
INSERT INTO identity_map VALUES ('employees', 'emp_123', 'user_456');
```

---

#### `runtime_state` — Runtime state для matcher

```sql
CREATE TABLE runtime_state (
  scope TEXT NOT NULL,
  dataset TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT,
  PRIMARY KEY (scope, dataset, key)
);
```

**Использование**: Хранение runtime state между запусками matcher (например, last processed ID).

---

### Dataset Tables (динамические)

Создаются на основе `CacheSpec` из DSL.

**Пример для датасета `employees`**:

```sql
CREATE TABLE users (
  _id TEXT NOT NULL,
  _ouid INTEGER NOT NULL,
  personnel_number TEXT NOT NULL,
  last_name TEXT NOT NULL,
  first_name TEXT NOT NULL,
  middle_name TEXT NOT NULL,
  match_key TEXT NOT NULL,
  mail TEXT NOT NULL,
  user_name TEXT NOT NULL,
  phone TEXT,
  organization_id INTEGER NOT NULL,
  account_status TEXT,
  deletion_date TEXT,
  _rev TEXT,
  manager_ouid INTEGER,
  is_logon_disabled INTEGER,
  position TEXT,
  updated_at TEXT,
  PRIMARY KEY (_id)
);

CREATE UNIQUE INDEX uidx_users_ouid ON users(_ouid);
CREATE UNIQUE INDEX uidx_users_match_key ON users(match_key);
CREATE INDEX idx_users_personnel_number ON users(personnel_number);
CREATE INDEX idx_users_organization_id ON users(organization_id);
```

**Type mapping** (Python → SQLite):
| Python Type | SQLite Type |
|------------|------------|
| `string` | TEXT |
| `int` | INTEGER |
| `bool` | INTEGER (0/1) |
| `float` | REAL |
| `datetime` | TEXT (ISO 8601) |
| `json` | TEXT (JSON string) |

---

## 🛠️ Как расширять

### Добавление нового backend (PostgreSQL/Redis)

1. **Создать backend module**:
```
connector/infra/cache/backends/postgresql/
├── engine.py                   # PostgresEngine
├── schema.py                   # PostgreSQL DDL
├── handlers/
│   └── generic_handler.py      # PostgreSQL-specific handler
└── repository/
    ├── cache_repository.py
    └── ...
```

2. **Реализовать PostgresEngine**:
```python
class PostgresEngine:
    def __init__(self, connection: psycopg2.Connection):
        self._conn = connection

    def execute(self, sql: str, params: dict): ...
    def transaction(self): ...
```

3. **Создать PostgresCacheGateway**:
```python
class PostgresCacheGateway:
    @classmethod
    def open(cls, settings, cache_specs):
        engine = PostgresEngine.connect(settings.pg_url)
        ...
```

4. **Переиспользовать role-based адаптеры** (они backend-agnostic):
```python
# Адаптеры работают с любым gateway
adapter = SqliteCacheAdminAdapter(gateway=postgres_gateway)
```

### Добавление нового роль-based порта

1. **Определить Port** в `domain/ports/cache/roles.py`:
```python
class NewRolePort(Protocol):
    def new_operation(self, dataset: str) -> Result: ...
```

2. **Создать Adapter** в `infra/cache/roles/new_role.py`:
```python
class SqliteNewRoleAdapter:
    def __init__(self, gateway: SqliteCacheGateway):
        self._gateway = gateway

    def new_operation(self, dataset: str) -> Result:
        # Реализация через gateway repositories
        ...
```

3. **Добавить в bundle**:
```python
@dataclass(frozen=True)
class SqliteCacheRolePorts:
    ...
    new_role: NewRolePort  # Новый порт
```

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| Cache Ports | Реализует | Role-based адаптеры | Infrastructure реализует контракты Ports |
| Cache DSL | Потребляет | `CacheSpec` | DSL компилирует spec, Infrastructure создаёт таблицы на его основе |
| UseCases | Используется | DI с адаптерами | UseCases получают адаптеры через DI, вызывают методы |
| Configuration | Зависимость | `Settings` | Settings содержит `cache_db_path`, `cache_dir` |

**Важно**: Infrastructure — единственный слой, который знает о SQLite. Domain и UseCases infrastructure-agnostic.

---

## 🔌 Контракты и границы

### Runtime-контракт

**Входные данные** для Gateway:

```python
# 1. Settings
settings = Settings(
    cache_dir="/path/to/cache",
    cache_db_path="/path/to/cache.db"
)

# 2. CacheSpec (из DSL)
cache_specs = [
    CacheSpec(dataset="employees", table="users", primary_key=("_id",), ...),
    CacheSpec(dataset="organizations", table="organizations", ...)
]

# 3. Инициализация
gateway = SqliteCacheGateway.open(
    settings=settings,
    cache_specs=cache_specs
)
```

**Выходные данные** (role-based адаптеры):

```python
# Получить bundle адаптеров
from connector.infra.cache.roles.bundle import build_sqlite_cache_role_ports

ports = build_sqlite_cache_role_ports(gateway)

# Используется в UseCases
use_case = RefreshCacheUseCase(cache=ports.cache_refresh)
```

**Гарантии**:
- Database инициализирована с правильной `schema_version`
- Все dataset таблицы созданы на основе `CacheSpec`
- Служебные таблицы (meta, pending_links, identity_map) созданы
- Транзакции поддерживают вложенность (savepoints)

---

### Boundaries слоёв

**Разрешенные зависимости**:
- ✅ `Infrastructure` → `Ports (Protocols)` — реализация контрактов
- ✅ `Infrastructure` → `sqlite3` (stdlib) — использование SQLite
- ✅ `Infrastructure` → `CacheSpec` (DTO из Ports) — создание таблиц

**Запрещенные зависимости**:
- ❌ `Infrastructure` → `UseCases` — Infrastructure не знает о use cases
- ❌ `Infrastructure` → `Domain Core` — Infrastructure не зависит от доменной логики
- ❌ `Domain/UseCases` → `Infrastructure` — Domain зависит только от Ports

**Визуальная граница**:

```
┌─────────────────────────────────────────┐
│ UseCases (Application)                  │  ← Зависит только от Ports
└────────────▼────────────────────────────┘
             │ uses (DI)
┌────────────▼────────────────────────────┐
│ Ports (Protocols)                       │  ← Контракты
└────────────▲────────────────────────────┘
             │ implements
┌────────────▼────────────────────────────┐
│ Infrastructure (SQLite Adapters)        │  ← Реализация
│  ├─ Engine (sqlite3 wrapper)            │
│  ├─ Repositories                        │
│  ├─ Gateway (facade)                    │
│  └─ Role-Based Adapters                 │
└─────────────────────────────────────────┘
```

---

## 💡 Типичные сценарии

### Сценарий 1: Инициализация cache при старте приложения

**Задача**: Открыть cache DB и инициализировать схему

**Решение**:
```python
from connector.infra.cache.cache_gateway import SqliteCacheGateway
from connector.config.config import Settings

# 1. Загрузить settings
settings = Settings.load()

# 2. Скомпилировать DSL (получить cache_specs)
runtime = compile_cache_runtime(...)

# 3. Открыть gateway
gateway = SqliteCacheGateway.open(
    settings=settings,
    cache_specs=runtime.cache_specs
)

# 4. Gateway готов к использованию
print(f"Cache opened: {gateway.engine._conn}")
```

**Объяснение**: `open()` автоматически проверяет schema version, выполняет migrations, создаёт таблицы.

---

### Сценарий 2: Получение role-based портов для UseCases

**Задача**: Получить адаптеры для всех use cases

**Решение**:
```python
from connector.infra.cache.roles.bundle import build_sqlite_cache_role_ports

# Получить bundle портов
ports = build_sqlite_cache_role_ports(gateway)

# Inject в UseCases
refresh_use_case = RefreshCacheUseCase(cache=ports.cache_refresh)
enrich_use_case = EnrichUseCase(lookup=ports.enrich_lookup)
match_use_case = MatchUseCase(cache=ports.planning_runtime)
```

**Объяснение**: Bundle предоставляет все role-based адаптеры из одного gateway.

---

### Сценарий 3: Транзакции с вложенностью

**Задача**: Выполнить несколько операций в одной транзакции

**Решение**:
```python
with gateway.transaction():
    # Все операции в одной транзакции
    gateway.cache.upsert("employees", row1)
    gateway.cache.upsert("employees", row2)
    gateway.identity.upsert_identity("employees", key, resolved_id)

    # Вложенная транзакция (savepoint)
    with gateway.transaction():
        gateway.pending.add_pending(...)
        # Если ошибка здесь, откатится только savepoint
```

**Объяснение**: `SqliteEngine` поддерживает вложенные транзакции через savepoints.

---

## 📌 Важные детали

### Особенности реализации

- **SQLite WAL mode**: Используется Write-Ahead Logging для лучшего concurrent access
- **Foreign keys**: Отключены в SQLite (контролируется на уровне приложения)
- **Type affinity**: SQLite использует dynamic typing, но мы соблюдаем strict types
- **Schema versioning**: Каждая schema version поддерживает forward migrations
- **Generic handlers**: Один handler на любой датасет (dynamic SQL generation)
- **Connection pooling**: Не используется (SQLite single-writer, multiple-readers)

### 🚨 Failure Modes

| Исключение | Условие возникновения | Поведение системы | Как обработать |
|------------|----------------------|-------------------|---------------|
| `sqlite3.IntegrityError` | Нарушение unique constraint или PK | Операция откатывается, exception поднимается | Проверить данные перед upsert, убедиться что PK уникален |
| `sqlite3.OperationalError: database is locked` | Concurrent write операции | Timeout при попытке получить lock | Использовать транзакции, retry с exponential backoff |
| `FileNotFoundError` | cache_db_path не существует (при открытии существующей DB) | Exception при `SqliteEngine.connect()` | Создать директорию заранее или использовать `open()` который создаёт DB |
| `ValueError: "Schema version mismatch"` | schema_version в meta не совпадает с ожидаемой | Выбрасывается при `ensure_cache_ready()` | Выполнить migration или rebuild cache |
| `sqlite3.DatabaseError: malformed database` | Повреждённый файл DB | Exception при любой операции | Удалить файл DB, rebuild cache заново |

**Примеры**:

```python
# ❌ IntegrityError: duplicate primary key
gateway.cache.upsert("employees", {"_id": "123", ...})
gateway.cache.upsert("employees", {"_id": "123", ...})  # ← Если не используется ON CONFLICT

# ✅ Upsert с ON CONFLICT
result = gateway.cache.upsert("employees", {"_id": "123", ...})
# → UpsertResult.INSERTED or UpsertResult.UPDATED
```

### Частые ошибки

- ❌ **Не делай так**: Забыть закрыть gateway
  ```python
  gateway = SqliteCacheGateway.open(...)
  # ... использование
  # Не вызвали gateway.close() → connection leak
  ```

- ✅ **Делай так**: Использовать context manager
  ```python
  with SqliteCacheGateway.open(...) as gateway:
      # ... использование
  # Автоматически закроется
  ```

- ❌ **Не делай так**: Параллельные write без транзакций
  ```python
  # Thread 1
  gateway.cache.upsert("employees", row1)

  # Thread 2 (одновременно)
  gateway.cache.upsert("employees", row2)
  # → "database is locked" error
  ```

- ✅ **Делай так**: Batch upserts в одной транзакции
  ```python
  with gateway.transaction():
      for row in rows:
          gateway.cache.upsert("employees", row)
  ```

### ⚠️ Инварианты системы

1. **Инвариант: Schema version соответствует коду**
   - **Что**: `meta.schema_version` = `SCHEMA_VERSION` константа
   - **Почему важно**: Предотвращает incompatibility между code и DB schema
   - **Где проверяется**: `ensure_cache_ready()` при инициализации

2. **Инвариант: Dataset таблицы соответствуют CacheSpec**
   - **Что**: Все поля из `CacheSpec.fields` существуют в таблице
   - **Почему важно**: Предотвращает errors при upsert/select
   - **Где проверяется**: `GenericCacheHandler.ensure_schema()` создаёт таблицу на основе spec

3. **Инвариант: Pending links имеют валидный status**
   - **Что**: `status` ∈ {'pending', 'resolved', 'conflict', 'expired'}
   - **Почему важно**: Предотвращает некорректные state transitions
   - **Где проверяется**: Repository методы проверяют допустимые статусы

### ⏱️ Performance заметки

**Узкие места**:
1. **Sequential upserts** — O(N) где N = количество записей
   - **Текущая оптимизация**: Batch upserts в транзакции (100-1000 записей в одной транзакции)

2. **Dynamic SQL generation** — O(F) где F = количество полей
   - **Текущая оптимизация**: SQL кэшируется в handler

3. **Indexes** — увеличивают скорость read, замедляют write
   - **Текущая оптимизация**: Только необходимые индексы из CacheSpec

**Benchmark данные**:
- Upsert 1000 записей (без транзакции): ~5 секунд
- Upsert 1000 записей (в одной транзакции): ~0.5 секунд (10x faster)
- Lookup by PK: ~0.1ms
- Lookup by indexed field: ~0.5ms
- Full table scan (10k записей): ~50ms

**Рекомендации**:
- Всегда использовать транзакции для batch operations
- Создавать индексы только для часто используемых полей
- Использовать `VACUUM` периодически для defragmentation
- Для очень больших датасетов (>1M записей) рассмотреть PostgreSQL

---

## 🔗 Связанные документы

- [Cache DSL](./cache-dsl.md) — Компилятор DSL, создаёт `CacheSpec`
- [Cache Ports](./cache-ports.md) — Контракты, которые реализует Infrastructure
- [Cache Core](./cache-core.md) — Доменная логика cache планирования
- [CACHE-DEC-001](../../adr/cache/CACHE-DEC-001-topological-sort-for-dependencies.md) — ADR по топологической сортировке

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-11 | Создан документ Cache Infrastructure | xORex-LC |
