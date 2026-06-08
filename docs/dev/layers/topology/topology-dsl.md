# Topology DSL

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🎯 DSL](#-dsl)
  - [Структура DSL](#структура-dsl)
  - [Source ingress: два режима](#source-ingress-два-режима)
  - [Consumer policies](#consumer-policies)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [📌 Важные детали](#-важные-детали)
  - [🚨 Failure Modes](#-failure-modes)
  - [⚠️ Инварианты системы](#️-инварианты-системы)
- [🛠️ Как расширять](#️-как-расширять)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Декларативное описание topology-capability датасета — как из source/target данных получить иерархию, как нормализовать labels и как стадии match/resolve должны использовать topology-сигнал.

**Ключевая ответственность**: Дать Pydantic-схему (`TopologySpec`) и компилятор (`TopologyDsl`), который превращает YAML в исполнимый **canonicalizer plan** (общий для python и polars). Сами consumer-политики (`match.topology`, `resolve.topology_link`) живут в match/resolve DSL, но описаны здесь как часть topology-контракта.

**Расположение в кодовой базе**:
- Specs: [connector/domain/transform_dsl/specs/topology.py](../../../../connector/domain/transform_dsl/specs/topology.py)
- Compiler: [connector/domain/transform_dsl/compilers/topology.py](../../../../connector/domain/transform_dsl/compilers/topology.py)
- YAML: `datasets/<dataset>/*.topology.yaml` (каталог `datasets/` не индексируется в git — это environment-конфиг)

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
transform_dsl/
├── specs/topology.py            # TopologySpec, TopologyBlock, source/target spec-ы, policy-спеки
├── specs/canonicalization.py    # Shared CanonicalizationSpec (trim/lower/compact/regex_replace/canonicalize)
└── compilers/topology.py        # TopologyDsl → CompiledCanonicalizerPlan (python + polars + version)
```

### 🎭 Применённые паттерны

#### Паттерн 1: Spec → Compiler → Compiled plan (как у всех стадий)

**Где применяется**: `TopologySpec` (Pydantic, валидация) → `TopologyDsl.compile()` → `CompiledTopologyCanonicalizerPlan`. Spec ничего не исполняет; compiler не валидирует бизнес-смысл — только собирает план.

**Реализация**: `TopologyDsl` в [compilers/topology.py](../../../../connector/domain/transform_dsl/compilers/topology.py) делегирует `CanonicalizationDsl`.

**Зачем**: единый паттерн со всеми DSL-слоями (см. [CLAUDE.md §3](../../../../CLAUDE.md)), легко тестировать compiler изолированно.

#### Паттерн 2: Discriminated union для source-режимов

**Где применяется**: `TopologySourceSpec = Annotated[PathColumns | AdjacencyList, Field(discriminator="mode")]` — Pydantic выбирает класс по полю `mode`.

**Зачем**: один датасет описывает source-иерархию либо как набор колонок-уровней (employees), либо как id/parent_id adjacency (organizations) — без ad-hoc парсинга.

#### Паттерн 3: Dual-form canonicalizer (один rule-set → два исполнителя)

**Где применяется**: `CompiledCanonicalizerPlan` несёт `python: CompiledCanonicalizer` и `polars_expression_plan: CompiledPolarsExpressionPlan` из **одного** `CanonicalizationSpec`.

**Зачем**: target labels канонизируются построчно (python, в reader-е), а source-проекция — векторно (polars). Правила нормализации обязаны совпадать побайтово, иначе source и target не сматчатся — поэтому источник один.

---

## 🔑 Ключевые абстракции

### Основные классы

| Класс | Роль | Ключевые поля/методы |
|-------|------|----------------------|
| `TopologySpec` | Корень topology-спеки датасета | `dataset`, `topology: TopologyBlock` |
| `TopologyBlock` | Полная capability-конфигурация | `canonicalization`, `source`, `target` |
| `TopologySourcePathColumnsSpec` | Source как ordered колонки-уровни | `mode="path_columns"`, `path_columns[]` |
| `TopologySourceAdjacencyListSpec` | Source как id/parent_id list | `node_id_field`, `parent_id_field`, `label_field`, `target_membership_field`, `on_unanchored` |
| `TopologyTargetAdjacencySpec` | Target как adjacency list | `node_id_field`, `parent_id_field`, `target_label_field`, `payload_target_id_field?` |
| `MatchTopologyPolicySpec` | Политика topology в match | `enabled`, `apply_on`, `on_missing_topology`, `comparison_ladder[]` |
| `ResolveTopologyLinkSpec` | Политика topology-backed FK в resolve | `enabled`, `field`, `on_missing_topology`, `on_ambiguous_topology`, `comparison_ladder[]` |
| `TopologyFreshnessPolicySpec` | Freshness target snapshot | `mode`, `max_age_seconds`, `require_revision` |
| `TopologyDsl` | Компилятор spec → canonicalizer plan | `compile(spec)` |

> Дополнительно есть `topology` capability-флаг в **dataset DSL** (`dataset_dsl`), который включает/выключает всю подсистему для датасета. Его читает activation resolver — см. [topology-runtime](./topology-runtime.md).

---

## 🎯 DSL

### Структура DSL

```yaml
# datasets/<dataset>/<dataset>.topology.yaml
dataset: organizations
topology:
  canonicalization:
    ops:
      - { op: trim }
      - { op: lower }
      - { op: compact }            # схлопнуть повторные пробелы
      - { op: regex_replace, pattern: "[«»\"]", replacement: "" }
  source:
    mode: adjacency_list
    node_id_field: dept_id
    parent_id_field: parent_dept_id
    label_field: dept_name
    target_membership_field: external_id
    on_unanchored: skip            # skip | warn | hard_error
  target:
    mode: adjacency_list
    node_id_field: id
    parent_id_field: parent_id
    target_label_field: name
    payload_target_id_field: id    # опционально, write-facing id
```

### Доступные canonicalization-ops

| Op | Описание | Параметры |
|----|----------|-----------|
| `trim` | Срезать пробелы по краям | — |
| `lower` | Привести к нижнему регистру | — |
| `compact` | Схлопнуть повторяющиеся пробелы | — |
| `regex_replace` | Замена по regex | `pattern`, `replacement` |
| `canonicalize` | Композитная нормализация | (см. `CanonicalizeOpSpec`) |

> Это **whitelisted** подмножество core-ops — namespace `canonicalization`, общий с другими подсистемами. Полный реестр операций — в [dsl-engine](../dsl/dsl-engine.md).

### Source ingress: два режима

| Режим | Когда | Как строится иерархия | Builder |
|-------|-------|------------------------|---------|
| `path_columns` | Иерархия закодирована колонками-уровнями (employees: «Орг. единица уровня 1..5») | из path-prefix, synthetic ids | `SourcePathTopologyBuilder` |
| `adjacency_list` | Source сам self-referential (organizations: id/parent_id) | из explicit id/parent_id | через anchoring (Stage G) |

**`path_columns`** питает row-level locator в match/resolve ([topology-consumers](./topology-consumers.md)) — source snapshot целиком не строится, локатор собирается построчно из перечисленных колонок.

**`adjacency_list`** активирует Stage G source validation: проекция → `anchor_source_nodes` → отсев незаякоренных. Поле `target_membership_field` указывает, какой source-столбец содержит business-id, по которому source сверяется с target membership.

### Consumer policies

Политики использования topology-сигнала живут не в `*.topology.yaml`, а в match/resolve спеках (логически — часть topology-контракта):

```yaml
# *.match.yaml
match:
  topology:
    enabled: true
    apply_on: ambiguous_only        # ambiguous_only | all_candidates
    on_missing_topology: skip       # skip | hard_error
    comparison_ladder:              # обязателен при enabled
      - exact_canonical_path
      - exact_leaf_parent_chain

# *.resolve.yaml
resolve:
  topology_link:
    enabled: true
    field: organization_id          # обязателен при enabled
    on_missing_topology: pending    # pending | hard_error | skip
    on_ambiguous_topology: pending  # pending | hard_error | skip
    comparison_ladder:
      - exact_canonical_path
```

---

## 🔌 Контракты и границы

### Runtime-контракт (что отдаёт компилятор)

```python
@dataclass
class CompiledCanonicalizerPlan:           # = CompiledTopologyCanonicalizerPlan
    python: CompiledCanonicalizer                 # построчно (canonicalize_scalar/segments)
    polars_expression_plan: CompiledPolarsExpressionPlan  # векторно (для polars-проекции)
    normalization_version: str                    # sha256:<...> — отпечаток правил
```

**Гарантии**:
- `python` и `polars_expression_plan` собраны из одного `CanonicalizationSpec` → побайтово эквивалентная нормализация.
- `normalization_version` входит в synthetic node ids ([topology-core](./topology-core.md)) и в bootstrap metadata: смена правил меняет version → старые ids невалидны.

**Используется в**:
- target reader (`canonicalizer=compiled.python`) — [topology-infra](./topology-infra.md)
- source locator builder (`compiled.python`) — [topology-consumers](./topology-consumers.md)
- bootstrap event `canonicalizer.compiled` логирует `ops`, `ops_count`, `normalization_version`

### Границы слоёв

**Разрешено**:
- ✅ `TopologyDsl` → `CanonicalizationDsl`, `OperationRegistry`
- ✅ Spec-классы → `DslBaseModel`, shared canonicalization specs

**Запрещено**:
- ❌ DSL → `infra/*` (compiler не читает файлы и не знает про cache/polars-источник)
- ❌ Бизнес-валидация в spec (например, проверка существования target dataset — это работа activation resolver-а)

---

## 📌 Важные детали

### 🚨 Failure Modes

| Код | Условие | Где |
|-----|---------|-----|
| `TOPOLOGY_DSL_SPEC_INVALID` | YAML не проходит Pydantic-валидацию / неверный `source.mode` для validation | загрузка spec, runtime guard |
| `TOPOLOGY_DSL_COMPILE_INVALID` | ошибка компиляции canonicalization | `TopologyDsl.compile()` оборачивает любой `DslLoadError`/`Exception` |

Примеры валидационных правил (Pydantic):
- `path_columns` не должен быть пустым; `field` не пустой после `strip()`.
- adjacency source/target поля не пустые после `strip()`.
- `match.topology.comparison_ladder` обязателен при `enabled=true`.
- `resolve.topology_link.field` и `comparison_ladder` обязательны при `enabled=true`.
- `freshness.max_age_seconds > 0`; обязателен при `mode='max_age'`.

### ⚠️ Инварианты системы

1. **Source и target канонизируются одними правилами** — иначе пути не совпадут; обеспечивается единым `canonicalization`-блоком на оба ingress.
2. **`mode` — дискриминатор** — Pydantic не примет adjacency-поля в `path_columns`-спеке и наоборот.
3. **Capability-флаг ≠ policy** — `dataset_dsl.topology.enabled` включает подсистему; `match.topology.enabled`/`resolve.topology_link.enabled` включают *потребление*. Конфликт (policy on, capability off) ловится рано как `TOPOLOGY_CAPABILITY_DISABLED` ([topology-runtime](./topology-runtime.md)).

---

## 🛠️ Как расширять

### Добавить датасету topology-capability

1. Создать `datasets/<dataset>/<dataset>.topology.yaml` (`canonicalization` + `source` + `target`).
2. Включить флаг `topology.enabled: true` в dataset DSL датасета.
3. Зарегистрировать topology-спеку в реестре датасета (loader `load_topology_spec_for_dataset`).
4. Для потребления — добавить `match.topology` и/или `resolve.topology_link` с непустым `comparison_ladder`.

### Добавить canonicalization-op

См. [how-to-add-dsl-operation](../../guides/how-to-add-dsl-operation.md) — op должна попасть в whitelisted canonicalization namespace, иначе её нельзя будет использовать в topology.

### Добавить рунг в ladder

Добавить литерал в `TopologyComparisonLadderStep` + реализовать в comparison core ([topology-core](./topology-core.md) → «Как расширять»).

---

## 🔗 Связанные документы

- [Topology Core](./topology-core.md) — что делает builder с canonical labels/segments
- [Topology Consumers](./topology-consumers.md) — как policy применяется в match/resolve
- [Topology Runtime](./topology-runtime.md) — capability vs policy, activation
- [DSL Engine](../dsl/dsl-engine.md) — реестр операций
- [ADR TRANSFORM-DEC-010](../../../adr/transform/TRANSFORM-DEC-010-topology-bootstrap-before-main-pipeline.md)
