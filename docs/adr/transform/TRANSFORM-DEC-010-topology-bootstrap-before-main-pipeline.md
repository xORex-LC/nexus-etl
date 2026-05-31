# TRANSFORM-DEC-010: Topology bootstrap before main pipeline

> **Статус**: Принято
> **Дата принятия**: 2026-05-28
> **Решает проблему**: [TRANSFORM-PROBLEM-011](./TRANSFORM-PROBLEM-011-dependency-tree-topology-runtime-integration.md)
> **Участники решения**: @xorex-LC

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

- target topology snapshot строится из cache-backed target hierarchy;
- source topology snapshot или эквивалентное source-side topology representation строится отдельно до старта основного pipeline;
- основной `Extract -> Map -> Normalize -> Enrich -> Match -> ResolveContext -> Resolve` запускается только после того, как topology artifacts готовы и помещены в run-scoped artifacts/provider;
- source-side topology bootstrap использует **canonicalized projection flow**, а не raw ad-hoc parsing source layout;
- для CSV-backed source baseline Phase 1 — отдельный Polars-based projection adapter в `infra/`, а не обязательный replay row-by-row reader основного pipeline;
- source bootstrap, target topology build и row-level source topology lookup используют один и тот же compiled segment-level canonicalization contract;
- baseline ingestion contract для source builder в CSV path — `distinct canonical path batch`; per-row projection DTO допустим только как adapter-local trace/diagnostic envelope и не считается обязательным builder contract;
- runtime orchestration владеет моментом вызова bootstrap;
- topology build встраивается в явную pre-handler `Initialization Phase`, но Phase 1 не требует нового general-purpose startup framework;
- сама логика topology build выносится в отдельный bootstrap service/use case;
- topology не доставляется через mutable slot в `AppContainer`;
- build topology artifacts/provider выполняется в optional bootstrap slot pre-handler initialization;
- wiring готового topology provider в pipeline assembly выполняется внутри handler после resolve dataset spec/catalog и до materialization `planning_pipeline()`;
- stages получают topology через узкий `TopologyProviderPort`, а не напрямую через internal run-scoped carrier;
- первым topology consumer в Phase 1 фиксируется `MatchStage`; topology используется как refinement/disambiguation layer поверх existing identity/fuzzy candidate flow, а не как его замена;
- topology snapshots не делают match decisions сами; для stage-потребления вводится отдельный `TopologyMatchService`;
- `topology.yaml` владеет hierarchy projection и canonicalization contract, а `match.yaml` владеет только политикой использования topology signal;
- bootstrap result использует явный контракт `errors/warnings`, а не один неразделённый diagnostics tuple;
- source/target distinction остаётся частью internal runtime composition, а отсутствие обязательного snapshot выражается через typed exception;
- per-side `TopologyProviderPort` фиксируется как осознанный Phase 1 trade-off: stage API становится прямее, но расширяемость по OCP переносится на internal runtime/orchestration уровень;
- `Pydantic` применяется только на DSL/spec и других trust boundaries topology-подсистемы;
- `graphlib.TopologicalSorter` используется как helper для cycle detection / topological order внутри validator-builder слоя, но не заменяет topology snapshot/query API;
- `hashlib.sha256` используется для deterministic node ids, normalization/version fingerprints и provenance metadata;
- source-side path ingest трактуется как acyclic-by-construction после canonical path dedup, а target-side id ingest требует явной cycle validation;
- если `require_target_topology=True`, пустой или policy-stale target topology snapshot считается bootstrap failure, а не silent degraded mode;
- в будущем этот bootstrap pass должен быть встроен в общую `Initialization Phase`, но на Phase 1 может жить как отдельный orchestration step.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые классы/модули**:
- `dependency_tree` domain subsystem в `connector/domain/dependency_tree/`
  - builder
  - validator
  - snapshot/query API
- initialization phase extension
  - тонкий optional bootstrap slot в runtime orchestration
- topology bootstrap orchestration
  - `TopologyBootstrapStep` в runtime lifecycle
- topology bootstrap logic
  - отдельный `TopologyBootstrapService` или `TopologyBootstrapUseCase`
- topology readiness
  - отдельный `TopologyTargetReadinessEvaluator`
- source topology projection infra
  - отдельный `TopologySourceProjectionAdapter` / equivalent adapter в `connector/infra/`
- source/target ingress builders
  - `SourcePathTopologyBuilder`
  - `TargetHierarchyTopologyBuilder`
- run-scoped `TopologyRunArtifacts`
- `TopologyProviderPort` для stage consumers

