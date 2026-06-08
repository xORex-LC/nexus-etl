# Topology Ports

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
  - [Порты](#порты)
- [🗂️ Модели данных](#️-модели-данных)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [📌 Важные детали](#-важные-детали)
- [🛠️ Как расширять](#️-как-расширять)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Набор узких Protocol-портов и immutable DTO, образующих boundary между доменным ядром topology и всем остальным (infra-ридеры, usecase-оркестрация, stage-consumers).

**Ключевая ответственность**: Определить *что* нужно topology-логике (прочитать target hierarchy, прочитать source adjacency, получить snapshot, опубликовать событие) без фиксации *как* это сделано. Реализации портов — в [topology-infra](./topology-infra.md) и usecases.

**Расположение в кодовой базе**: [connector/domain/ports/topology/](../../../../connector/domain/ports/topology/)

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
domain/ports/topology/
├── provider.py        # TopologyProviderPort + TopologyNotAvailableError (snapshot access)
├── readers.py         # TopologyTargetReadPort, SourceAdjacencyReadPort, TopologyTargetMembershipReadPort
├── services.py        # SourceTopologyLocatorBuilderPort, TopologyMatchServicePort, TopologyLinkResolutionServicePort
├── builders.py        # SourcePathTopologyBuilderPort, TargetHierarchyTopologyBuilderPort
├── observability.py   # TopologyEventSink (transport-neutral)
└── models.py          # все DTO boundary-слоя
```

### 🎭 Применённые паттерны

#### Паттерн 1: Role-segregated ports (ISP)

**Где применяется**: вместо одного «topology gateway» — несколько узких портов под конкретную роль: чтение target hierarchy, чтение source adjacency, чтение target membership (плоское множество ids). Каждый consumer зависит только от нужного.

**Зачем**: Stage C (target build) и Stage G (source validation) читают cache по-разному (полные adjacency rows vs плоский id-set) — отдельные порты не заставляют один адаптер тащить чужой контракт. Это прямое следствие CQRS-lite/ISP из [CLAUDE.md §3](../../../../CLAUDE.md).

#### Паттерн 2: DTO как anti-corruption boundary

**Где применяется**: `TargetHierarchyRow`, `SourceAdjacencyNode`, `SourceTopologyCanonicalPath` — нейтральные носители, в которые infra проецирует storage-строки до того, как они дойдут до ядра.

**Зачем**: ядро не знает про колонки SQLite/CSV; смена storage не трогает domain.

---

## 🔑 Ключевые абстракции

### Порты

| Порт | Назначение | Реализация |
|------|-----------|------------|
| `TopologyProviderPort` | Read-only доступ к готовым snapshot-ам (`require_source/target`, `get_source/target`) | `StaticTopologyProvider` (usecases) |
| `TopologyTargetReadPort` | Прочитать target adjacency rows + freshness metadata | `SqliteTopologyTargetReader` |
| `SourceAdjacencyReadPort` | Прочитать source adjacency projection (`read_nodes`) | `PolarsSourceAdjacencyReader` |
| `TopologyTargetMembershipReadPort` | Прочитать плоское множество target ids (`read_target_ids`) | `SqliteTopologyTargetMembershipReader` |
| `SourceTopologyLocatorBuilderPort` | Построить canonical локатор из `SourceRecord` | `SourceTopologyLocatorBuilder` |
| `TopologyMatchServicePort` | Topology-refinement на match (`compare`) | `TopologyMatchService` |
| `TopologyLinkResolutionServicePort` | Topology-backed FK на resolve (`resolve_link`) | `TopologyLinkResolutionService` |
| `TopologyEventSink` | Transport-neutral lifecycle-события (`emit`, `enabled`) | `StructlogTopologyEventSink` |
| `SourcePathTopologyBuilderPort` / `TargetHierarchyTopologyBuilderPort` | Контракты builder-ов ядра | builders в `dependency_tree/` |

> `TopologyQueryPort` (read-side snapshot) определён в самом ядре ([snapshot.py](../../../../connector/domain/dependency_tree/snapshot.py)), а не здесь — он часть read-model, а не boundary к внешним системам.

---

## 🗂️ Модели данных

### Входные DTO (infra → ядро)

#### `TargetHierarchyRow`
Target adjacency-строка для target builder. `node_id`/`parent_id` уже string-identifiers, `label` уже canonical. `payload_target_id` — write-facing id, **не** подменяет `node_id`.
```python
@dataclass(frozen=True)
class TargetHierarchyRow:
    node_id: str
    parent_id: str | None
    label: str
    payload_target_id: str | int | None = None
```

#### `SourceTopologyCanonicalPath`
Canonical путь source-иерархии (для row-level локатора и source builder).
```python
@dataclass(frozen=True)
class SourceTopologyCanonicalPath:
    canonical_segments: tuple[str, ...]
```

#### `SourceAdjacencyNode` (определён в ядре, [anchoring.py](../../../../connector/domain/dependency_tree/anchoring.py))
Source-узел в абстрактном business-id space для Stage G: `node_id`, `parent_id`, `label`.

### Результирующие DTO (ядро → consumers)

#### `TopologyMatchResult`
```python
@dataclass(frozen=True)
class TopologyMatchResult:
    matched_target_id: str | None
    is_ambiguous: bool
    mode: TopologyMatchMode
    reason: str | None
    evidence: Mapping[str, Any]
```

#### `TopologyLinkResolutionResult`
Как `TopologyMatchResult`, плюс `resolved_field`, `resolved_target_id: str|int|None`, `is_pending: bool`.

#### `SourceTopologyValidationState`
Run-scoped verdicts для pipeline-фильтра. Хранит только node-id keyed verdicts — **row-level диагностику создаёт стадия-фильтр**, где есть актуальный `row_ref`.
```python
@dataclass(frozen=True)
class SourceTopologyValidationState:
    node_id_field: str                              # имя поля в mapped row
    dropped: Mapping[str, SourceAnchoringVerdict]
    on_unanchored: Literal["skip", "warn", "hard_error"]
```

### Метаданные / политики

| DTO | Назначение |
|-----|-----------|
| `TargetHierarchyReadMeta` | `cache_snapshot_revision`, `refreshed_at`, `row_count` — provenance для readiness |
| `TopologyFreshnessPolicy` | `mode` (none/max_age/revision_required), `max_age_seconds`, `require_revision`; валидирует себя в `__post_init__` |
| `TopologyTargetReadinessResult` | `is_ready`, `errors`, `warnings`, `details` |
| `TopologyRuntimeRequirements` | run-scoped activation-семантика для pipeline composition (см. ниже) |

#### `TopologyRuntimeRequirements`
Не хранит snapshot и не подменяет provider — это *composition input* для consumer-ов: была ли topology затребована, для какого датасета, по какой причине активации.
```python
@dataclass(frozen=True)
class TopologyRuntimeRequirements:
    pipeline_dataset: str
    topology_dataset: str
    requires_source_topology: bool
    requires_target_topology: bool
    activation_sources: tuple[str, ...]   # ("match",) / ("resolve",) / ("source_validation",) / комбинации
    skipped_reason: str | None = None
```

---

## 🔄 Взаимодействие с другими слоями

| Слой | Направление | Через что |
|------|------------|-----------|
| Topology Infra | реализует | `*ReadPort`, `TopologyEventSink` |
| Topology Usecases | реализует/потребляет | `TopologyProviderPort`, service-порты, builders |
| Topology Consumers | потребляет | `TopologyMatchServicePort`, `TopologyLinkResolutionServicePort`, `SourceTopologyLocatorBuilderPort` |
| Cache Ports | переиспользует | `TopologyCacheReadPort` (роль cache) — детали в [topology-infra](./topology-infra.md) |
| Diagnostics | зависит | DTO `SourceTopologyValidationState`/readiness несут `DiagnosticItem` |

---

## 🔌 Контракты и границы

**Разрешено**:
- ✅ Порты импортируют только `domain/*` (модели ядра, diagnostics, `SourceRecord`).
- ✅ Реализации портов — в `infra/` и `usecases/`.

**Запрещено**:
- ❌ Порт-модуль импортирует `infra/*` или `delivery/*`.
- ❌ DTO несёт polars/SQLite-типы — только примитивы и доменные dataclass.

**Архитектурные тесты**: контракт `domain is the inner layer` (`lint-imports`).

---

## 📌 Важные детали

### Особенности реализации

- **`TopologyNotAvailableError`** поднимается `require_source/require_target`, когда соответствующий snapshot не построен. Consumers, которым topology опциональна, используют `get_source/get_target` (возвращают `None`).
- **Membership ≠ hierarchy.** `TopologyTargetMembershipReadPort` намеренно отделён от `TopologyTargetReadPort`: Stage G сверяет source в **business-id space** (плоское множество), тогда как target snapshot живёт в **node_id space**. Объединять порты нельзя — это разные id-пространства.
- **`node_id_field` в `SourceTopologyValidationState`** — это имя поля **в mapped row** (после Map), а не имя source-колонки; маппинг подставляет usecase-оркестратор (`_mapped_field_for_source`).

### ⚠️ Инварианты системы

1. **DTO immutable** (`frozen=True`); `Mapping`-поля оборачиваются в read-only прокси на уровне ядра.
2. **`TopologyEventSink` транспортно-нейтрален** — допускает любой backend (structlog сейчас, legacy stdlib раньше); ядро/usecases не знают про конкретный logger.
3. **`payload_target_id` не равен `node_id`** — топологический id и write-facing id живут раздельно, чтобы resolve мог материализовать FK правильным значением.

---

## 🛠️ Как расширять

### Добавить новый read-порт

1. Объявить `Protocol` в [readers.py](../../../../connector/domain/ports/topology/readers.py) с узким контрактом.
2. Экспортировать из `__init__.py` (обновить `__all__`).
3. Реализовать адаптер в `infra/topology/` ([topology-infra](./topology-infra.md)).
4. Завести фабрику в runtime-шаге ([topology-runtime](./topology-runtime.md)).

### Добавить поле в DTO

- Добавлять с дефолтом (DTO frozen, обратная совместимость), обновить README директории портов и потребителей.

---

## 🔗 Связанные документы

- [Topology Core](./topology-core.md) — `TopologyQueryPort`, модели узлов
- [Topology Infra](./topology-infra.md) — реализации read-портов и event sink
- [Topology Consumers](./topology-consumers.md) — реализации service-портов
- [Topology Runtime](./topology-runtime.md) — где порты связываются в bootstrap
- [Cache Ports](../cache/cache-ports.md) — `TopologyCacheReadPort` как роль cache
