# TRANSFORM-DEC-010: Topology bootstrap before main pipeline

> **Статус**: Принято
> **Дата принятия**: 2026-05-28
> **Решает проблему**: [TRANSFORM-PROBLEM-011](./TRANSFORM-PROBLEM-011-dependency-tree-topology-runtime-integration.md)
> **Участники решения**: @user, @codex

---

## 📋 Контекст

Для внедрения `dependency_tree` в ETL pipeline нужно было определить runtime-модель построения topology snapshot.

Проблема состояла в том, что topology-aware use cases требуют готовую и валидную иерархию уже во время работы `enrich`, `match` и `resolve`, а основной planning pipeline в проекте является streaming:

> `Extract -> Map -> Normalize -> Enrich -> Match -> ResolveContext -> Resolve`

Дополнительно source и target представляют hierarchy по-разному:
- source — как строковые уровни пути;
- target/cache — как `organization_id` и cache mirror.

Это исключает вариант, где topology строится только по target-side данным, и делает недостаточными решения, в которых graph "дозревает" по ходу основного потока.

---

## 🎯 Решение

Принято решение строить topology **до запуска основного planning pipeline** через отдельный explicit bootstrap pass.

Базовая модель Phase 1:

- `target_topology` строится из cache-backed target hierarchy;
- `source_topology` или эквивалентное source-side topology representation строится отдельно до старта основного pipeline;
- основной `Extract -> Map -> Normalize -> Enrich -> Match -> ResolveContext -> Resolve` запускается только после того, как topology artifacts готовы и помещены в run-scoped context;
- source-side topology bootstrap использует **canonicalized projection flow**, а не raw ad-hoc parsing source layout;
- runtime orchestration владеет моментом вызова bootstrap;
- сама логика topology build выносится в отдельный bootstrap service/use case;
- topology slot объявляется в `AppContainer`, а `PipelineContainer` читает его как dependency;
- override topology dependency выполняется после bootstrap и до bind/handler boundary;
- stages получают topology через узкий `TopologySnapshotProviderPort`, а не напрямую через `TopologyRuntime`;
- bootstrap result использует явный контракт `errors/warnings`, а не один неразделённый diagnostics tuple;
- topology snapshot names типизируются через enum, а отсутствие snapshot выражается через typed exception;
- в будущем этот bootstrap pass должен быть встроен в общую `Initialization Phase`, но на Phase 1 может жить как отдельный orchestration step.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `dependency_tree` domain subsystem в `connector/domain/dependency_tree/`
  - builder
  - validator
  - snapshot/query API
- topology bootstrap orchestration
  - `TopologyBootstrapStep` в runtime lifecycle
- topology bootstrap logic
  - отдельный `TopologyBootstrapService` или `TopologyBootstrapUseCase`
- run-scoped `TopologyRuntime`
- `TopologySnapshotProviderPort` для stage consumers

**Изменения в существующих компонентах**:
- `PlanningPipeline` и связанный runtime lifecycle должны получать уже готовые topology snapshots
- `StageExecutionContext` / capability wiring должны предоставлять topology как read-only runtime artifact
- runtime orchestration должен уметь выполнить bootstrap step до старта основного stage chain
- runtime step не должен содержать предметную логику topology build
- handler boundary не должна стартовать до того, как topology dependency override выполнен

### Интерфейсы

```python
class TopologyBootstrapPort(Protocol):
    def build_source_topology(self, ...) -> TopologySnapshot: ...
    def build_target_topology(self, ...) -> TopologySnapshot: ...


class TopologySnapshotProviderPort(Protocol):
    def has(self, name: TopologySnapshotName) -> bool: ...
    def get(self, name: TopologySnapshotName) -> TopologySnapshot: ...
```

```python
class TopologySnapshotName(str, Enum):
    SOURCE = "source_topology"
    TARGET = "target_topology"


class TopologyNotAvailableError(Exception):
    def __init__(self, name: TopologySnapshotName) -> None: ...


@dataclass(frozen=True)
class TopologyRuntime:
    snapshots: Mapping[str, TopologySnapshot]

    def get(self, name: TopologySnapshotName) -> TopologySnapshot: ...


@dataclass(frozen=True)
class TopologyBootstrapResult:
    runtime: TopologyRuntime | None
    errors: tuple[DiagnosticItem, ...]
    warnings: tuple[DiagnosticItem, ...]


@dataclass(frozen=True)
class TopologyBootstrapRequest:
    pipeline_dataset: str
    topology_dataset: str | None
    run_id: str
    require_source_topology: bool
    require_target_topology: bool


@dataclass(frozen=True)
class SourceTopologyBuildRequest:
    pipeline_dataset: str
    topology_dataset: str
    run_id: str


@dataclass(frozen=True)
class TargetTopologyBuildRequest:
    pipeline_dataset: str
    topology_dataset: str
    run_id: str


@dataclass(frozen=True)
class SourceTopologyProjectionRow:
    row_ref: RowRef | None
    path_segments: tuple[str, ...]


@dataclass(frozen=True)
class TopologySnapshot:
    nodes_by_id: Mapping[str, TopologyNode]
    parent_by_id: Mapping[str, str | None]
    children_by_id: Mapping[str, tuple[str, ...]]
    roots: tuple[str, ...]
```

