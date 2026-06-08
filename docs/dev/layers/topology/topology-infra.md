# Topology Infrastructure

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [📌 Важные детали](#-важные-детали)
  - [🚨 Failure Modes](#-failure-modes)
  - [⚠️ Инварианты системы](#️-инварианты-системы)
- [🛠️ Как расширять](#️-как-расширять)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Инфраструктурные адаптеры topology — реализации read-портов поверх cache (SQLite) и source-файла (polars), плюс адаптер событий поверх structlog.

**Ключевая ответственность**: Прочитать физические данные (cache adjacency, source CSV, target membership) и спроецировать их в нейтральные DTO ядра. Адаптеры знают про колонки/CSV-параметры, но **не** строят граф, не валидируют anchoring и не принимают readiness-решения.

**Расположение в кодовой базе**:
- [connector/infra/topology/](../../../../connector/infra/topology/)
- [connector/infra/logging/topology.py](../../../../connector/infra/logging/topology.py)

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
infra/topology/
├── sqlite_target_reader.py       # SqliteTopologyTargetReader  → TopologyTargetReadPort
├── sqlite_membership_reader.py   # SqliteTopologyTargetMembershipReader → TopologyTargetMembershipReadPort
└── polars_source_reader.py       # PolarsSourceAdjacencyReader  → SourceAdjacencyReadPort

infra/logging/
└── topology.py                   # StructlogTopologyEventSink   → TopologyEventSink
```

### 🎭 Применённые паттерны

#### Паттерн 1: Adapter (port реализация)

**Где применяется**: каждый класс реализует ровно один topology-порт ([topology-ports](./topology-ports.md)) и проецирует storage-строку в DTO ядра.

**Реализация**:
- **Порт**: `TopologyTargetReadPort` (Protocol)
- **Адаптер**: `SqliteTopologyTargetReader` поверх `TopologyCacheReadPort`

**Зачем**: domain/usecases зависят от Protocol; смена SQLite→другой backend меняет только адаптер.

#### Паттерн 2: Cache role-port reuse (а не прямой SQLite)

**Где применяется**: оба cache-ридера работают через **`TopologyCacheReadPort`** — узкую роль cache-гейтвея, а не через `SqliteEngine` напрямую.

**Реализация**: `container.cache.roles().topology_read` инжектится в ридеры (см. [topology-runtime](./topology-runtime.md)).

**Зачем**: topology переиспользует уже верифицированный read-path cache (content-hash, drift), не дублируя SQL. Соответствует правилу «весь SQLite — через cache/SqliteEngine» из [CLAUDE.md §7](../../../../CLAUDE.md).

#### Паттерн 3: Dual id-space readers

**Где применяется**: target читается **двумя** разными адаптерами — `SqliteTopologyTargetReader` (полные adjacency rows, node_id-space) и `SqliteTopologyTargetMembershipReader` (плоское множество business-ids).

**Зачем**: Stage C строит граф из node_id/parent_id; Stage G сверяет source против business-id membership. Это разные id-пространства → разные ридеры.

---

## 🔑 Ключевые абстракции

### Основные классы

| Класс | Порт | Источник | Ключевые методы |
|-------|------|----------|-----------------|
| `SqliteTopologyTargetReader` | `TopologyTargetReadPort` | cache dataset table | `read_hierarchy()`, `read_snapshot_metadata()` |
| `SqliteTopologyTargetMembershipReader` | `TopologyTargetMembershipReadPort` | cache dataset table | `read_target_ids()` |
| `PolarsSourceAdjacencyReader` | `SourceAdjacencyReadPort` | source CSV | `read_nodes()` |
| `StructlogTopologyEventSink` | `TopologyEventSink` | — (logger) | `emit()`, `enabled()` |

---

## 📊 Ключевые методы и алгоритмы

### `SqliteTopologyTargetReader.read_hierarchy()`

**Расположение**: [sqlite_target_reader.py:55](../../../../connector/infra/topology/sqlite_target_reader.py#L55)

```
1. _require_dataset(dataset)        # адаптер привязан к одному cache_spec.dataset
2. rows = cache_read.read_all(dataset, include_deleted=True)
3. отсортировать по node_id (детерминизм)
4. FOR EACH row → TargetHierarchyRow:
     node_id        = str(row[node_id_field])
     parent_id      = optional_str(row[parent_id_field])
     label          = canonicalizer.canonicalize_scalar(str(row[target_label_field]))  # python-форма!
     payload_target_id = row[payload_target_id_field] | None
```

**Важно**: `include_deleted=True` — в граф попадают и tombstone-узлы, иначе у живого потомка «исчез» бы родитель. Label канонизируется **той же** `compiled.python` формой, что и source-локатор → пути сопоставимы.

### `read_snapshot_metadata()`

Достаёт `cache_snapshot_revision` (или fallback `last_refresh_run_id`), `refreshed_at` (или `last_refresh_at`, ISO-parse) и `row_count` — это вход для `TopologyTargetReadinessEvaluator` (freshness/empty gate).

### `PolarsSourceAdjacencyReader.read_nodes()`

**Расположение**: [polars_source_reader.py:51](../../../../connector/infra/topology/polars_source_reader.py#L51)

```
1. pl.read_csv(infer_schema_length=0, null_values=["","null","NULL"])  # всё как Utf8
2. проверить наличие требуемых колонок → ValueError при отсутствии
3. select(node_id, parent_id, label) с .str.strip_chars()
4. filter(node_id is not null & != "")  → .unique(maintain_order=True)
5. yield SourceAdjacencyNode(...)  # пустой parent_id → None
```

**Векторная проекция** (polars), в отличие от построчной target-канонизации — но дедуп/strip на этом этапе, а нормализация labels Stage G не требует (anchoring смотрит на ids, не на labels).

### `StructlogTopologyEventSink.emit()`

**Расположение**: [infra/logging/topology.py](../../../../connector/infra/logging/topology.py)

- `enabled(level)` — пробует `is_enabled_for` / `isEnabledFor` / обёрнутый stdlib-logger; при невозможности проверить → `True`.
- `emit()` пропускает событие, если `enabled` ложно, иначе диспатчит по уровню (`critical/error/warning/info/debug`) с фиксированным `scope="topology"` и распакованным payload.

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| Cache | Зависимость | `TopologyCacheReadPort`, `CacheSpec` | Чтение target adjacency/membership без прямого SQL |
| Sources | Зависимость | source CSV + `csv_options()` | Source adjacency projection (Stage G) |
| Topology Ports | Реализует | `*ReadPort`, `TopologyEventSink` | Boundary к ядру/usecases |
| Topology Common | Использует | `CompiledCanonicalizer` (`compiled.python`) | Канонизация target labels |
| Logging | Зависимость | structlog command logger | Публикация lifecycle-событий |

---

## 🔌 Контракты и границы

**Разрешено**:
- ✅ `infra/topology/*` → `domain/ports/topology`, `domain/ports/cache`, `domain/dependency_tree` (DTO), `polars`
- ✅ `infra/logging/topology.py` → `domain/ports/topology.TopologyEventSink`

**Запрещено**:
- ❌ `infra/topology/*` → `usecases/*` или `delivery/*` (контракт `infra must not depend on usecases or delivery`)
- ❌ Прямой `sqlite3` — только через cache role-port
- ❌ Graph-валидация/anchoring внутри адаптера — это ядро/usecases

**Архитектурные тесты**: контракты `infra must not depend on usecases or delivery` в [pyproject.toml](../../../../pyproject.toml). `polars` разрешён в infra (запрещён только в `domain`/`usecases` контрактом `core layers stay free of IO/CLI/DI libraries`).

---

## 📌 Важные детали

### 🚨 Failure Modes

| Условие | Поведение | Где |
|---------|-----------|-----|
| `dataset != cache_spec.dataset` | `ValueError` (адаптер привязан к одному датасету) | оба cache-ридера |
| Отсутствуют source-колонки | `ValueError` со списком недостающих | `PolarsSourceAdjacencyReader` |
| Нераспознаваемый `refreshed_at` | `None` (freshness просто «не present») | `read_snapshot_metadata` |
| Пустой/`None` membership value | значение отбрасывается | `read_target_ids` |

> Эти `ValueError` из конфигурационной несогласованности (а не из данных) транслируются в catalog-диагностику (`TOPOLOGY_TARGET_CACHE_SPEC_MISSING` / `TOPOLOGY_DSL_SPEC_INVALID`) на уровне runtime-шага — см. [topology-runtime](./topology-runtime.md).

### ⚠️ Инварианты системы

1. **Один адаптер — один датасет.** `_require_dataset` защищает от случайного чтения чужой таблицы.
2. **Target labels канонизируются `compiled.python`** — той же формой, что source-локатор; иначе пути не совпадут.
3. **`include_deleted=True`** при чтении target hierarchy — целостность parent-цепочек важнее «свежести».
4. **Адаптеры не нормализуют source labels** — Stage G работает по ids; нормализация здесь была бы мёртвой работой.

### ⏱️ Performance заметки

- `read_hierarchy` материализует tuple (нужна сортировка + повторный проход в builder) — приемлемо: target hierarchy мала (подразделения).
- `read_nodes` — единый polars-проход с `unique(maintain_order=True)`; дедуп выполняется в движке, не в python.

---

## 🛠️ Как расширять

### Добавить новый source backend (например, не-CSV)

1. Реализовать `SourceAdjacencyReadPort.read_nodes()` в новом адаптере `infra/topology/`.
2. Спроецировать в `SourceAdjacencyNode` (не добавлять anchoring-логику — это ядро).
3. Подключить в `_build_source_validation_usecase` ([topology-runtime](./topology-runtime.md)).

### Поменять backend событий

Реализовать `TopologyEventSink` (`emit`/`enabled`) — ядро/usecases не изменятся (порт транспортно-нейтрален).

---

## 🔗 Связанные документы

- [Topology Ports](./topology-ports.md) — контракты, которые реализуют эти адаптеры
- [Topology Core](./topology-core.md) — что делает с DTO builder/anchoring
- [Topology Runtime](./topology-runtime.md) — где адаптеры собираются через DI
- [Cache Infrastructure](../cache/cache-infra.md) — cache read-path, который переиспользуется
- [Cache Ports](../cache/cache-ports.md) — `TopologyCacheReadPort`