**Изменения в существующих компонентах**:
- существующие `validate_requirements(...)` и `_init_container_for_requirements(...)` становятся первыми двумя шагами явной pre-handler initialization sequence без обязательного переоборачивания в новые framework-классы;
- `PlanningPipeline` и связанный runtime lifecycle должны получать уже готовые topology artifacts/provider
- `StageExecutionContext` / capability wiring должны предоставлять topology как read-only runtime artifact
- runtime orchestration должен уметь выполнить bootstrap step до старта основного stage chain
- runtime step не должен содержать предметную логику topology build
- pipeline materialization внутри handler не должна стартовать до того, как topology provider wiring выполнен

### Интерфейсы

```python
class TopologyBootstrapPort(Protocol):
    def build_source_topology(self, ...) -> TopologySnapshot: ...
    def build_target_topology(self, ...) -> TopologySnapshot: ...


class TopologyProviderPort(Protocol):
    def require_source(self) -> TopologySnapshot: ...
    def require_target(self) -> TopologySnapshot: ...
    def get_source(self) -> TopologySnapshot | None: ...
    def get_target(self) -> TopologySnapshot | None: ...
```

`TopologyProviderPort` относится только к stage-facing boundary.
Internal runtime/orchestration слой при этом может оставаться расширяемым к N snapshots.
Это осознанный компромисс Phase 1 между явностью API и OCP на уровне stage-facing порта.
Provider остаётся snapshot-only: provenance/readiness metadata не читаются стадиями
напрямую через этот port.

```python
class TopologyNotAvailableError(Exception):
    ...


@dataclass(frozen=True)
class TopologyNode:
    node_id: str
    parent_id: str | None
    display_name: str
    canonical_name: str


@dataclass(frozen=True)
class TopologyBuildMetadata:
    dataset_name: str
    source_file_fingerprint: str | None
    cache_snapshot_revision: str | None
    built_at: datetime
    topology_normalization_version: str


@dataclass(frozen=True)
class TopologyRunArtifacts:
    source_snapshot: TopologySnapshot | None
    target_snapshot: TopologySnapshot | None
    metadata: TopologyBuildMetadata


@dataclass(frozen=True)
class TopologyBootstrapResult:
    artifacts: TopologyRunArtifacts | None
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
class SourceTopologyCanonicalPath:
    canonical_segments: tuple[str, ...]


@dataclass(frozen=True)
class TopologyMatchResult:
    matched_target_id: str | None
    is_ambiguous: bool
    mode: str | None
    reason: str | None
    evidence: Mapping[str, Any]


@dataclass(frozen=True)
class TopologySnapshot:
    nodes_by_id: Mapping[str, TopologyNode]
    parent_by_id: Mapping[str, str | None]
    children_by_id: Mapping[str, tuple[str, ...]]
    roots: tuple[str, ...]


class CompiledTopologyCanonicalizer(Protocol):
    def canonicalize_segments(self, segments: tuple[str, ...]) -> tuple[str, ...]: ...


class TopologyMatchServicePort(Protocol):
    def compare(
        self,
        source_locator: SourceTopologyCanonicalPath,
        target_candidate_ids: tuple[str, ...],
    ) -> TopologyMatchResult: ...


@dataclass(frozen=True)
class TopologyTargetReadinessResult:
    is_ready: bool
    errors: tuple[DiagnosticItem, ...]
    warnings: tuple[DiagnosticItem, ...]
    details: Mapping[str, Any]
```

Семантика типов:

- `TopologyNode` описывает только node-level relation и labels; derived query facts
  вроде `depth`, `root_id`, `path_to_root` не входят в baseline node contract;
- `TopologyBuildMetadata` хранит provenance/build facts (`когда`, `из чего`, `с какой normalization version`),
  но не readiness/usability policy;
- readiness/freshness outcome живёт отдельно в `TopologyTargetReadinessResult`.

### Initialization Phase strategy

Phase 1 фиксирует двухшаговую стратегию:

1. **Tactical baseline**: не строить новый общий startup framework, а формализовать уже
   существующую pre-handler инициализацию как явную named sequence:
   `validate_requirements -> resource init -> optional bootstrap -> handler`.
2. **Strategic consolidation**: после появления нескольких bootstrap/readiness tasks
   эволюционно прийти к более общей `Initialization Phase`, не меняя topology domain contract.

Что это означает practically:

- текущие `validate_requirements(...)` и `_init_container_for_requirements(...)`
  рассматриваются как уже существующие шаги initialization lifecycle;