### Поток данных

```
source reader + map (+ topology-normalize) ─┐
                                            ├→ source_topology
cache-backed hierarchy ─────────────────────┤
                                            ├→ run-scoped topology context
                                            ↓
Extract → Map → Normalize → Enrich → Match → ResolveContext → Resolve
```

Для source-side bootstrap утверждён internal flow:

```text
resolve projection config
  -> source reader
  -> projection mapper
  -> topology path normalizer
  -> SourceTopologyProjectionRow stream
  -> SourceTopologyBuilder
  -> TopologySnapshot
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Topology полностью готова к моменту первого topology-aware запроса стадии
- ✅ Основной streaming pipeline остаётся чистым и не превращается в скрытый full-buffer pass
- ✅ Lifecycle graph build становится явным и диагностируемым
- ✅ `dependency_tree` остаётся изолированной domain capability без привязки к конкретной стадии
- ✅ Runtime orchestration и topology build logic разделены по SRP
- ✅ Stage consumers зависят от узкого provider port, а не от concrete runtime carrier
- ✅ Bootstrap failure semantics становятся явными через `errors/warnings`
- ✅ Snapshot names типизированы и не зависят от raw string keys
- ✅ Runtime orchestration получает простой единый bootstrap request
- ✅ Source и target build paths могут развиваться независимо через специализированные internal requests
- ✅ Внешний bootstrap request остаётся routing/activation object и не смешивается с topology policy
- ✅ Source-side topology extraction использует стабильный projection DTO без выноса graph semantics из domain builder
- ✅ Source-side projection flow остаётся отдельным lightweight bootstrap path, а не прячется внутри main pipeline stages
- ✅ Topology оформляется как отдельный DSL artifact (`topology.yaml`), а не как скрытое расширение `mapping.yaml`
- ✅ Решение поддерживает обе стороны matching: source-side и target-side topology
- ✅ Подход совместим с дальнейшим переходом к общей `Initialization Phase`

**Недостатки (компромиссы)**:
- ⚠️ Source почти наверняка читается отдельно до основного pipeline (но это приемлемая цена за корректный topology snapshot)
- ⚠️ Появляется отдельный bootstrap orchestration step (но он делает lifecycle явным и управляемым)
- ⚠️ Source-side bootstrap не должен разрастись в дубликат всего planning pipeline (но это контролируется ограничением bootstrap flow только topology-нужными данными)
- ⚠️ Появляется дополнительная абстракция между runtime step и bootstrap logic (но она оправдана разделением ответственности)
- ⚠️ Появляется дополнительный provider layer между stages и runtime carrier (но он снижает связность и удерживает stage API стабильным)
- ⚠️ Typed result/provider contracts добавляют несколько новых small abstractions (но они резко повышают определённость boundary)
- ⚠️ Появляется двухуровневый request contract — внешний orchestration request и внутренние build requests (но это удерживает SRP и не раздувает внешний API)
- ⚠️ Появляется отдельный source topology projection contract, который нужно сопровождать и тестировать отдельно
- ⚠️ Появляется явный bootstrap-local projection flow с собственной config/normalization surface
- ⚠️ Чтение source и узкая topology-normalization выполняются повторно до основного pipeline

**Альтернативы, которые отклонили**:
- ❌ **Lazy build on first use**: скрывает lifecycle, даёт неявную latency и для source-backed topology всё равно вырождается в скрытый pre-pass
- ❌ **Incremental build inside main pipeline**: topology не готова к ранним stage queries и ломает прозрачность streaming contract
- ❌ **Collector in same pass as final runtime model**: полезен как техника bootstrap, но не как финальная модель runtime use
- ❌ **Raw source parsing inside init step**: дублирует source-layout knowledge и повышает риск расхождения с основным ETL path
- ❌ **Bootstrap целиком внутри `PlanningPipeline.open()`**: нарушает SRP `PlanningPipeline` и смешивает pipeline lifecycle с topology startup logic
- ❌ **Projection rows с уже вычисленными `node_key` / `parent_key`**: выносят graph semantics из domain builder в projection layer
- ❌ **Raw source rows как direct builder input**: заставляют topology builder знать source-layout concerns или дублировать parsing logic
- ❌ **SourceTopologyProjection как обычная stage основного pipeline**: смешивает bootstrap-lifecycle concerns с main streaming chain
- ❌ **Topology как скрытая секция `mapping.yaml`**: смешивает bootstrap-specific hierarchy semantics с main transform-stage DSL

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/dependency_tree/*` | Новый domain subsystem |
| `connector/domain/ports/topology/*` | Runtime/topology port contracts |
| `connector/delivery/cli/runtime/*` | Bootstrap orchestration step |
| `connector/usecases/topology/*` | Bootstrap service/use case logic |
| `connector/delivery/cli/containers.py` | DI wiring AppContainer slot, provider port и bootstrap dependencies |
| `connector/delivery/pipelines/planning_pipeline.py` | Получение topology snapshots из run-scoped context |
| `docs/notes/dependency-tree/DEPENDENCY_TREE_WORKNOTE.md` | Рабочая аналитика и обсуждения |

