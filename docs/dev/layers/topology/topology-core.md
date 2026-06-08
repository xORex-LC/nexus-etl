# Topology Core (dependency_tree)

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма зависимостей](#диаграмма-зависимостей)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [📌 Важные детали](#-важные-детали)
  - [🚨 Failure Modes](#-failure-modes)
  - [⚠️ Инварианты системы](#️-инварианты-системы)
  - [⏱️ Performance заметки](#️-performance-заметки)
- [🛠️ Как расширять](#️-как-расширять)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Чистое доменное ядро topology-подсистемы — построение и query иерархического графа подразделений (forest) без какой-либо зависимости от storage, DSL или CLI.

**Ключевая ответственность**: Принять уже нормализованные данные (canonical source paths или target adjacency rows), построить immutable `TopologySnapshot`, отдать детерминированные graph-запросы и сравнить source-локатор с target-кандидатами по explainable comparison ladder. Сюда же входит Stage G source anchoring (reachability/отсечение поддеревьев).

**Расположение в кодовой базе**: [connector/domain/dependency_tree/](../../../../connector/domain/dependency_tree/)

> Это самый внутренний слой подсистемы. Он не знает ни про cache/polars (см. [topology-infra](./topology-infra.md)), ни про YAML (см. [topology-dsl](./topology-dsl.md)), ни про bootstrap-lifecycle (см. [topology-runtime](./topology-runtime.md)). Потребители ядра описаны в [topology-consumers](./topology-consumers.md).

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
domain/dependency_tree/
├── models.py            # TopologyNode — минимальный immutable узел (node_id/parent_id/labels)
├── snapshot.py          # TopologySnapshot + TopologyQueryPort (read-only query-слой)
├── target_builder.py    # TargetHierarchyTopologyBuilder — adjacency → snapshot, валидация (duplicate/parent/cycle)
├── source_builder.py    # SourcePathTopologyBuilder — canonical paths → forest, synthetic ids
├── comparison.py        # compare_topology_candidates + TopologyMatchMode (explainable ladder)
├── anchoring.py         # anchor_source_nodes — Stage G reachability/отсечение поддеревьев
├── readiness.py         # TopologyTargetReadinessEvaluator — empty/stale gate перед runtime
├── fingerprints.py      # build_source_synthetic_id, build_structural_signature (stable sha256)
└── ports.py             # TopologyTracePort + NullTopologyTrace (DEBUG-трейс ingestion)
```

### 🎭 Применённые паттерны

#### Паттерн 1: Immutable Snapshot + Query Port (CQS read-side)

**Где применяется**: `TopologySnapshot` владеет graph-индексами и отдаёт только запросы; builders владеют ingestion/валидацией. Разделение строгое: snapshot никогда не строит сам себя из raw-данных, builder никогда не отвечает на graph-запросы.

**Реализация в коде**:
- **Query contract**: `TopologyQueryPort` (Protocol) в [snapshot.py](../../../../connector/domain/dependency_tree/snapshot.py)
- **Read-model**: `TopologySnapshot` (frozen dataclass, `MappingProxyType`-индексы) там же
- **Ingestion**: `TargetHierarchyTopologyBuilder`, `SourcePathTopologyBuilder`

**Зачем**: Snapshot безопасно шарить между стадиями (match/resolve) в рамках одного run — он read-only и не мутируется query-методами.

#### Паттерн 2: Explainable comparison ladder (вместо непрозрачного fingerprint)

**Где применяется**: `compare_topology_candidates` сравнивает source-сегменты с каждым target-кандидатом по упорядоченному списку «рунгов» (strongest → weakest) и возвращает не только результат, но и `evidence` с разбором каждого рунга.

**Реализация в коде**:
- `TopologyMatchMode` (Enum) и `compare_topology_candidates` в [comparison.py](../../../../connector/domain/dependency_tree/comparison.py)

**Зачем**: Match/resolve должны уметь объяснить, почему кандидат выбран/отвергнут (reporting, отладка), а не просто сравнить хэши. Ladder также даёт градацию строгости: точное совпадение пути → leaf+parent → leaf+root+depth.

#### Паттерн 3: Null Object для трейса

**Где применяется**: `NullTopologyTrace` подставляется builder-ами, когда DEBUG выключен, чтобы убрать ветвление `if trace is not None` из горячего ingestion-цикла.

**Реализация в коде**: `TopologyTracePort` / `NullTopologyTrace` в [ports.py](../../../../connector/domain/dependency_tree/ports.py)

### Диаграмма зависимостей

```
[DSL canonicalizer] ─► [canonical paths / adjacency rows]
                             │
                  ┌──────────┴───────────┐
        SourcePathTopologyBuilder   TargetHierarchyTopologyBuilder
                  │                       │
                  └────────► TopologySnapshot ◄──── TopologyTargetReadinessEvaluator
                                  │
                  ┌───────────────┴────────────────┐
        compare_topology_candidates          anchor_source_nodes
        (match/resolve consumers)            (Stage G validation)
```

---

## 🔑 Ключевые абстракции

### Интерфейсы/Порты

| Интерфейс | Назначение | Где используется |
|-----------|-----------|------------------|
| `TopologyQueryPort` | Read-only graph-запросы над snapshot (`canonical_path`, `ancestors`, `descendants`, `depth`, …) | comparison core, consumers ([topology-consumers](./topology-consumers.md)) |
| `TopologyTracePort` | DEBUG-трейс ingestion (`node_ingested`, `path_ingested`, `cycle_checked`) | builders; адаптер `TraceToSink` в usecases |

### Основные классы

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
| `TopologySnapshot` | Immutable graph-индексы + детерминированные запросы | `canonical_path()`, `ancestors()`, `descendants()`, `path_to_root()`, `structural_signature()`, `empty()` |
| `TargetHierarchyTopologyBuilder` | Target adjacency → snapshot с полной валидацией | `build(rows)` |
| `SourcePathTopologyBuilder` | Canonical source paths → forest с synthetic ids | `build(paths)` |
| `TopologyTargetReadinessEvaluator` | Решает, пригоден ли target snapshot (empty/stale) | `evaluate(snapshot, metadata, policy, require_target_topology)` |
| `compare_topology_candidates` (func) | Explainable сравнение source ↔ target кандидаты | — |
| `anchor_source_nodes` (func) | Stage G: reachability source-узлов против target membership | — |

---

## 🗂️ Модели данных

### Dataclass: `TopologyNode`

**Назначение**: Минимальный immutable узел графа. Хранит только локальные relation и labels; всё производное (depth, root, descendants, canonical path) вычисляет snapshot.

**Структура**:
```python
@dataclass(frozen=True)
class TopologyNode:
    node_id: str
    parent_id: str | None
    display_name: str
    canonical_name: str
```

**Инварианты**:
- `node_id` стабилен и уникален в пределах snapshot (target — из данных; source — synthetic sha256 от path-prefix).
- `canonical_name` уже нормализован upstream (DSL canonicalizer); builder не запускает ops повторно.

### Dataclass: `TopologySnapshot`

**Назначение**: Read-only представление графа: `nodes_by_id`, `parent_by_id`, `children_by_id`, `roots`.

**Lifecycle**:
1. **Создание**: builder-ом (`build()`), либо `TopologySnapshot.empty()` при фатальной валидации.
2. **Трансформации**: нет — `frozen=True`, индексы обёрнуты в `MappingProxyType`, child-коллекции — tuples.
3. **Завершение**: оборачивается в `StaticTopologyProvider` ([topology-runtime](./topology-runtime.md)) и шарится между стадиями run-а.

**Инварианты**:
- Query-методы никогда не мутируют состояние.
- `descendants()`/`path_to_root()` детерминированы (дети отсортированы).

### Dataclass: `TopologyComparisonResult`

**Назначение**: Explainable итог `compare_topology_candidates`.

```python
@dataclass(frozen=True)
class TopologyComparisonResult:
    matched_candidate_ids: tuple[str, ...]
    mode: TopologyMatchMode
    reason: str | None
    evidence: Mapping[str, Any]   # source_segments, candidate_ids, разбор по рунгам
```
- `matched_candidate_id` (property) → единственный id или `None` (если 0 или >1).
- `is_ambiguous` (property) → `mode == AMBIGUOUS`.

### Dataclass: `SourceAnchoringResult` (Stage G)

**Назначение**: Итог anchoring без row-level привязки — node-id keyed.

```python
@dataclass(frozen=True)
class SourceAnchoringResult:
    anchored_ids: frozenset[str]
    dropped: Mapping[str, SourceAnchoringVerdict]   # node_id → reason (missing_parent|unanchored_subtree|cycle)
```

---

## 📊 Ключевые методы и алгоритмы

### Обзор сложных методов

| Метод | Сложность | Назначение |
|-------|-----------|------------|
| `TargetHierarchyTopologyBuilder.build()` | O(n) | Валидировать adjacency и собрать target snapshot |
| `compare_topology_candidates()` | O(k·d) | Сопоставить source-путь с k кандидатами по ladder |
| `anchor_source_nodes()` | O(n) амортизированно | Reachability + отсечение поддеревьев (memoized DFS) |

---

### Метод: `TargetHierarchyTopologyBuilder.build()`

**Расположение**: [target_builder.py:46](../../../../connector/domain/dependency_tree/target_builder.py#L46)

**Алгоритм** (fail-fast на любой структурной ошибке):
```
1. Ingest rows (lines 59-82)
   - FOR EACH row:
       → IF node_id уже встречался → TOPOLOGY_DUPLICATE_NODE, skip
       → создать TopologyNode (label уже canonical), записать parent_by_id
2. Проверка parent references (lines 84-97)
   - FOR EACH (node, parent):
       → IF parent_id ∉ nodes → TOPOLOGY_PARENT_MISSING
       → ELSE: добавить node в children[parent]
   - IF errors → вернуть (empty snapshot, errors, ())   # fail-fast
3. Проверка циклов (lines 102-111)
   - graphlib.TopologicalSorter.static_order()
   - IF CycleError → TOPOLOGY_CYCLE_DETECTED, вернуть empty snapshot
4. Сборка (lines 113-131)
   - frozen children (sorted tuples), roots = узлы без parent
```

**Инварианты**:
1. Target ingest **строго валидируется** — relations приходят из внешних данных (cache).
2. Любая структурная ошибка → пустой snapshot (не частичный). Readiness затем пометит его `TOPOLOGY_TARGET_EMPTY`.

---

### Метод: `compare_topology_candidates()`

**Расположение**: [comparison.py:57](../../../../connector/domain/dependency_tree/comparison.py#L57)

**Алгоритм**:
```
Вход: source_segments (canonical path), candidate_ids, ladder (упорядоченные рунги)
  ↓
[dedup candidates] → {пусто?} ─Yes→ NO_MATCH (empty_source_or_candidates)
  ↓ No
FOR EACH mode IN ladder (strongest → weakest):
   matched = кандидаты, чей canonical_path удовлетворяет mode
   ├─ len(matched) == 1 → return mode (resolved_by_<mode>)   # ранний выход
   ├─ len(matched) > 1  → return AMBIGUOUS (ambiguous_on_<mode>)
   └─ len(matched) == 0 → следующий рунг
  ↓
NO_MATCH (no_topology_confirmation)
```

**Рунги (`TopologyMatchMode`)**:
| Mode | Условие совпадения |
|------|--------------------|
| `EXACT_CANONICAL_PATH` | `candidate_path == source_segments` |
| `EXACT_LEAF_PARENT_CHAIN` | последние 2 сегмента совпадают (`[-2:]`), оба пути длиной ≥ 2 |
| `EXACT_LEAF_ROOT_DEPTH` | совпали leaf, root и длина пути |

**Инварианты**:
1. Любой рунг с >1 совпадением немедленно даёт `AMBIGUOUS` (consumer решит policy).
2. `evidence` всегда содержит разбор по каждому пройденному рунгу — для reporting.
3. Сравнение идёт только через `TopologyQueryPort` — никакого прямого доступа к storage.

---

### Метод: `anchor_source_nodes()` (Stage G)

**Расположение**: [anchoring.py:58](../../../../connector/domain/dependency_tree/anchoring.py#L58)

**Назначение**: dataset-agnostic проверка: каждый source-узел должен подниматься по `parent_id` до **якоря** — root (`parent_id is None`), target id (`parent ∈ target_ids`) или уже заякоренного source-родителя. Если цепочка обрывается на отсутствующем родителе — узел и всё его поддерево отсекаются.

**Алгоритм**:
```
1. dedup-first (первое вхождение node_id выигрывает)
2. memoized DFS visit(node):
   - node в текущем stack → cycle
   - parent is None | parent ∈ target_ids → anchored (None verdict)
   - parent ∉ source nodes → missing_parent
   - иначе → наследовать verdict родителя (unanchored_subtree | cycle)
3. propagate: для каждого dropped-узла пометить весь его subtree
   (reason наследуется: cycle остаётся cycle, иначе unanchored_subtree)
4. anchored_ids = все узлы, не попавшие в dropped
```

**Edge cases**:
- **Forward-reference** (родитель в том же батче, но позже) — валиден: anchoring смотрит на весь батч, порядок не важен. Это «штатный» источник pending в resolve.
- **Permanently-unanchorable** (родителя нет ни в source, ни в target) — `missing_parent`, отсекается.
- **Cycle** — отдельный reason, отсекается вместе с поддеревом.

**Важно**: anchoring работает в абстрактном **business-id space** (`SourceAdjacencyNode`), а не в `node_id`-space target snapshot. Это намеренно: source membership сравнивается с плоским target membership set (см. [topology-infra](./topology-infra.md)).

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| Topology DSL | Потребляет вход | `CompiledCanonicalizer` (canonical labels/segments) | Builders доверяют, что labels уже нормализованы |
| Topology Ports | Shared DTO | `TargetHierarchyRow`, `SourceTopologyCanonicalPath`, `SourceAdjacencyNode`, `TopologyFreshnessPolicy` | Boundary-модели для builder/readiness |
| Diagnostics | Зависимость | `ErrorCatalog`, `build_error/build_warning`, `DiagnosticStage` | Структурные ошибки графа |
| Topology Consumers | Поставляет | `TopologyQueryPort` + `compare_topology_candidates` | Match/resolve refinement |
| Topology Usecases | Поставляет | builders, readiness, `anchor_source_nodes` | Bootstrap orchestration |

---

## 🔌 Контракты и границы

### Границы слоёв

**Разрешено**:
- ✅ `dependency_tree/*` → `domain/diagnostics`, `domain/models`, `domain/ports/topology/models`
- ✅ consumers/usecases → `TopologyQueryPort`, `compare_topology_candidates`, builders

**Запрещено**:
- ❌ `dependency_tree/*` → `connector/infra/*` (нет cache/polars — данные приходят уже спроецированными)
- ❌ `dependency_tree/*` → `connector/usecases/*` или `delivery/*`
- ❌ Запуск DSL-ops внутри builder (label canonicalization — забота upstream seam)

**Архитектурные тесты**: контракт `domain is the inner layer` в [pyproject.toml](../../../../pyproject.toml) (`lint-imports`).

---

## 📌 Важные детали

### 🚨 Failure Modes

| Код диагностики | Условие | Сторона | Поведение |
|-----------------|---------|---------|-----------|
| `TOPOLOGY_DUPLICATE_NODE` | повтор `node_id` в adjacency | target build / source validation | строка пропускается, error |
| `TOPOLOGY_PARENT_MISSING` | `parent_id` отсутствует среди узлов | target build | fail-fast → empty snapshot |
| `TOPOLOGY_CYCLE_DETECTED` | цикл в target adjacency | target build | fail-fast → empty snapshot |
| `TOPOLOGY_SOURCE_PATH_EMPTY` | все сегменты пути пустые | source build | error, путь пропускается |
| `TOPOLOGY_SOURCE_PATH_MALFORMED` | дыра в середине пути (пустой сегмент) | source build | warning, путь пропускается |
| `TOPOLOGY_SOURCE_COLLISION` | два path схлопнулись в один canonical | source build | warning, первый выигрывает |
| `TOPOLOGY_TARGET_EMPTY` | snapshot без узлов | readiness | required → error, optional → warning |
| `TOPOLOGY_TARGET_STALE` | freshness policy нарушена | readiness | required → error, optional → warning |
| `TOPOLOGY_SOURCE_UNANCHORED` | узел не заякорен | source validation / filter | по `on_unanchored` (skip/warn/hard_error) |

> Source build терпим к частичным ошибкам (валидные пути всё равно формируют snapshot); target build — fail-fast (внешние данные, частичный граф недопустим).

### ⚠️ Инварианты системы

1. **Snapshot immutable** — `frozen=True` + `MappingProxyType`; ни один query-метод не мутирует индексы.
2. **Source forest acyclic by construction** — parent выводится из path-prefix, поэтому source builder не проверяет циклы (в отличие от target).
3. **Synthetic id детерминирован** — `build_source_synthetic_id(prefix, normalization_version)` стабилен между запусками при той же canonicalization; `normalization_version` входит в хэш, поэтому смена canonicalization меняет ids.
4. **Anchoring reason наследуется по поддереву** — `cycle` остаётся `cycle`, всё остальное становится `unanchored_subtree`.

### ⏱️ Performance заметки

- Все builders/anchoring — линейные по числу узлов; `compare_topology_candidates` — O(k·d) на строку (k кандидатов × глубина пути), что мало (обычно k≤несколько, d≤5–6 уровней).
- Cycle detection — единый `graphlib.TopologicalSorter` проход (`_has_cycle`), не на узел.
- Snapshot строится один раз за run (в bootstrap) и переиспользуется всеми стадиями.

---

## 🛠️ Как расширять

### Добавить новый comparison-рунг (ladder step)

1. Добавить значение в `TopologyMatchMode` ([comparison.py](../../../../connector/domain/dependency_tree/comparison.py)).
2. Реализовать условие в `_candidate_matches_mode()`.
3. Добавить литерал в `TopologyComparisonLadderStep` ([DSL spec](../../../../connector/domain/transform_dsl/specs/topology.py)) — иначе рунг нельзя будет включить из YAML.
4. Покрыть тестом в изоляции (`compare_topology_candidates` с синтетическим snapshot).

### Добавить новый source builder / новый источник графа

1. Спроецировать данные в существующий DTO (`SourceTopologyCanonicalPath` или `SourceAdjacencyNode`) на стороне infra.
2. Переиспользовать `SourcePathTopologyBuilder` / `anchor_source_nodes` — **не** добавлять storage-логику в ядро.

### Добавить структурную диагностику

1. Расширить `build_core_catalog()` новым `TOPOLOGY_*` кодом (см. [diagnostics](../../../../connector/domain/diagnostics/core_catalog.py)).
2. Эмитить через `build_error/build_warning(catalog, stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP|TOPOLOGY_VALIDATE, ...)`.

---

## 🔗 Связанные документы

- [Topology DSL](./topology-dsl.md) — откуда берутся canonical labels/segments
- [Topology Ports](./topology-ports.md) — DTO и контракты boundary
- [Topology Infra](./topology-infra.md) — кто проецирует данные в DTO ядра
- [Topology Runtime](./topology-runtime.md) — где ядро собирается в bootstrap
- [Topology Consumers](./topology-consumers.md) — кто использует query/comparison
- [ADR TRANSFORM-DEC-010](../../../adr/transform/TRANSFORM-DEC-010-topology-bootstrap-before-main-pipeline.md) — почему bootstrap до основного pipeline