- topology добавляет только третий slot: optional bootstrap task;
- первый инкремент не требует переписывать шаги 1-2 в новые
  `PreflightValidationStep`/`ResourceInitializationStep` классы;
- единый pre-handler diagnostics/report boundary уже существует и должен быть переиспользован.

### Build vs wire

Для topology фиксируется жёсткое разделение:

- **build**: загрузка topology spec, построение snapshot и сборка provider происходят
  в optional bootstrap slot pre-handler initialization;
- **wire**: инъекция уже готового provider в pipeline / `StageExecutionContext`
  происходит внутри handler во время сборки pipeline.

Это снимает главное lifecycle-противоречие:

- topology bootstrap не требует раннего `dataset_spec` materialization внутри handler;
- topology spec может грузиться напрямую по dataset name так же, как preflight сейчас
  грузит `source.yaml` через `load_source_spec_for_dataset(...)`;
- pipeline-specific wiring остаётся там, где он и должен жить: рядом со сборкой pipeline.

### Поток данных

```
source topology projection adapter (+ optional vectorized canonicalization / dedup) ─┐
                                                                                     ├→ source topology snapshot
cache-backed hierarchy ───────────────────────────────────────────────────────────────┤
                                                                                     ├→ run-scoped topology artifacts/provider
                                                                                     ↓
Extract → Map → Normalize → Enrich → Match → ResolveContext → Resolve
```

Для source-side bootstrap утверждён internal flow:

```text
resolve projection config
  -> topology source projection adapter
  -> optional vectorized canonicalization / dedup
  -> distinct canonical path batch (+ optional adapter-local trace rows)
  -> SourceTopologyBuilder
  -> TopologySnapshot
```

### Strategy by library

#### Polars

- используется только в `infra/`;
- baseline для CSV-backed source topology bootstrap: выбрать только hierarchy path columns, выполнить узкую canonicalization и `distinct` canonical paths до domain builder;
- canonicalization contract компилируется один раз из `topology.yaml` и применяется одинаково к source bootstrap projection, row-level source locator и target-side hierarchy labels;
- topology bootstrap должен переиспользовать тот же source config contract, что и основной runtime, но не обязан использовать тот же row-by-row reader implementation.

Практический эффект:

- source-side topology build смещается ближе к `O(distinct paths)` по числу domain-ingestion объектов;
- bootstrap не превращается в обязательный Python object mini-pipeline на каждую source row;
- current row-based [connector/infra/sources/csv_reader.py](../../../connector/infra/sources/csv_reader.py) не является обязательным runtime contract для topology bootstrap.

#### Pydantic

- применяется для `topology.yaml` spec models, loader/validator и других trust boundaries;
- не используется как базовая модель для `TopologyNode`, `TopologySnapshot`, builder accumulators и других hot runtime объектов.

Практический эффект:

- boundary validation остаётся строгой;
- runtime/domain слой сохраняет лёгкие immutable dataclass/plain-class модели без лишней повторной валидации.

#### graphlib

- используется как stdlib helper для cycle detection и topological order внутри validator/build step;
- применяется по-разному для двух ingestion paths: target-side hierarchy проходит явную cycle validation, source-side canonical path ingest остаётся acyclic-by-construction после prefix-based derivation;
- не считается заменой custom snapshot/index/query модели.

Практический эффект:

- проект не дублирует готовую stdlib реализацию там, где нужен только topo-order;
- при этом `children_by_id`, `parent_by_id`, `ancestors`, `path_to_root` и stage-facing query API остаются responsibility topology domain subsystem.

#### hashlib

- используется для deterministic synthetic node ids, fingerprints и provenance metadata;
- hash contract строится только от canonicalized, детерминированно сериализованного payload;
- Python `hash()` не используется.

### Match consumer boundary

Phase 1 фиксирует первый topology-aware consumer: `MatchStage`.

Правила boundary:

- `dependency_tree` строит snapshots и query indexes, но не принимает match decisions;
- `MatchCore` не работает напрямую с graph traversal API;
- topology signal подаётся в match через отдельный `TopologyMatchService`;
- topology применяется после обычного candidate discovery как refinement/disambiguation layer;
- `match.yaml` не описывает hierarchy projection или canonicalization, а только политику использования topology signal.

Минимальный consumer flow:

```text
MatchCore
  -> existing identity/fuzzy candidate collection
  -> build row-level source topology locator via compiled topology canonicalizer
  -> TopologyMatchService.compare(...)
  -> enrich MatchDecision / ambiguity outcome with topology evidence
```