### Ключевые методы

- `build_source_topology(...)` - строит source-side topology из canonicalized source projection
- `build_target_topology(...)` - строит target-side topology из cache-backed hierarchy
- `SourceTopologyProjectionRow` - минимальный DTO между projection path и domain topology builder
- `TopologyPathNormalizer` - canonicalizes hierarchy path segments before builder ingestion
- `TopologyBootstrapStep.run(...)` - запускает bootstrap в runtime lifecycle
- `TopologySnapshotProviderPort.has(...)` - позволяет безопасно проверить доступность topology snapshot
- `TopologySnapshotProviderPort.get(...)` - отдаёт topology snapshot stage consumer-у или выбрасывает typed exception
- `TopologyBootstrapRequest` - orchestration-level routing/activation request
- `SourceTopologyBuildRequest` / `TargetTopologyBuildRequest` - internal specialized build requests
- `get(name)` - возвращает topology snapshot по runtime name

### Инварианты

1. **Topology готова до основного pipeline**: topology-aware stages не работают с незавершённым graph
2. **Основной pipeline остаётся streaming**: bootstrap не встраивается скрыто в обычный record-by-record pass
3. **Bootstrap использует canonicalized source view**: raw source layout не становится частью domain topology contract
4. **Topology snapshots read-only**: после построения snapshot не мутируется по ходу run
5. **Runtime step не содержит topology build logic**: orchestration и построение graph разделены
6. **Topology dependency override выполняется до handler boundary**: stages не материализуются с пустым topology slot
7. **Bootstrap errors short-circuit execution**: при фатальных bootstrap diagnostics handler не вызывается
8. **TopologyBootstrapRequest не несёт policy semantics**: strictness и topology behavior не зашиваются во внешний orchestration request
9. **`topology_dataset` normalizes once**: `None -> pipeline_dataset` выполняется в одном bootstrap boundary, а не размазывается по consumers
10. **`SourceTopologyProjectionRow` несёт только canonicalized path segments**: synthetic ids и parent ids вычисляются в domain topology builder
11. **Source-side projection flow остаётся bootstrap-local**: source reader, projection mapper и path normalizer не становятся частью main planning pipeline stage chain
12. **Topology задаётся отдельным DSL artifact**: dataset-level topology capability декларируется через registry/spec layer, а detailed hierarchy projection и normalization живут в `topology.yaml`

---

## 🧪 Валидация решения

**Тесты**:
- ✅ Unit tests для builder/validator/query API dependency tree
- ✅ Integration tests для source bootstrap flow и target bootstrap flow
- ✅ E2E tests для topology-enabled pipeline run

**Проверка в runtime**:
1. Запустить topology bootstrap на source hierarchy path dataset
2. Убедиться, что `source_topology` и `target_topology` строятся до старта planning pipeline
3. Проверить, что `match` использует topology-aware disambiguation и корректно различает одинаковые leaf names в разных ветках

**Метрики успеха**:
- Количество ambiguous matches для hierarchy-sensitive departments должно уменьшиться
- Topology diagnostics должны появляться на bootstrap step, а не в середине main pipeline

---

## 📐 Диаграммы

**UML диаграммы** (если созданы):
- Пока не созданы

**Примеры использования**:

```python
target_topology = bootstrap.build_target_topology(...)
source_topology = bootstrap.build_source_topology(...)
topology_runtime = TopologyRuntime(
    snapshots={
        "target_topology": target_topology,
        "source_topology": source_topology,
    }
)
runtime = runtime.with_topology(topology_runtime)

with planning_pipeline.open(run_id, runtime) as stream:
    for result in stream:
        ...
```

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Phase 1 допускает асимметрию: полноценный target snapshot и более лёгкий source-side topology representation
- Bootstrap lifecycle пока может существовать отдельно от общей `Initialization Phase`
- Activation model bootstrap сначала будет command-driven, а не полностью declarative
- Request contract должен различать `pipeline_dataset` и `topology_dataset`, если topology читается из другого dataset
- Внутренние source/target build requests пока зафиксированы как Phase 1 split без полной topology spec integration
- Внешний `TopologyBootstrapRequest` намеренно не содержит policy/source-path details; они должны жить ниже, в spec/build contracts
- Source-side bootstrap требует отдельного lightweight projection path вместо raw source parse или полного replay main mapping path
- Path canonicalization выполняется до builder ingestion и не смешивается с graph-level topology semantics
- Повторное чтение source и повторная узкая topology-normalization считаются допустимым bootstrap trade-off при условии, что topology path rules остаются ограниченными и не превращаются во второй full normalize flow

**Риски**:
- ⚠️ Нестабильная нормализация source hierarchy path может дать ложные topology mismatches
  - **Митигация**: выделить явный topology-normalize contract и тестировать synthetic path generation отдельно
- ⚠️ Bootstrap flow может начать дублировать слишком много логики основного pipeline
  - **Митигация**: ограничить его map/topology-normalize/topology-collector шагами
- ⚠️ Дополнительное чтение source увеличит startup latency
  - **Митигация**: рассмотреть reopen/replay или внешний topology artifact как future optimization

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `PlanningPipeline` | Получает topology runtime artifact | Нужно принимать topology-capable runtime/context |
| `StageExecutionContext` | Новая capability | Добавить `TopologySnapshotProviderPort` в capability registry |
| `Match` / `Enrich` / `Resolve` | Получают topology-aware query path | Использовать topology capability, не строить graph сами |
| Runtime orchestration | Новый bootstrap step | Запускать topology build до main pipeline, не владея build logic |
| Topology use case/service | Новый orchestration executor | Инкапсулировать source/target topology build |
| Source topology projection | Новый bootstrap boundary | Эмитить canonicalized path DTOs, не вычисляя graph keys |
| Topology path normalization | Новый bootstrap-local step | Canonicalize hierarchy segments до domain builder |
| Dataset topology DSL | Новый declarative artifact | Описывать hierarchy fields, path order и topology-specific normalization |
| Runtime/report boundary | Новый bootstrap result path | Маппить bootstrap `errors/warnings` в `CommandResult` и report до handler |
| Delivery DI | Новый wiring | Собрать bootstrap/provider зависимости |

---

## 📚 Документация

**Обновлена документация**:
- ✅ [Dependency Tree Worknote](../../notes/dependency-tree/DEPENDENCY_TREE_WORKNOTE.md) - рабочая аналитика
- ✅ [TRANSFORM-PROBLEM-011](./TRANSFORM-PROBLEM-011-dependency-tree-topology-runtime-integration.md) - формализованная проблема
- ⏳ Понадобится обновление layer docs после реализации

---

## 🔗 Связанные документы

- [TRANSFORM-PROBLEM-011](./TRANSFORM-PROBLEM-011-dependency-tree-topology-runtime-integration.md) - решаемая проблема
- [Dependency Tree Worknote](../../notes/dependency-tree/DEPENDENCY_TREE_WORKNOTE.md) - рабочее обсуждение и аналитика
- [ADR Index](../INDEX.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-05-28 | Решение предложено |
| 2026-05-28 | Решение принято после обсуждения |
| 2026-05-28 | Уточнён runtime integration contract: hybrid runtime step + bootstrap service |
| 2026-05-28 | Уточнены boundary contracts: bootstrap result, provider port, enum names, typed exception |
| 2026-05-28 | Зафиксирован baseline `SourceTopologyProjectionRow` и projection-vs-builder boundary |
| 2026-05-28 | Зафиксирован pipeline `source reader -> projection mapper -> path normalizer -> builder` |
| 2026-05-28 | Topology вынесена в отдельный DSL artifact; повторная узкая normalization признана допустимым bootstrap trade-off |
