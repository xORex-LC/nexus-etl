# Cache Ports

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Определение интерфейсов (Protocols) для работы с кэшем по принципу Role-Based Access

**Ключевая ответственность**:
- Определение границ между доменом и инфраструктурой (Ports & Adapters)
- Role-based сегрегация операций (CacheAdmin, EnrichLookup, MatchRuntime, etc.)
- DTO модели для передачи данных через границы слоёв
- Контракты для pending links, identity mapping, runtime state

**Расположение в кодовой базе**:
- `connector/domain/ports/cache/models.py` (103 строки) — DTO модели
- `connector/domain/ports/cache/roles.py` (149 строк) — Protocol классы

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
cache_ports/
├── models.py                      # DTO модели (граничные модели)
│   ├── UpsertResult               # Enum результата upsert
│   ├── FieldSpec                  # Описание поля cache таблицы
│   ├── CacheSpec                  # Скомпилированная schema
│   ├── CacheMeta                  # Метаданные кэша (k/v)
│   ├── PendingStatus              # Enum статуса pending-ссылки
│   └── PendingLink                # DTO для pending-ссылок
│
└── roles.py                       # Protocol классы (контракты)
    ├── CacheAdminPort             # Администрирование кэша
    ├── EnrichLookupPort           # Lookup для enrich-стадии
    ├── MatchRuntimePort           # Runtime state для matcher
    ├── ResolveRuntimePort         # Pending links для resolver
    ├── ApplyRuntimePort           # Identity sync для apply
    ├── CacheRefreshPort           # Refresh операции
    └── PlanningRuntimePort        # Unified контракт для planning