Минимальная topology policy в `match.yaml`:

- `enabled`
- `apply_on`
- `on_missing_topology`
- `comparison_ladder`

`topology.yaml` при этом остаётся единственным местом для hierarchy field mapping,
target label extraction и canonicalization rules.

Практический эффект:

- source-side synthetic ids не зависят от display-path string;
- metadata вроде `topology_normalization_version` и `source_file_fingerprint` естественно встраиваются в уже существующий fingerprint-style проекта.

### Metadata vs usability boundary

`TopologyRunArtifacts` уже содержит metadata, но Phase 1 сознательно не расширяет
`TopologyProviderPort` raw metadata-access methods.

Фиксируется следующее разделение:

- `TopologyProviderPort` отдаёт snapshots;
- `TopologyBuildMetadata` остаётся внутренним provenance/build contract;
- `TopologyTargetReadinessEvaluator` вычисляет freshness/readiness outcome;
- `TopologyMatchService` может получать уже подготовленный usability context, если
  degraded topology должна влиять на match-time behavior.

Это нужно, чтобы:

- не тянуть orchestration policy в stage API;
- не дублировать freshness logic в `MatchCore`;
- не превращать generic provider в второй runtime context carrier.

### Bootstrap diagnostics boundary

Topology bootstrap должен отдавать отдельные diagnostics до materialization main pipeline.

Boundary contract для Phase 1:

- diagnostics относятся к отдельному bootstrap-specific stage, а не к `MATCH` или `CACHE`;
- readiness decision принимается до сборки main pipeline;
- decision не живёт внутри `TopologySnapshot` и не перекладывается на `MatchStage`;
- cache status/drift facts могут переиспользоваться как вход readiness evaluator, но не заменяют его.
- topology-specific codes должны регистрироваться в core diagnostics catalog, а не как ad-hoc строки внутри bootstrap logic.

Минимальный набор Phase 1:

- `TOPOLOGY_TARGET_EMPTY` - обязательный target snapshot построен, но не содержит узлов;
- `TOPOLOGY_TARGET_STALE` - cache-backed target topology нарушает freshness policy;
- `TOPOLOGY_SNAPSHOT_NOT_AVAILABLE` - stage запрашивает обязательную topology capability, которая не была собрана;
- `TOPOLOGY_SOURCE_TARGET_INCOMPATIBLE` - source и target snapshots несовместимы по normalization/version contract.

Target readiness matrix:

- `require_target_topology=True` + snapshot missing -> error
- `require_target_topology=True` + snapshot empty -> error
- `require_target_topology=True` + freshness violated -> error
- `require_target_topology=False` + readiness degraded -> warning или skip capability по policy, но не silent success

### Initialization guardrails

- topology bootstrap не должен быть always-on; он активируется только command/dataset requirements;
- `cache refresh` не является частью initialization phase, даже если cache freshness check
  со временем окажется частью optional bootstrap/readiness tasks;
- pre-handler initialization phase не должна materialize-ить полный dataset pipeline только ради topology;
- topology build должен оставаться thin orchestration slot, а не поводом переписывать уже работающий preflight/resource-init код.

### Activation matrix

Phase 1 фиксирует один rule-driven activation contract.

Topology bootstrap активируется только если одновременно истинны три условия:

1. dataset/spec декларирует topology capability;
2. compiled match policy реально включает topology-aware matching;
3. command checkpoint включает `Match` или идёт после него.

Матрица текущих команд:

| Command / checkpoint | require_source_topology | require_target_topology | Причина |
|---|---:|---:|---|
| `mapping` | `False` | `False` | checkpoint до `Match` |
| `normalize` | `False` | `False` | checkpoint до `Match` |
| `enrich` | `False` | `False` | topology consumer ещё не активен |
| `match` | `True`* | `True`* | первый topology consumer |
| `resolve` | `True`* | `True`* | upstream включает `Match` |
| `import plan` | `True`* | `True`* | full planning pipeline включает `Match` |
| `import apply` | `False` | `False` | работает по готовому `plan.json` |
| cache/vault/admin commands | `False` | `False` | не используют planning pipeline |

\* только если dataset/spec и compiled match policy реально требуют topology-aware matching.

Для реализации рекомендуется единая policy point:

- `TopologyRequirementResolver`

Его вход:

- command/checkpoint
- dataset spec
- compiled match policy

Его выход:

- `TopologyBootstrapRequest`

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
- ✅ Runtime orchestration получает простой единый bootstrap request
- ✅ Source и target build paths могут развиваться независимо через специализированные internal requests
- ✅ Внешний bootstrap request остаётся routing/activation object и не смешивается с topology policy
- ✅ Source-side topology extraction использует стабильный projection DTO без выноса graph semantics из domain builder
- ✅ Source-side projection flow остаётся отдельным lightweight bootstrap path, а не прячется внутри main pipeline stages
- ✅ Для CSV-backed source bootstrap может использовать columnar/vectorized path вместо per-row object flow
- ✅ `Pydantic`, `graphlib` и `hashlib` закрывают boundary validation, topo-order/cycle detection и stable fingerprinting без лишних самописных абстракций
- ✅ Initialization Phase может быть введена эволюционно поверх уже существующих preflight/resource-init шагов без greenfield-framework first
- ✅ Lifecycle split `build before handler / wire inside handler` делает topology bootstrap совместимым с текущим command flow
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
- ⚠️ Vectorized baseline требует держать topology normalization в узком whitelist ops; произвольные Python UDF и тяжёлые cross-column transforms быстро ломают это упрощение
- ⚠️ Phase 1 сознательно оставляет preflight/resource init в существующей форме, а не вводит полный formal step framework