```

### 📐 UML диаграммы

| Тип | Диаграмма | Описание |
|-----|-----------|----------|
| Class | [Cache Ports Class Diagram](../../uml/cache/cache_ports_class.png) | Структура Protocol классов |
| Component | [Role-Based Ports](../../uml/cache/cache_ports_component.png) | Взаимодействие портов с UseCases |

**PlantUML исходники**: `docs/uml/cache/*.puml`

### 🎭 Применённые паттерны

#### Паттерн 1: Ports & Adapters (Hexagonal Architecture)

**Где применяется**: Разделение доменной логики от инфраструктуры

**Реализация в коде**:
- **Ports**: Protocol классы в `roles.py` (абстракции)
- **Adapters**: Реализации в `connector/infra/cache/roles/` (конкретные имплементации для SQLite)
- **Domain**: UseCases зависят только от портов, не знают о конкретных адаптерах

**Пример использования**:
```python
# Domain зависит только от порта (абстракции)
class RefreshCacheUseCase:
    def __init__(self, cache: CacheRefreshPort):
        self._cache = cache  # Protocol, не конкретная реализация

# Infrastructure предоставляет адаптер
class SqliteCacheRefreshAdapter(CacheRefreshPort):
    def upsert(self, dataset: str, write_model: dict) -> UpsertResult:
        # Конкретная реализация для SQLite
        ...
```

**Зачем**: Доменная логика не зависит от деталей инфраструктуры (БД, Redis, файлы), легко подменять реализации для тестирования

#### Паттерн 2: Interface Segregation (SOLID)

**Где применяется**: Разделение портов по ролям вместо одного большого интерфейса

**Реализация**:
- `CacheAdminPort` — только admin операции
- `EnrichLookupPort` — только lookup для enrich
- `MatchRuntimePort` — только runtime state для matcher
- `ResolveRuntimePort` — только pending links для resolver
- `PlanningRuntimePort` — композиция `MatchRuntimePort + ResolveRuntimePort`

**Зачем**: UseCase зависит только от нужных ему операций, не получает доступ к лишним методам

#### Паттерн 3: DTO (Data Transfer Objects)

**Где применяется**: Модели в `models.py` для передачи данных через границы

**Реализация**:
```python
@dataclass(frozen=True)
class CacheSpec:
    """DTO для передачи схемы cache таблицы"""
    dataset: str
    table: str
    primary_key: tuple[str, ...]
    fields: tuple[FieldSpec, ...]
```

**Зачем**: Явные контракты данных, immutability, не зависит от ORM/DB моделей

### Диаграмма зависимостей

```
[UseCases] → [Ports (Protocols)] ← [Adapters (Infrastructure)]
                   ↓
              [DTO Models]
```

---

## 🔑 Ключевые абстракции

### Role-Based Порты (Protocols)

| Protocol | Назначение | Используется в |
|----------|-----------|---------------|
| `CacheAdminPort` | Admin операции (upsert, count, clear, rebuild, meta) | `RefreshCacheUseCase`, `ClearCacheUseCase` |
| `EnrichLookupPort` | Lookup/exists для enrich-стадии | `EnrichUseCase` |
| `MatchRuntimePort` | Runtime state для matcher (find + state management) | `MatchUseCase` |
| `ResolveRuntimePort` | Pending links lifecycle | `ResolveUseCase` |
| `ApplyRuntimePort` | Identity sync после apply | `ApplyUseCase` |
| `CacheRefreshPort` | Refresh операции (extends CacheAdminPort + ApplyRuntimePort) | `RefreshCacheUseCase` |
| `PlanningRuntimePort` | Unified контракт для planning (extends MatchRuntime + ResolveRuntime) | `PlanningUseCase` |

### DTO Модели

| DTO | Роль | Ключевые поля |
|-----|------|--------------|
| `CacheSpec` | Описание schema cache таблицы | `dataset`, `table`, `primary_key`, `fields`, `indexes` |
| `FieldSpec` | Описание одного поля | `name`, `type`, `nullable`, `source` |
| `CacheMeta` | Метаданные кэша (k/v) | `values: dict[str, str \| None]` |
| `PendingLink` | DTO pending-ссылки | `pending_id`, `dataset`, `source_row_id`, `field`, `lookup_key`, `status` |
| `UpsertResult` | Enum результата upsert | `INSERTED`, `UPDATED` |
| `PendingStatus` | Enum статуса pending | `PENDING`, `RESOLVED`, `CONFLICT`, `EXPIRED` |

---

## 🗂️ Модели данных

### Dataclass: `CacheSpec`

**Назначение**: Скомпилированное описание schema cache таблицы

**Структура**:
```python
@dataclass(frozen=True)
class CacheSpec:
    dataset: str                           # Имя датасета
    table: str                             # Имя таблицы в cache DB
    primary_key: tuple[str, ...]           # Список полей PK
    fields: tuple[FieldSpec, ...]          # Описание всех полей
    unique_indexes: tuple[tuple[str, ...], ...] = ()  # Уникальные индексы
    indexes: tuple[tuple[str, ...], ...] = ()         # Обычные индексы
```

**Где используется**: Передаётся в `SqliteCacheGateway.open()` для CREATE TABLE

**Пример**:
```python
spec = CacheSpec(
    dataset="employees",
    table="users",
    primary_key=("_id",),
    fields=(
        FieldSpec(name="_id", type="string", nullable=False),
        FieldSpec(name="_ouid", type="int", nullable=False),
        FieldSpec(name="mail", type="string", nullable=False),
    ),
    unique_indexes=(("_ouid",), ("match_key",)),
    indexes=(("organization_id",),)
)
```

**Lifecycle**:
1. **Создание**: Компилируется из DSL в `compile_cache_runtime()`
2. **Передача**: Через границу domain → infrastructure
3. **Использование**: Infrastructure создаёт таблицы на основе spec
4. **Immutable**: frozen=True, не изменяется после создания

---

### Dataclass: `FieldSpec`

**Назначение**: Описание одного поля cache таблицы

**Структура**:
```python
@dataclass(frozen=True)
class FieldSpec:
    name: str                  # Имя поля
    type: str                  # Тип поля (string, int, bool, float, datetime, json)
    nullable: bool = True      # Может ли быть NULL
    source: str | None = None  # Source field name (опционально, для метаданных)
```

**Пример**:
```python
field = FieldSpec(
    name="personnel_number",
    type="string",
    nullable=False,
    source="personnelNumber"
)
```

---

### Dataclass: `CacheMeta`

**Назначение**: Метаданные кэша (key-value хранилище)

**Структура**:
```python
@dataclass(frozen=True)
class CacheMeta:
    values: dict[str, str | None]  # Словарь метаданных {key: value}
```

**Примеры ключей**:
- `schema_version` — версия схемы cache
- `{dataset}.schema_hash` — SHA256 schema датасета
- `{dataset}.sync_hash` — SHA256 sync spec датасета
- `{dataset}.last_sync` — timestamp последней синхронизации

**Пример**:
```python
meta = CacheMeta(values={
    "schema_version": "6",
    "employees.schema_hash": "abc123...",
    "employees.sync_hash": "def456...",
    "employees.last_sync": "2026-02-11T10:00:00Z"
})
```

---

### Dataclass: `PendingLink`

**Назначение**: DTO для pending-ссылки (unresolved FK)

**Структура**:
```python
@dataclass(frozen=True)
class PendingLink:
    pending_id: int                # Уникальный ID pending-ссылки
    dataset: str                   # Датасет, где pending
    source_row_id: str             # ID строки-источника
    field: str                     # Имя FK поля
    lookup_key: str                # Ключ для lookup в target датасете
    status: str                    # Статус (pending, resolved, conflict, expired)
    attempts: int                  # Количество попыток resolve
    created_at: str | None         # Timestamp создания
    last_attempt_at: str | None    # Timestamp последней попытки
    expires_at: str | None         # Timestamp истечения
    reason: str | None             # Причина (для conflict/expired)
    payload: str | None            # Дополнительные данные (JSON)
```

**Lifecycle**:
1. **Создание**: `add_pending()` при unresolved FK
2. **Retry**: `touch_attempt()` при повторной попытке resolve
3. **Resolved**: `mark_resolved()` при успешном resolve
4. **Conflict**: `mark_conflict()` при ambiguous match
5. **Expired**: `sweep_expired()` удаляет истекшие

**Пример**:
```python
pending = PendingLink(
    pending_id=1,
    dataset="employee_mappings",
    source_row_id="row_123",
    field="employee_id",
    lookup_key="emp_456",
    status="pending",
    attempts=1,
    created_at="2026-02-11T10:00:00Z",
    expires_at="2026-03-13T10:00:00Z"  # 30 дней retention
)
```

---

### Enum: `UpsertResult`

**Назначение**: Результат операции upsert

**Значения**:
```python
class UpsertResult(str, Enum):
    INSERTED = "inserted"  # Запись создана
    UPDATED = "updated"    # Запись обновлена
```

**Использование**:
```python
result = cache.upsert(dataset="employees", write_model={...})
if result == UpsertResult.INSERTED:
    print("New record created")
elif result == UpsertResult.UPDATED:
    print("Existing record updated")
```

---

### Enum: `PendingStatus`

**Назначение**: Статус pending-ссылки

**Значения**:
```python
class PendingStatus(str, Enum):
    PENDING = "pending"      # Ожидает resolve
    RESOLVED = "resolved"    # Успешно резолвлен
    CONFLICT = "conflict"    # Ambiguous match
    EXPIRED = "expired"      # Истёк retention период
```

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| UseCases | Зависимость | Protocol классы | UseCases зависят от портов, не от конкретных реализаций |
| Infrastructure | Реализация | Adapters в `connector/infra/cache/roles/` | Адаптеры реализуют портов для конкретного backend |
| Domain Core | Использует DTO | `CacheSpec`, `PendingLink` | Domain создаёт DTO для передачи через границу |
| Cache DSL | Создаёт DTO | `CacheSpec` | DSL Compiler создаёт `CacheSpec` из YAML |

**Важно**: Порты — это **контракты**, они не содержат логики. Вся логика в адаптерах (Infrastructure).

---

## 🔌 Контракты и границы

### Protocol контракты

Каждый Protocol определяет строгий контракт методов без реализации.

#### `CacheAdminPort`

```python
class CacheAdminPort(Protocol):
    """Администрирование и snapshot операции кэша"""

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Открыть транзакцию"""
        ...

    def upsert(self, dataset: str, write_model: dict) -> UpsertResult:
        """Вставить или обновить запись в cache"""
        ...

    def count(self, dataset: str) -> int:
        """Количество записей в датасете"""
        ...

    def count_by_table(self, dataset: str) -> dict[str, int]:
        """Количество записей по таблицам датасета"""
        ...

    def clear(self, dataset: str) -> None:
        """Очистить все данные датасета"""
        ...

    def rebuild(self, dataset: str) -> None:
        """Пересоздать schema датасета (DROP + CREATE)"""
        ...

    def list_datasets(self) -> list[str]:
        """Список всех датасетов в cache"""
        ...

    def get_meta(self, dataset: str | None = None) -> CacheMeta:
        """Получить метаданные (глобальные или датасета)"""
        ...

    def set_meta(self, dataset: str | None, key: str, value: str | None) -> None:
        """Установить метаданные"""
        ...
```

**Используется в**: `RefreshCacheUseCase`, `ClearCacheUseCase`, `StatusCacheUseCase`

---

#### `ResolveRuntimePort`

```python
class ResolveRuntimePort(Protocol):
    """Контракт resolve-стадии для pending links lifecycle"""

    def find_candidates(self, dataset: str, identity_key: str) -> list[str]:
        """Найти кандидатов в identity map по ключу"""
        ...

    def add_pending(
        self,
        dataset: str,
        source_row_id: str,
        field: str,
        lookup_key: str,
        expires_at: str | None = None,
        payload: dict | None = None
    ) -> int:
        """Создать pending-ссылку, вернуть pending_id"""
        ...

    def list_pending_rows(self, dataset: str) -> list[PendingRow]:
        """Список всех pending-строк датасета"""
        ...

    def mark_resolved_for_source(self, source_row_id: str) -> None:
        """Пометить все pending для source как resolved"""
        ...

    def mark_conflict(self, pending_id: int, reason: str) -> None:
        """Пометить pending как conflict"""
        ...

    def sweep_expired(self, now: str, reason: str) -> list[PendingLink]:
        """Удалить истекшие pending-ссылки"""
        ...

    def purge_stale(self, cutoff: str, statuses: list[str]) -> int:
        """Удалить старые pending по статусам"""
        ...
```

**Используется в**: `ResolveUseCase`, `PendingReplayUseCase`

---

#### `PlanningRuntimePort`

```python
class PlanningRuntimePort(MatchRuntimePort, ResolveRuntimePort, Protocol):
    """
    Unified контракт для planning стадии (matcher + resolver).

    Объединяет:
    - MatchRuntimePort: find() + runtime state
    - ResolveRuntimePort: pending links lifecycle
    """
```

**Зачем композиция**:
- UseCase может зависеть от одного порта вместо двух
- Адаптер реализует оба интерфейса одновременно
- Упрощает DI (один параметр вместо двух)

**Используется в**: `PlanningUseCase` (комбинированный workflow match + resolve)

---

### Границы слоёв

**Разрешенные зависимости**:
- ✅ `UseCases` → `Ports (Protocols)` — зависимость от абстракций
- ✅ `Infrastructure Adapters` → `Ports (Protocols)` — реализация контрактов
- ✅ `Domain Core` → `DTO Models` — использование граничных моделей

**Запрещенные зависимости**:
- ❌ `Ports` → `Infrastructure` — порты не знают о реализациях
- ❌ `UseCases` → `Infrastructure Adapters` — UseCases зависят только от портов
- ❌ `Ports` → `SQLAlchemy`, `Redis` — порты infrastructure-agnostic

**Визуальная граница**:

```
┌─────────────────────────────────────────┐
│ Infrastructure (Adapters)               │  ← Реализует Protocols
│  ├─ SqliteCacheAdminAdapter             │
│  ├─ SqliteResolveRuntimeAdapter         │
│  └─ ...                                 │
└────────────▲────────────────────────────┘
             │ implements
┌────────────┴────────────────────────────┐
│ Ports (Protocols)                       │  ← Контракты без реализации
│  ├─ CacheAdminPort                      │
│  ├─ ResolveRuntimePort                  │
│  └─ ...                                 │
└────────────▲────────────────────────────┘
             │ depends on
┌────────────┴────────────────────────────┐
│ UseCases (Application)                  │  ← Зависит только от портов
│  ├─ RefreshCacheUseCase                 │
│  ├─ ResolveUseCase                      │
│  └─ ...                                 │
└─────────────────────────────────────────┘
```

**Принцип**: **Dependency Inversion** (SOLID) — высокоуровневые модули (UseCases) не зависят от низкоуровневых (Infrastructure), оба зависят от абстракций (Ports).

---

## 💡 Типичные сценарии

### Сценарий 1: UseCase использует порт через DI

**Задача**: UseCase должен работать с cache, не зная о конкретной реализации

**Решение**:
```python
# UseCase зависит только от порта
class RefreshCacheUseCase:
    def __init__(self, cache: CacheRefreshPort):
        self._cache = cache  # Protocol, не конкретный класс

    def execute(self, dataset: str) -> None:
        with self._cache.transaction():
            data = fetch_from_source(dataset)
            for row in data:
                result = self._cache.upsert(dataset, row)
                print(f"Upsert result: {result}")

# Dependency Injection с адаптером
from connector.infra.cache.roles.cache_refresh import SqliteCacheRefreshAdapter

adapter = SqliteCacheRefreshAdapter(gateway=sqlite_gateway)
use_case = RefreshCacheUseCase(cache=adapter)  # ← DI

use_case.execute("employees")
```

**Объяснение**: UseCase не знает, что за ним SQLite. Можно подменить на Redis/PostgreSQL без изменения UseCase.

---

### Сценарий 2: Mock порта для тестирования

**Задача**: Протестировать UseCase без реального cache

**Решение**:
```python
import pytest
from unittest.mock import Mock

def test_refresh_cache_use_case():
    # Создать mock порта
    mock_cache = Mock(spec=CacheRefreshPort)
    mock_cache.upsert.return_value = UpsertResult.INSERTED

    # Inject mock в UseCase
    use_case = RefreshCacheUseCase(cache=mock_cache)

    # Execute
    use_case.execute("employees")

    # Verify
    assert mock_cache.transaction.called
    assert mock_cache.upsert.called
```

**Объяснение**: Protocol позволяет легко создавать mocks для unit-тестов.

---

### Сценарий 3: Композиция портов (PlanningRuntimePort)

**Задача**: UseCase нужны операции и из MatchRuntime, и из ResolveRuntime

**Решение**:
```python
class PlanningUseCase:
    def __init__(self, cache: PlanningRuntimePort):
        self._cache = cache  # Композиция MatchRuntime + ResolveRuntime

    def execute(self, dataset: str) -> None:
        # Используем методы MatchRuntime
        candidates = self._cache.find(dataset, filters={...})

        # Используем методы ResolveRuntime
        pending_id = self._cache.add_pending(
            dataset=dataset,
            source_row_id="row_123",
            field="employee_id",
            lookup_key="emp_456"
        )
```

**Объяснение**: `PlanningRuntimePort` наследует от обоих портов, адаптер реализует оба интерфейса одновременно.

---

## 📌 Важные детали

### Особенности реализации

- **Protocol классы**: Используют `typing.Protocol` для structural subtyping (duck typing)
- **Immutable DTO**: Все DTO — frozen dataclasses для thread-safety
- **Role-Based Segregation**: Каждый порт фокусируется на одной роли (admin, lookup, pending, etc.)
- **Композиция портов**: Сложные порты наследуют от простых (`PlanningRuntimePort = MatchRuntime + ResolveRuntime`)
- **No implementation**: Порты содержат только сигнатуры методов, не содержат логики

### 🚨 Failure Modes

| Ошибка | Условие возникновения | Поведение системы | Как обработать |
|--------|----------------------|-------------------|---------------|
| `AttributeError` | Адаптер не реализует метод порта | Runtime ошибка при вызове метода | Убедиться, что адаптер реализует все методы Protocol |
| `TypeError` | Передан объект, не соответствующий Protocol | Runtime ошибка при вызове | Проверить, что объект реализует Protocol (можно использовать `isinstance()` для проверки) |
| `NotImplementedError` | Адаптер реализует метод как `raise NotImplementedError` | Runtime ошибка при вызове | Полностью реализовать метод в адаптере или не использовать этот метод |

**Примеры**:

```python
# ❌ Адаптер не реализует все методы
class IncompleteCacheAdapter:
    def upsert(self, dataset: str, write_model: dict) -> UpsertResult:
        ...
    # Отсутствует count(), clear(), etc.

adapter = IncompleteCacheAdapter()
use_case = RefreshCacheUseCase(cache=adapter)  # ← OK (Protocol structural typing)
use_case.execute("employees")  # ← AttributeError: 'IncompleteCacheAdapter' has no attribute 'transaction'
```

**Как избежать**:
```python
# ✅ Полная реализация Protocol
class CompleteCacheAdapter(CacheRefreshPort):  # Явное наследование
    def transaction(self) -> ContextManager[None]: ...
    def upsert(self, dataset: str, write_model: dict) -> UpsertResult: ...
    def count(self, dataset: str) -> int: ...
    # ... все методы реализованы
```

### Частые ошибки

- ❌ **Не делай так**: Создавать зависимость UseCase от конкретного адаптера
  ```python
  class RefreshCacheUseCase:
      def __init__(self, cache: SqliteCacheRefreshAdapter):  # ❌ Конкретный класс
          self._cache = cache
  ```

- ✅ **Делай так**: Зависить только от порта
  ```python
  class RefreshCacheUseCase:
      def __init__(self, cache: CacheRefreshPort):  # ✅ Protocol
          self._cache = cache
  ```

- ❌ **Не делай так**: Добавлять логику в Protocol
  ```python
  class CacheAdminPort(Protocol):
      def upsert(self, dataset: str, write_model: dict) -> UpsertResult:
          # ❌ Логика в Protocol!
          return UpsertResult.INSERTED
  ```

- ✅ **Делай так**: Protocol только сигнатуры, логика в адаптере
  ```python
  class CacheAdminPort(Protocol):
      def upsert(self, dataset: str, write_model: dict) -> UpsertResult:
          ...  # ✅ Только сигнатура
  ```

### ⚠️ Инварианты системы

1. **Инвариант: DTO immutable**
   - **Что**: Все DTO модели — frozen dataclasses
   - **Почему важно**: Предотвращает side effects, обеспечивает thread-safety
   - **Где проверяется**: `@dataclass(frozen=True)` выбрасывает FrozenInstanceError при попытке изменения

2. **Инвариант: Адаптер реализует все методы Protocol**
   - **Что**: Адаптер должен реализовать все методы из Protocol
   - **Почему важно**: Предотвращает AttributeError в runtime
   - **Где проверяется**: Static type checking (mypy), runtime — при вызове метода

3. **Инвариант: Порты не содержат state**
   - **Что**: Protocol классы — stateless, без полей/атрибутов
   - **Почему важно**: Порты — это контракты, не реализации
   - **Где проверяется**: Code review, архитектурные тесты

### ⏱️ Performance заметки

**Узкие места**:
- Порты сами по себе не имеют performance overhead (это просто интерфейсы)
- Performance зависит от реализации адаптеров (Infrastructure)

**Рекомендации**:
- Использовать Protocol вместо ABC для structural subtyping (быстрее)
- DTO — frozen dataclasses (компилируются в эффективный код)
- Batch operations (upsert multiple) лучше вызывать через один метод, чем циклом

---

## 🔗 Связанные документы

- [Cache DSL](./cache-dsl.md) — Компилятор DSL, создаёт `CacheSpec`
- [Cache Core](./cache-core.md) — Доменная логика cache планирования
- [Cache Infrastructure](./cache-infra.md) — Реализация адаптеров для SQLite
- [CACHE-DEC-001](../../adr/cache/CACHE-DEC-001-topological-sort-for-dependencies.md) — ADR по топологической сортировке

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-02-11 | Создан документ Cache Ports | xORex-LC |