**Альтернативы, которые отклонили**:
- ❌ **Lazy build on first use**: скрывает lifecycle, даёт неявную latency и для source-backed topology всё равно вырождается в скрытый pre-pass
- ❌ **Incremental build inside main pipeline**: topology не готова к ранним stage queries и ломает прозрачность streaming contract
- ❌ **Collector in same pass as final runtime model**: полезен как техника bootstrap, но не как финальная модель runtime use
- ❌ **Raw source parsing inside init step**: дублирует source-layout knowledge и повышает риск расхождения с основным ETL path
- ❌ **Bootstrap целиком внутри `PlanningPipeline.open()`**: нарушает SRP `PlanningPipeline` и смешивает pipeline lifecycle с topology startup logic
- ❌ **Projection rows с уже вычисленными `node_key` / `parent_key`**: выносят graph semantics из domain builder в projection layer
- ❌ **Raw source rows как direct builder input**: заставляют topology builder знать source-layout concerns или дублировать parsing logic
- ❌ **SourceTopologyProjection как обычная stage основного pipeline**: смешивает bootstrap-lifecycle concerns с main streaming chain
- ❌ **Pydantic-моделировать весь runtime snapshot**: добавляет повторную валидацию и утяжеляет hot path без выигрыша в boundary safety
- ❌ **Определять topology ids через display path string или `hash()`**: нестабильно и плохо совместимо с versioned normalization contract
- ❌ **Сначала строить общий GeneralInitializationPhase framework**: для Phase 1 это лишнее переоборачивание уже существующих preflight/resource-init шагов без прямой пользы для topology
- ❌ **Topology как скрытая секция `mapping.yaml`**: смешивает bootstrap-specific hierarchy semantics с main transform-stage DSL

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/dependency_tree/*` | Новый domain subsystem |
| `connector/domain/ports/topology/*` | Runtime/topology port contracts |
| `connector/infra/topology/*` или `connector/infra/sources/*` | Source-side projection adapter на Polars + target-side topology readers |
| `connector/delivery/cli/runtime/*` | Bootstrap orchestration step |
| `connector/usecases/topology/*` | Bootstrap service/use case logic |
| `connector/delivery/cli/containers.py` | DI wiring bootstrap/provider dependencies и handler-scope stage capability delivery |
| `connector/delivery/cli/runtime/orchestrator.py` | Named pre-handler initialization sequence + optional bootstrap slot + pre-handler diagnostics boundary |
| `connector/delivery/pipelines/planning_pipeline.py` | Получение topology-capable run composition/context |
| `docs/notes/dependency-tree/DEPENDENCY_TREE_WORKNOTE.md` | Рабочая аналитика и обсуждения |

### Ключевые методы

- `build_source_topology(...)` - строит source-side topology из canonicalized source projection
- `build_target_topology(...)` - строит target-side topology из cache-backed hierarchy
- `TopologyTargetReadinessEvaluator.evaluate(...)` - принимает snapshot, provenance и cache readiness facts, возвращает fail-fast decision до старта main pipeline
- `TopologyRequirementResolver.resolve(...)` - вычисляет `TopologyBootstrapRequest` из command checkpoint, dataset topology capability и compiled match policy
- `TopologySourceProjectionAdapter.project_paths(...)` - выполняет source-side projection по topology-relevant columns и отдаёт distinct canonical paths
- `SourcePathTopologyBuilder.build(...)` - строит hierarchy из canonical path batch без row-level semantic coupling
- `TargetHierarchyTopologyBuilder.build(...)` - строит hierarchy из explicit `node_id -> parent_id` relations с полной graph validation
- `CompiledTopologyCanonicalizer.canonicalize_segments(...)` - единый canonicalization contract для source bootstrap, row-level lookup и target topology build
- `TopologyMatchService.compare(...)` - интерпретирует topology signal для `MatchStage`, не смешивая match policy с graph storage
- `TopologyBootstrapStep.run(...)` - запускает bootstrap в runtime lifecycle
- `validate_requirements(...)` - текущий fast preflight step initialization phase
- `_init_container_for_requirements(...)` - текущий resource-init step initialization phase
- `TopologyProviderPort.require_source(...)` - отдаёт обязательный source topology snapshot или выбрасывает typed exception
- `TopologyProviderPort.require_target(...)` - отдаёт обязательный target topology snapshot или выбрасывает typed exception
- `TopologyProviderPort.get_source(...)` / `get_target(...)` - soft-access для optional topology consumers
- `TopologyBootstrapRequest` - orchestration-level routing/activation request
- `SourceTopologyBuildRequest` / `TargetTopologyBuildRequest` - internal specialized build requests

### Инварианты

1. **Topology готова до основного pipeline**: topology-aware stages не работают с незавершённым graph
2. **Основной pipeline остаётся streaming**: bootstrap не встраивается скрыто в обычный record-by-record pass
3. **Bootstrap использует canonicalized source view**: raw source layout не становится частью domain topology contract
4. **Topology snapshots read-only**: после построения snapshot не мутируется по ходу run
5. **Runtime step не содержит topology build logic**: orchestration и построение graph разделены
6. **Topology build выполняется pre-handler, wiring — inside handler**: bootstrap artifacts строятся до handler, а provider inject-ится при materialization pipeline
7. **Bootstrap errors short-circuit execution**: при фатальных bootstrap diagnostics handler не вызывается
8. **TopologyBootstrapRequest не несёт policy semantics**: strictness и topology behavior не зашиваются во внешний orchestration request
9. **`topology_dataset` normalizes once**: `None -> pipeline_dataset` выполняется в одном bootstrap boundary, а не размазывается по consumers
10. **Source builder ingests distinct canonical paths**: canonical path batch является baseline contract, а per-row trace DTO не обязателен для domain builder
11. **Один canonicalization contract используется симметрично**: source bootstrap, source row-level lookup и target hierarchy ingest должны давать совместимые canonical segments
12. **Source-side projection flow остаётся bootstrap-local**: source projection adapter и canonicalizer не становятся частью main planning pipeline stage chain
13. **Topology задаётся отдельным DSL artifact**: dataset-level topology capability декларируется через registry/spec layer, а detailed hierarchy projection и normalization живут в `topology.yaml`
14. **Polars остаётся infra-only зависимостью**: domain topology builder/query API не импортируют `polars`
15. **Pydantic остаётся boundary-only зависимостью**: runtime snapshot/query модели topology не требуют `BaseModel`
16. **Stable ids/fingerprints строятся из canonical contract**: display labels не являются primary runtime id source
17. **Initialization Phase не materialize-ит полный pipeline ради topology**: pre-handler шаги ограничены validation/resource readiness/bootstrap build задачами
18. **Cache refresh остаётся отдельным use case**: readiness/freshness checks допустимы, mutating refresh — нет
19. **Target topology readiness проверяется fail-fast**: пустой или policy-stale target snapshot не может silently выключить topology-aware matching
20. **`MatchStage` — первый topology consumer**: graph snapshots изолированы от stage logic через `TopologyMatchService`
21. **Readiness — отдельная orchestration responsibility**: snapshot build, readiness evaluation и stage consumption не смешиваются между собой
22. **Source и target ingress semantics не симметричны**: source path ingest считается acyclic-by-construction, target hierarchy ingest требует полной cycle/missing-parent validation
23. **Builder contract и trace contract разделены**: canonical path batch является domain ingress baseline, row-level trace остаётся optional diagnostic envelope
24. **Provider и metadata не смешиваются**: stage-facing provider остаётся snapshot-only, а usability/readiness context передаётся только dedicated consumer-ам
25. **Activation определяется одной policy point**: topology bootstrap requirements вычисляются из checkpoint/spec/policy, а не ad-hoc по именам команд

---

## 🧪 Валидация решения

**Тесты**:
- ✅ Unit tests для builder/validator/query API dependency tree
- ✅ Integration tests для source bootstrap flow и target bootstrap flow
- ✅ E2E tests для topology-enabled pipeline run

**Проверка в runtime**:
1. Запустить topology bootstrap на source hierarchy path dataset
2. Убедиться, что source topology snapshot и target topology snapshot строятся до старта planning pipeline
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
target_snapshot = bootstrap.build_target_topology(...)
source_snapshot = bootstrap.build_source_topology(...)
artifacts = TopologyRunArtifacts(
    source_snapshot=source_snapshot,
    target_snapshot=target_snapshot,
    metadata=topology_metadata,
)
topology_provider = build_topology_provider(artifacts)
runtime = runtime.with_topology_provider(topology_provider)

with planning_pipeline.open(run_id, runtime) as stream:
    for result in stream:
        ...
```

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Phase 1 допускает асимметрию: полноценный target snapshot и более лёгкий source-side topology representation
- Tactical initialization phase в Phase 1 остаётся thin sequence, а не полным generalized lifecycle framework
- Общая platform-level `Initialization Phase` ещё не формализована как отдельный reusable framework
- Activation model bootstrap сначала будет command-driven, а не полностью declarative
- Request contract должен различать `pipeline_dataset` и `topology_dataset`, если topology читается из другого dataset
- Внутренние source/target build requests пока зафиксированы как Phase 1 split без полной topology spec integration
- Внешний `TopologyBootstrapRequest` намеренно не содержит policy/source-path details; они должны жить ниже, в spec/build contracts
- Source-side bootstrap требует отдельного lightweight projection path вместо raw source parse или полного replay main mapping path
- Path canonicalization выполняется до builder ingestion и не смешивается с graph-level topology semantics
- Повторное чтение source и повторная узкая topology-normalization считаются допустимым bootstrap trade-off при условии, что topology path rules остаются ограниченными и не превращаются во второй full normalize flow
- Current main CSV reader может оставаться row-based; topology bootstrap не обязан делить с ним одну и ту же implementation path
- Topology build pre-handler не отменяет необходимость handler-scope wiring в pipeline assembly
- Baseline source ingest contract — canonical path batch; row-level traceability, если нужна, должна жить как optional diagnostic envelope, а не как обязательный builder input
- Empty target snapshot при обязательной topology capability недопустим как silent fallback
- Freshness/staleness target topology должна маппиться в bootstrap diagnostics, а не в поздние match anomalies
- Readiness policy зависит от качества cache metadata; при отсутствии нужных freshness facts policy должна явно деградировать в `warning` или `error`, но не в implicit success
- Source и target ingress paths намеренно имеют разные validator semantics; это не временная несимметрия, а отражение разных data contracts
- Если metadata напрямую открыть через generic provider, stage layer быстро начнёт тащить orchestration policy внутрь себя
- Activation matrix Phase 1 ориентирована на текущие checkpoint команды; новые команды должны подключаться через requirement resolver, а не через ad-hoc `if command == ...`

**Риски**:
- ⚠️ Нестабильная нормализация source hierarchy path может дать ложные topology mismatches
  - **Митигация**: выделить явный topology-normalize contract и тестировать synthetic path generation отдельно
- ⚠️ Bootstrap flow может начать дублировать слишком много логики основного pipeline
  - **Митигация**: ограничить его map/topology-normalize/topology-collector шагами
- ⚠️ Дополнительное чтение source увеличит startup latency
  - **Митигация**: рассмотреть reopen/replay или внешний topology artifact как future optimization
- ⚠️ Выход за узкий whitelist topology ops быстро разрушит vectorized Polars baseline
  - **Митигация**: держать topology normalization отдельной, deterministic и выражаемой через expression API по умолчанию
- ⚠️ Преждевременное формализованное обобщение initialization lifecycle может дать много обвязки без практической пользы
  - **Митигация**: в Phase 1 добавить только optional bootstrap slot поверх уже существующих preflight/resource-init шагов
- ⚠️ Source topology и target topology могут быть построены из разных по времени состояний данных
  - **Митигация**: сохранять provenance metadata (`source_file_fingerprint`, `cache_snapshot_revision`, `built_at`, `topology_normalization_version`) и проверять freshness cache-backed target topology
- ⚠️ Source bootstrap, row-level lookup и target-side labels могут canonicalize-иться по разным правилам
  - **Митигация**: компилировать один shared canonicalization contract из `topology.yaml` и использовать его симметрично во всех трёх точках
- ⚠️ Topology capability может быть технически доступна, но не интегрирована в match decision boundary
  - **Митигация**: вводить topology в `MatchStage` только через выделенный `TopologyMatchService` и фиксировать policy boundary в `match.yaml`
- ⚠️ Один “универсальный” builder быстро размоет разницу между source path ingest и target hierarchy ingest
  - **Митигация**: фиксировать два ingress builder-а с общим snapshot assembly слоем, а не один source-agnostic constructor
- ⚠️ Row-level trace DTO может снова стать неявным builder contract и сломать `distinct` baseline
  - **Митигация**: держать trace envelope adapter-local и не пропускать его как обязательный domain ingress type
- ⚠️ Match-time freshness policy может просочиться в stage API через metadata getters
  - **Митигация**: держать provider snapshot-only и передавать usability context только в `TopologyMatchService`
- ⚠️ Activation logic может расползтись по handler/composer/spec loader
  - **Митигация**: вычислять topology requirements в одном `TopologyRequirementResolver`

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `PlanningPipeline` | Получает topology-capable run composition | Нужно принимать topology-capable runtime/context |
| `StageExecutionContext` | Новая capability | Добавить `TopologyProviderPort` в capability registry |
| `Match` | Первый topology consumer | Использовать `TopologyMatchService` как refinement/disambiguation layer поверх existing candidate flow |
| `Enrich` / `Resolve` | Потенциальные будущие consumers | Не строить graph сами; подключать topology позже отдельными решениями |
| Runtime orchestration | Новый bootstrap step | Запускать topology build до main pipeline, не владея build logic |
| Topology use case/service | Новый orchestration executor | Инкапсулировать source/target topology build |
| Topology readiness | Новый orchestration evaluator | Принимать snapshot + cache facts и выдавать fail-fast readiness decision |
| Topology requirement resolution | Новый orchestration policy point | Вычислять topology bootstrap activation из checkpoint/spec/match policy |
| Source topology projection | Новый bootstrap boundary | Эмитить distinct canonical paths и optional diagnostic trace, не вычисляя graph keys |
| Source topology builder | Новый source-specific ingress path | Принимать canonical path batch и не зависеть от row-level trace envelope |
| Target topology builder | Новый target-specific ingress path | Валидировать parent relations, missing parents и cycles до assembly |
| Topology canonicalizer | Новый shared contract | Обеспечить симметрию source bootstrap, row-level lookup и target hierarchy ingest |
| Topology match service | Новый consumer adapter | Интерпретировать topology evidence для `MatchStage` без смешения с snapshot storage |
| Dataset topology DSL | Новый declarative artifact | Описывать hierarchy fields, path order и topology-specific normalization |
| Runtime/report boundary | Новый bootstrap result path | Маппить bootstrap `errors/warnings` в `CommandResult` и report до materialization/запуска main pipeline |
| Initialization phase | Новый optional slot | Формализовать sequence `validate -> init resources -> optional bootstrap -> handler` без обязательного greenfield-framework |
| Delivery DI | Новый wiring | Собрать bootstrap/provider зависимости и обеспечить handler-scope delivery в pipeline assembly; при отказе от mutable override нужен явный composition input для `planning_pipeline` или эквивалентный scoped wiring path |

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
| 2026-05-28 | Уточнены boundary contracts: bootstrap result, provider port и typed exception |
| 2026-05-29 | Зафиксирован baseline `SourceTopologyProjectionRow` и projection-vs-builder boundary |
| 2026-05-29 | Зафиксирован pipeline `source projection adapter -> path canonicalization -> builder` |
| 2026-05-29 | Topology вынесена в отдельный DSL artifact; повторная узкая normalization признана допустимым bootstrap trade-off |
| 2026-05-31 | Зафиксирована library strategy: Polars for infra projection, Pydantic for boundaries, graphlib for topo-order/cycle detection, hashlib for stable ids/fingerprints |
| 2026-05-31 | Зафиксирована tactical Initialization Phase strategy: existing preflight/resource init + optional bootstrap slot, build pre-handler and wire inside handler |
| 2026-05-31 | Зафиксирован shared canonicalization contract для source bootstrap, row-level lookup и target topology build |
| 2026-05-31 | Зафиксирован `MatchStage` как первый topology consumer через отдельный `TopologyMatchService`; source builder baseline переведён на canonical path batch |
| 2026-05-31 | Зафиксированы отдельный target readiness evaluator, разделение builder-vs-trace contract и явная асимметрия source/target validator semantics |
| 2026-05-31 | Зафиксированы snapshot-only provider boundary, semantic notes для metadata/node contracts и activation matrix через requirement resolver |
