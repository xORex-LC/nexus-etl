# TRANSFORM-DEC-004: Modular Pipeline with Scoped Execution Context

> **Статус**: Принято — реализация поэтапная
> **Дата принятия**: 2026-02-22
> **Решает проблему**: [TRANSFORM-PROBLEM-004](./TRANSFORM-PROBLEM-004-missing-modular-pipeline-architecture.md)
> **Поглощает**: [TRANSFORM-DEC-002](./TRANSFORM-DEC-002-transform-context-capability-registry.md), [TRANSFORM-DEC-003](./TRANSFORM-DEC-003-pipeline-container-lazy-stage-assembly.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

Pipeline вырос до 5 стадий (map, normalize, enrich, match, resolve), 3 capability-семейств (cache, vault, dictionaries) и 6 CLI-команд. При этом нет единой архитектурной модели: стадии используют разные контракты, три подхода к получению зависимостей, два механизма оркестрации. `DatasetSpec` превратился в god-protocol с 15+ методами. `build_pipeline_context()` строит eagerly весь граф для любой команды.

Ранее были предложены два частных решения:

- **DEC-002** (TransformContext) — typed capability registry для enrich deps
- **DEC-003** (PipelineContainer) — lazy per-stage DI для delivery wiring

Оба решают свои подпроблемы, но не дают целостной архитектуры. Данное решение определяет **полную модель**, поглощающую оба частных решения и закрывающую все 7 разрывов из [TRANSFORM-PROBLEM-004](./TRANSFORM-PROBLEM-004-missing-modular-pipeline-architecture.md).

---

## 🎯 Решение

Архитектура **"Modular Pipeline with Scoped Execution Context"** — комбинация паттернов Pipeline + Dependency Injection + Plugin Architecture. Четыре компонента:

1. **Stage Contract** — единый протокол для всех стадий (включая match/resolve)
2. **Stage Execution Context** — scoped объект с метаданными pipeline и capability-зависимостями для конкретной стадии
3. **Stage Factory** — создаёт стадию из DSL-конфигурации и execution context, заменяя god-protocol
4. **Pipeline Orchestrator** — управляет полным потоком от source до resolved, с lifecycle hooks

Сборка через **PipelineContainer** (dependency-injector `DeclarativeContainer`) — lazy resolution, explicit dependency graph, open/closed для новых capabilities.

---

## 🏗️ Архитектурное решение

### Компонент 1: Stage Contract

**Проблема**: `TransformStageProcessor` покрывает только 3 из 5 стадий. `ResolveStage.run()` нарушает контракт. Match/Resolve имеют отдельные протоколы.

**Решение**: Единый контракт, охватывающий все стадии:

```python
class StageContract(Protocol):
    """Единый контракт стадии конвейера."""

    @property
    def stage_name(self) -> str:
        """Имя стадии для диагностики и логирования."""
        ...

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        """Обработать поток записей."""
        ...
```

**Ключевые решения**:

- `run(source) → stream` — **единственный** метод контракта. Все стадии, включая match и resolve, реализуют этот контракт.
- `ResolveStage` больше не принимает `dataset` через `run()`. `dataset` приходит через Execution Context при создании стадии.
- `MatchProcessor` и `ResolveProcessor` остаются как **internal engine protocols** — они описывают контракт движка, а не стадии. Stage-обёртка адаптирует engine к `StageContract`.
- Batching объявляется через контрактное свойство, а не через monkey-patch:

```python
class BatchableStage(StageContract, Protocol):
    """Стадия, требующая буферизации входного потока."""

    @property
    def batch_config(self) -> BatchConfig | None:
        """Конфигурация батчинга. None — стадия не требует батчинга."""
        ...

@dataclass(frozen=True)
class BatchConfig:
    batch_size: int = 1000
    key: Callable | None = None
```

### Компонент 2: Stage Execution Context

**Проблема**: Нет единого объекта, передаваемого стадии. Каждая стадия собирает зависимости по-своему. Нет scoping (все capabilities доступны всем). Метаданные pipeline (run_id, dataset) прокидываются ad-hoc.

**Решение**: `StageExecutionContext` — объект, scoped к конкретной стадии.

```python
@dataclass(frozen=True)
class PipelineMetadata:
    """Метаданные запуска pipeline (иммутабельные, общие для всех стадий)."""
    run_id: str
    dataset_name: str
    catalog: ErrorCatalog
    sink_spec: SinkSpec | None = None

class StageExecutionContext:
    """
    Scoped execution context для одной стадии.

    Содержит метаданные pipeline + только те capabilities,
    которые разрешены данной стадии (pay-for-what-you-use).
    """

    def __init__(
        self,
        metadata: PipelineMetadata,
        capabilities: dict[type, object],
    ) -> None:
        self._metadata = metadata
        self._capabilities = capabilities

    @property
    def metadata(self) -> PipelineMetadata:
        return self._metadata

    def require(self, port_type: type[T]) -> T:
        """
        Получить capability или raise MissingCapabilityError.
        Используется provider-функциями, для которых capability обязательна.
        """
        instance = self._capabilities.get(port_type)
        if instance is None:
            raise MissingCapabilityError(
                port_type=port_type,
                available=list(self._capabilities.keys()),
            )
        return instance  # type: ignore[return-value]

    def get(self, port_type: type[T]) -> T | None:
        """Получить capability или None (мягкий доступ)."""
        return self._capabilities.get(port_type)  # type: ignore[return-value]

    def has(self, port_type: type) -> bool:
        return port_type in self._capabilities
```

**Кто что получает** (scoping):

| Стадия | Capabilities в контексте |
|--------|------------------------|
| Map | — (только metadata) |
| Normalize | — (только metadata) |
| Enrich | `EnrichLookupPort`, `DictionaryProviderPort`, `SecretStoreProtocol` (только не-None) |
| Match | `PlanningRuntimePort` |
| Resolve | `PlanningRuntimePort`, `ResolverSettings` |

**Поглощение DEC-002**: `StageExecutionContext` — это эволюция `TransformContext` из DEC-002. Разница:
- `TransformContext` был только для enrich deps. `StageExecutionContext` — для всех стадий.
- `TransformContext` не содержал метаданных pipeline. `StageExecutionContext` содержит `PipelineMetadata`.
- API совместим: `require(PortType)`, `get(PortType)`, `has(PortType)`.

### Компонент 3: Stage Factory

**Проблема**: `DatasetSpec` — god-protocol с 15+ методами. Смешивает DSL-загрузку, dependency assembly, stage construction, I/O adapters. `build_*_stage()` делает I/O внутри domain.

**Решение**: Разделение ответственностей `DatasetSpec` на 3 чистые роли:

```
DatasetSpec (Protocol)          ← сужается: только DSL-конфигурация
    build_map_spec() → MappingSpec
    build_normalize_spec() → NormalizeSpec
    build_enrich_spec() → EnrichSpec
    build_match_spec() → MatchSpec
    build_resolve_spec() → ResolveSpec
    build_sink_spec() → SinkSpec
    build_record_source() → Iterable[SourceRecord]

StageFactory                    ← НОВЫЙ: собирает стадию из spec + context
    create(stage_type, spec, context) → StageContract

PipelineContainer (DI)          ← НОВЫЙ: wiring + capability scoping
    map_stage = Factory(...)
    enrich_stage = Factory(...)
    ...
```

**`StageFactory`** — generic factory на основе **Registry Pattern**, создающая стадию из DSL-спецификации и execution context. Вместо hardcoded методов `create_map_stage()`, `create_enrich_stage()`, ... используется реестр типов стадий.

#### Stage Descriptor

Каждая стадия описывает себя через метаданные:

```python
@dataclass(frozen=True)
class StageDescriptor:
    """
    Метаданные стадии для регистрации в StageFactory.

    stage_type: уникальный идентификатор типа стадии (e.g. "map", "enrich", "resolve")
    engine_factory: функция (spec, context, **kwargs) → Engine
    stage_wrapper: функция (engine, context) → StageContract
    required_capabilities: порты, которые стадия требует через context.require()
    """
    stage_type: str
    engine_factory: Callable[..., object]
    stage_wrapper: Callable[[object, StageExecutionContext], StageContract]
    required_capabilities: frozenset[type] = frozenset()
```

#### Stage Registry + Generic Factory

```python
class StageFactory:
    """
    Registry-based factory для создания стадий pipeline.

    Ответственность: хранит реестр type → descriptor, создаёт стадию
    из DSL-spec и execution context через единый метод create().
    НЕ делает I/O (build_options приходят снаружи).
    """

    def __init__(self) -> None:
        self._registry: dict[str, StageDescriptor] = {}

    def register(self, descriptor: StageDescriptor) -> None:
        """Зарегистрировать тип стадии."""
        if descriptor.stage_type in self._registry:
            raise ValueError(f"Stage type already registered: {descriptor.stage_type}")
        self._registry[descriptor.stage_type] = descriptor

    def create(
        self,
        stage_type: str,
        spec: object,
        context: StageExecutionContext,
        **kwargs,
    ) -> StageContract:
        """
        Создать стадию по типу.

        Единый метод вместо create_map_stage(), create_enrich_stage(), ...
        Open/Closed: новая стадия = новый descriptor + register(), factory не меняется.

        Fail-fast: проверяет required_capabilities из descriptor ДО создания engine.
        """
        descriptor = self._registry.get(stage_type)
        if descriptor is None:
            raise ValueError(
                f"Unknown stage type: {stage_type}. "
                f"Registered: {list(self._registry.keys())}"
            )
        # Fail-fast: проверяем capabilities ДО создания engine
        for cap in descriptor.required_capabilities:
            if not context.has(cap):
                raise MissingCapabilityError(
                    port_type=cap,
                    available=list(context._capabilities.keys()),
                )
        engine = descriptor.engine_factory(spec, context, **kwargs)
        return descriptor.stage_wrapper(engine, context)
```

#### Регистрация стадий

Регистрация происходит при создании `StageFactory` в `PipelineContainer` (delivery layer, не domain):

```python
def _build_stage_factory() -> StageFactory:
    factory = StageFactory()
    factory.register(StageDescriptor(
        stage_type="map",
        engine_factory=lambda spec, ctx, **kw: MapperEngine(
            spec, catalog=ctx.metadata.catalog,
            sink_spec=ctx.metadata.sink_spec, options=kw.get("options"),
        ),
        stage_wrapper=lambda engine, ctx: MapStage(engine, ctx),
        required_capabilities=frozenset(),
    ))
    factory.register(StageDescriptor(
        stage_type="enrich",
        engine_factory=lambda spec, ctx, **kw: EnricherEngine(
            spec=spec, context=ctx,
            dataset=ctx.metadata.dataset_name,
            catalog=ctx.metadata.catalog,
            sink_spec=ctx.metadata.sink_spec,
            options=kw.get("options"),
            providers=kw.get("gateway"),
        ),
        stage_wrapper=lambda engine, ctx: EnrichStage(engine, ctx),
        required_capabilities=frozenset({EnrichLookupPort}),
    ))
    # Аналогично для normalize, match, resolve
    return factory
```

В `PipelineContainer`:

```python
stage_factory = providers.Singleton(_build_stage_factory)
```

**Выигрыши Registry Pattern vs hardcoded методы**:
- **Open/Closed**: новая стадия = `factory.register(descriptor)`. `StageFactory` не модифицируется
- **Нет God Class**: `StageFactory` не растёт с каждой новой стадией — он фиксирован
- **Fail-fast**: `create()` проверяет `required_capabilities` из descriptor ДО создания engine. Ошибка capability scoping обнаруживается при сборке стадии (wiring time), а не при обработке данных
- **Introspection**: `factory._registry` позволяет узнать все зарегистрированные стадии, их capabilities, строить pipeline динамически
- **Тестируемость**: тест может зарегистрировать mock-стадию без monkey-patching factory

#### Двухуровневая защита capabilities

| Уровень | Когда | Что проверяет | Механизм |
|---------|-------|---------------|----------|
| `StageFactory.create()` | При сборке стадии (wiring time) | `required_capabilities` из descriptor | `context.has(cap)` → `MissingCapabilityError` |
| `context.require()` | При выполнении (runtime) | Динамические запросы engine | `require(PortType)` → `MissingCapabilityError` |

Первый уровень — **статически декларированные** capabilities (descriptor). Второй — **динамические** запросы engine (например, условный доступ к `SecretStoreProtocol` только если в spec есть secret-поля). Оба уровня бросают одну ошибку (`MissingCapabilityError`), но в разное время.

#### Registry vs Instances (lifetime)

| Компонент | Lifetime | Что хранит |
|-----------|----------|------------|
| `StageFactory` | **Singleton** (один на контейнер) | Реестр типов: `stage_type → StageDescriptor`. Статичен — код приложения не меняется от датасета к датасету |
| `create()` результат | **Transient** (новый при каждом вызове) | Экземпляр стадии с конкретным spec и context. Уникален для каждого датасета и запуска |

Per-dataset различия обеспечиваются разными `spec` и `context` (через `providers.Dependency`), а не разными registry. Ограничение: если понадобится **другой engine class** для разных датасетов (не другой spec) — потребуется conditional descriptor или отдельный `stage_type`.

#### Компромисс: string-keyed kwargs

`**kwargs` в `create()` и `kw.get("gateway")` в descriptor — string-keyed bag без статической проверки. IDE не подскажет, mypy не проверит. Контракт между `PipelineContainer` (вызов `f.create("enrich", ..., gateway=gw)`) и descriptor (`kw.get("gateway")`) — неявный.

На 5 стадиях управляемо. Если станет проблемой — можно ввести per-stage `BuildParams` dataclass вместо `**kwargs`. Фиксируем как known limitation.

**Ключевые решения**:
- `StageFactory` **не делает I/O**: `build_options` приходят снаружи (из DI-контейнера или loader).
- `DatasetSpec` сужается до чистого DSL-конфигуратора (без `build_*_stage()`).
- `build_enrich_deps()` и `build_planning_deps()` уходят из `DatasetSpec` — scoping capabilities делается в `PipelineContainer`.
- Регистрация дескрипторов — ответственность delivery layer (`_build_stage_factory()`), не domain.
- `required_capabilities` — enforcement, не documentation. Factory проверяет их в `create()` до создания engine.

### Компонент 4: Pipeline Orchestrator

**Проблема**: `StagePipeline` — наивный chain для 3 стадий. Оркестрация match/resolve размазана по command handlers. Нет lifecycle hooks, error recovery.

**Решение**: `PipelineOrchestrator` — управляет полным потоком:

```python
class PipelineOrchestrator:
    """
    Управляет выполнением цепочки стадий от source до target.

    Ответственности:
    - Принимает упорядоченный список стадий
    - Передаёт данные из стадии в стадию
    - Поддерживает batching для стадий с BatchConfig
    - Предоставляет lifecycle hooks (before/after stage)
    """

    def __init__(
        self,
        stages: Sequence[StageContract],
        *,
        hooks: PipelineHooks | None = None,
    ) -> None:
        self._stages = stages
        self._hooks = hooks or PipelineHooks()

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        current = source
        for stage in self._stages:
            if self._hooks.before_stage:
                self._hooks.before_stage(stage.stage_name)
            current = self._execute_stage(stage, current)
            if self._hooks.after_stage:
                self._hooks.after_stage(stage.stage_name)
        return current

    def _execute_stage(
        self,
        stage: StageContract,
        source: Iterable[TransformResult],
    ) -> Iterable[TransformResult]:
        batch_config = getattr(stage, "batch_config", None)
        if batch_config is not None:
            return self._run_batched(stage, source, batch_config)
        return stage.run(source)

@dataclass
class PipelineHooks:
    """Lifecycle hooks для observability."""
    before_stage: Callable[[str], None] | None = None
    after_stage: Callable[[str], None] | None = None
```

**Ключевые решения**:
- Orchestrator работает с **полным** pipeline (все 5 стадий), а не только с map/normalize/enrich.
- Команда решает, какие стадии включить: `normalize` → `[map, normalize]`, `resolve` → `[map, normalize, enrich, match, resolve]`.
- `PipelineHooks` — minimal viable observability. Расширяется по мере необходимости (telemetry, structured logging).

### Граница: UseCase layer остаётся

`MatchUseCase`, `ResolveUseCase`, `NormalizeUseCase`, `EnrichUseCase` **не поглощаются** Orchestrator-ом. Они содержат command-specific concerns:

- **Report building** (presentation): `PlanningResultProcessor`, `report.add_item()`, `report.add_op()`
- **Micro-batching с flush policy** (execution policy): `iter_micro_batches(batch_size, flush_interval_ms)`
- **Специфическая бизнес-логика**: `drain_expired()`, `_purge_pending()`, `_resolve_transaction()`

**Разделение ответственностей**:

| Компонент | Ответственность |
|-----------|----------------|
| `PipelineOrchestrator` | Поток данных между стадиями (generic pipeline chaining, batching, hooks) |
| `UseCase` (match/resolve/...) | Command-specific orchestration: reporting, flush policy, transactions, error counting |
| `Command handler` | Wiring: выбирает стадии из `PipelineContainer`, передаёт в orchestrator или use-case |

**Пример потока для resolve-команды:**

```
Command Handler
  ├── PipelineOrchestrator([map, normalize, enrich])  ← generic pipeline
  │     └── stream of enriched rows
  ├── MatchUseCase(enriched_stream, match_stage)       ← match-specific
  │     └── stream of matched rows (с micro-batching, scope binding)
  └── ResolveUseCase(matched_stream, resolve_stage)    ← resolve-specific
        └── resolved rows (с transactions, drain_expired, purge_pending)
```

Orchestrator управляет потоком данных. UseCase управляет поведением команды. Они не конкурируют — они работают на разных уровнях.

### ProviderGateway как DI-managed компонент

Сейчас `ProviderGateway.with_defaults()` hardcoded в `EnricherEngine.__init__()`. В новой архитектуре `ProviderGateway` становится DI-managed Singleton:

```python
# В PipelineContainer:
provider_gateway = providers.Singleton(ProviderGateway.with_defaults)
```

`StageFactory.create_enrich_stage()` получает `gateway` как параметр:

```python
def create_enrich_stage(self, spec, context, options=None, *, gateway):
    engine = EnricherEngine(
        spec=spec,
        context=context,
        providers=gateway,         # ← из DI, не hardcoded
        ...
    )
    return EnrichStage(engine, context)
```

**Выигрыши**:
- Тест может зарегистрировать mock-provider или кастомный lookup
- Dataset-specific spec может добавить custom providers через DI override
- `ProviderGateway` создаётся один раз (Singleton), переиспользуется между стадиями

### Архитектурные решения по lifecycle и orchestration

#### Решение A: Match lifecycle остаётся в UseCase

`open_match_runtime()` и `MatchRuntime` **остаются** в `usecases/planning_match_runtime.py`. Не переносятся ни в Orchestrator, ни в PipelineContainer.

**Обоснование**: match lifecycle — это command-specific orchestration, а не generic pipeline concern:

- `reset_source_dedup()` — побочный эффект, зависящий от конкретного запуска (run scope)
- `bind_runtime_scope()` — привязка к `run:{run_id}`, уникальному для каждого CLI-вызова
- `clear_runtime_scope()` — cleanup в `finally` блоке, гарантирующий очистку при ошибке
- Micro-batching с `flush_interval_ms` — execution policy, а не pipeline routing

**Где что живёт**:

| Компонент | Ответственность |
|-----------|----------------|
| `PipelineContainer.match_stage` | Создание `MatchStage` из spec + context (DI wiring) |
| `MatchUseCase` | Micro-batching, dedup reset, scope binding, report processing |
| `open_match_runtime()` | Setup/cleanup runtime scope (`clear_runtime_scope` в `finally`) |
| `PipelineOrchestrator` | НЕ знает о match lifecycle — просто вызывает `stage.run()` |

**Пример потока для match-команды:**

```
Command Handler
  ├── pipeline.match_stage()                      ← из PipelineContainer
  ├── open_match_runtime(match_stage, ...)         ← lifecycle context manager
  │     ├── reset_source_dedup()
  │     ├── bind_runtime_scope("run:{run_id}")
  │     └── finally: clear_runtime_scope()
  └── MatchUseCase.run(enriched, match_stage)      ← micro-batching + reporting
```

#### Решение B: ResolveStage — dataset через context, buffering в UseCase

Два аспекта текущего `ResolveStage`:

**1. `dataset` kwarg в `run()` → переносится в `StageExecutionContext`**

Сейчас `ResolveStage.run(batch, dataset=dataset)` нарушает `StageContract`. В новой архитектуре `dataset` приходит через `context.metadata.dataset_name` при создании стадии. `ResolveStage.run(source)` соответствует единому контракту.

```python
# Было:
for resolved in resolve_stage.run(batch, dataset=dataset):  # ← extra kwarg

# Стало:
# dataset_name уже в context.metadata при создании стадии
for resolved in resolve_stage.run(batch):  # ← StageContract
```

**2. Buffering + transactions → остаются в `ResolveUseCase`**

`_resolve_transaction()` оборачивает каждый micro-batch в DB-транзакцию. `_purge_pending()` и `drain_expired()` — domain-специфичные побочные эффекты. Это command-specific orchestration, а не generic pipeline concern.

| Аспект | Текущее место | Целевое место | Обоснование |
|--------|--------------|---------------|-------------|
| `dataset` kwarg | `ResolveStage.run()` | `StageExecutionContext.metadata` | Единый контракт `StageContract` |
| `_resolve_transaction()` | `ResolveUseCase` | `ResolveUseCase` (без изменений) | Command-specific DB concern |
| `_purge_pending()` | `ResolveUseCase` | `ResolveUseCase` (без изменений) | Domain-specific cleanup |
| `drain_expired()` | `ResolveUseCase` | `ResolveUseCase` (без изменений) | Domain-specific lifecycle |
| Micro-batching | `ResolveUseCase` | `ResolveUseCase` (без изменений) | Execution policy с flush_interval |

#### Решение C: import-plan использует PipelineContainer для стадий

`import_plan` — самая сложная команда: vault rollout, все 5 стадий, собственная orchestration через `ImportPlanService`. В новой архитектуре:

**Что меняется**:
- `import_plan` handler получает стадии из `PipelineContainer` вместо ручной сборки
- `PipelineContainer` обеспечивает lazy resolution: vault-зависимые capabilities материализуются только если `secret_store` передан
- Vault rollout policy **остаётся в command handler** (delivery concern, не pipeline concern)

**Что НЕ меняется**:
- `ImportPlanService` сохраняет свою orchestration логику (это use-case, не pipeline)
- Vault mode detection и rollout evaluation — в command handler

**Пример потока:**

```
import_plan handler (delivery)
  ├── resolve_vault_runtime_mode()           ← delivery: vault policy
  ├── evaluate_vault_rollout()               ← delivery: rollout gate
  ├── ctx.container.pipeline                 ← PipelineContainer
  │     ├── .row_source()                    ← lazy
  │     ├── .transform_pipeline()            ← [map, normalize, enrich] lazy
  │     ├── .match_stage()                   ← lazy
  │     └── .resolve_stage()                 ← lazy
  └── ImportPlanService.run(                 ← use-case orchestration
        stages, cache_roles, settings, ...
      )
```

**Ключевое ограничение**: `PipelineContainer` не знает о vault rollout policy. Решение vault mode → передача `secret_store` в контейнер — это ответственность command handler.

### Компонент 5: PipelineContainer (DI wiring)

**Поглощение DEC-003**: `PipelineContainer` — это эволюция контейнера из DEC-003, дополненная `StageFactory`, `StageExecutionContext` и полным pipeline.

```python
class PipelineContainer(containers.DeclarativeContainer):
    """
    Субконтейнер для transform pipeline (часть AppContainer).

    Lazy resolution: команда запрашивает только нужные стадии.
    Capability scoping: каждая стадия получает только свои зависимости.
    """
    # ── Внешние зависимости ──────────────────────────────────────────
    dataset_spec    = providers.Dependency(instance_of=DatasetSpec)
    app_settings    = providers.Dependency(instance_of=AppSettings)
    cache_roles     = providers.Dependency(instance_of=SqliteCacheRolePorts)
    catalog         = providers.Dependency(instance_of=ErrorCatalog)
    csv_has_header  = providers.Dependency(instance_of=bool)
    run_id          = providers.Dependency(instance_of=str)

    # Опциональные capabilities (не все команды их передают)
    secret_store  = providers.Dependency(instance_of=object)   # SecretStoreProtocol | None
    dictionaries  = providers.Dependency(instance_of=object)   # DictionaryProviderPort | None

    # ── Pipeline metadata ────────────────────────────────────────────
    sink_spec = providers.Factory(
        lambda spec: spec.build_sink_spec(),
        spec=dataset_spec,
    )
    pipeline_metadata = providers.Factory(
        PipelineMetadata,
        run_id=run_id,
        dataset_name=providers.Factory(lambda spec: spec.dataset_name, spec=dataset_spec),
        catalog=catalog,
        sink_spec=sink_spec,
    )

    # ── Build options (загрузка из registry — I/O на границе wiring) ─
    map_options       = providers.Factory(_load_map_options, spec=dataset_spec)
    normalize_options = providers.Factory(_load_normalize_options, spec=dataset_spec)
    enrich_options    = providers.Factory(_load_enrich_options, spec=dataset_spec)
    match_options     = providers.Factory(_load_match_options, spec=dataset_spec)
    resolve_options   = providers.Factory(_load_resolve_options, spec=dataset_spec)

    # ── Scoped execution contexts ────────────────────────────────────
    transform_context = providers.Factory(
        _build_transform_context,
        metadata=pipeline_metadata,
    )
    enrich_context = providers.Factory(
        _build_enrich_context,
        metadata=pipeline_metadata,
        cache_roles=cache_roles,
        secret_store=secret_store,
        dictionaries=dictionaries,
    )
    planning_context = providers.Factory(
        _build_planning_context,
        metadata=pipeline_metadata,
        cache_roles=cache_roles,
        settings=providers.Factory(lambda s: s.resolver, s=app_settings),
    )

    # ── Stage factory (registry-based) + provider gateway ────────────
    provider_gateway = providers.Singleton(ProviderGateway.with_defaults)
    stage_factory = providers.Singleton(_build_stage_factory)

    # ── Transform stages (resolver_settings не участвует) ────────────
    row_source = providers.Factory(
        lambda spec, h: spec.build_record_source(csv_has_header=h),
        spec=dataset_spec, h=csv_has_header,
    )
    map_stage = providers.Factory(
        lambda f, spec, ctx, opts: f.create("map", spec.build_map_spec(), ctx, options=opts),
        f=stage_factory, spec=dataset_spec,
        ctx=transform_context, opts=map_options,
    )
    normalize_stage = providers.Factory(
        lambda f, spec, ctx, opts: f.create("normalize", spec.build_normalize_spec(), ctx, options=opts),
        f=stage_factory, spec=dataset_spec,
        ctx=transform_context, opts=normalize_options,
    )
    enrich_stage = providers.Factory(
        lambda f, spec, ctx, opts, gw: f.create("enrich", spec.build_enrich_spec(), ctx, options=opts, gateway=gw),
        f=stage_factory, spec=dataset_spec,
        ctx=enrich_context, opts=enrich_options,
        gw=provider_gateway,
    )

    # ── Planning stages (resolver_settings резолвится только здесь) ──
    match_stage = providers.Factory(
        lambda f, spec, ctx, opts: f.create("match", spec.build_match_spec(), ctx, options=opts),
        f=stage_factory, spec=dataset_spec,
        ctx=planning_context, opts=match_options,
    )
    resolve_stage = providers.Factory(
        lambda f, spec, ctx, opts: f.create("resolve", spec.build_resolve_spec(), ctx, options=opts),
        f=stage_factory, spec=dataset_spec,
        ctx=planning_context, opts=resolve_options,
    )

    # ── Orchestrator (создаётся с нужным набором стадий) ─────────────
    transform_pipeline = providers.Factory(
        PipelineOrchestrator,
        stages=providers.List(map_stage, normalize_stage, enrich_stage),
    )
    full_pipeline = providers.Factory(
        PipelineOrchestrator,
        stages=providers.List(
            map_stage, normalize_stage, enrich_stage,
            match_stage, resolve_stage,
        ),
    )
```

**Как меняется command handler (normalize):**

```python
# было (normalize.py)
pipeline_ctx = build_pipeline_context(
    dataset_spec=dataset_spec,
    resolver_settings=app_settings.resolver,   # ← не нужен
    observability_settings=app_settings.observability,
    ...
)
usecase.run(
    map_stage=pipeline_ctx.map_stage,
    normalize_stage=pipeline_ctx.normalize_stage,
)

# стало
pipeline = ctx.container.pipeline  # PipelineContainer из AppContainer
row_source = pipeline.row_source()
orchestrator = PipelineOrchestrator(
    stages=[pipeline.map_stage(), pipeline.normalize_stage()]
)
# resolver_settings не материализуется, planning_deps не строится
```

### Поток данных (полный pipeline)

```
CLI Command
  └── AppContainer.pipeline (PipelineContainer)
        ├── dataset_spec.build_*_spec()       → DSL Spec
        ├── _load_*_options()                 → BuildOptions  (I/O здесь, на границе)
        ├── _build_*_context(metadata, caps)  → StageExecutionContext (scoped)
        ├── StageFactory.create_*(spec, ctx)  → StageContract
        └── PipelineOrchestrator([stages])    → run(source) → stream
              ├── MapStage.run(source)
              ├── NormalizeStage.run(stream)
              ├── EnrichStage.run(stream)      ← ctx.require(EnrichLookupPort)
              ├── MatchStage.run(stream)        ← ctx.require(PlanningRuntimePort)
              └── ResolveStage.run(stream)      ← ctx.require(ResolverSettings)
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **Единый контракт**: все 5 стадий реализуют `StageContract.run()` — pipeline покрывает весь поток от source до resolved
- ✅ **Scoped context**: каждая стадия получает только свои capabilities. Map не видит vault. Normalize не видит cache. Enrich не видит resolver_settings
- ✅ **Pay-for-what-you-use**: команда normalize запрашивает только `map_stage` + `normalize_stage`. Planning deps, resolver_settings, match/resolve stages не материализуются
- ✅ **Single source of truth**: `resolver_settings` существует в одном месте — `planning_context`. Нет дублирования путей
- ✅ **Open/closed для capabilities**: новая capability = новый provider в контейнере + передача в нужный context builder. Остальные команды не меняются
- ✅ **Open/closed для стадий**: новая стадия = новый `create_*` в `StageFactory` + provider в контейнере. `DatasetSpec` не меняется (только `build_new_spec()`)
- ✅ **Чистые hexagonal boundaries**: I/O (загрузка build_options, чтение YAML) — на границе wiring (в `PipelineContainer` providers), не в domain
- ✅ **Testability**: тест стадии создаёт `StageExecutionContext` с нужными mock-capabilities. Тест pipeline overrides только нужные providers в контейнере
- ✅ **Lifecycle hooks**: `PipelineHooks` — точка для observability, structured logging, telemetry
- ✅ **Поглощает DEC-002 и DEC-003**: оба частных решения становятся частью единой модели

**Недостатки (компромиссы)**:
- ⚠️ Значительный scope рефактора: все 5 стадий, `DatasetSpec`, `EmployeesSpec`, все command handlers, тесты. **Митигация**: поэтапная реализация (см. план ниже)
- ⚠️ `ctx.require(PortType)` слабее IDE autocomplete чем прямой атрибут. **Митигация**: `PipelineMetadata` для частых полей (`catalog`, `dataset_name`) доступен через прямой атрибут; `require()` только для capabilities
- ⚠️ Новая абстракция (`StageExecutionContext`, `StageFactory`, `PipelineOrchestrator`). **Митигация**: каждая абстракция решает конкретную проблему и заменяет ad-hoc код

**Альтернативы, которые отклонили**:
- ❌ **DEC-002 + DEC-003 по отдельности**: решают 2 из 7 разрывов; не дают целостной модели; создают промежуточное несогласованное состояние
- ❌ **Per-command фабрики**: дублирование wiring; нет единого pipeline; невозможно гарантировать консистентность

---

## 🛠️ Реализация (поэтапный план)

### Этап 1: Stage Contract + Batching Contract

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform/stages/stages.py` | Добавить `StageContract`, `BatchConfig`, `BatchableStage`. `MapStage`, `NormalizeStage`, `EnrichStage`, `MatchStage` реализуют `StageContract`. `ResolveStage.run()` — убрать `dataset` kwarg |
| `connector/domain/transform/stages/stages.py` | `StagePipeline` → `PipelineOrchestrator` с поддержкой `BatchConfig` |
| Тесты | Проверить, что все 5 стадий реализуют `StageContract` |

### Этап 2: PipelineMetadata + StageExecutionContext

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform/context.py` | Создать `PipelineMetadata`, `StageExecutionContext`, `MissingCapabilityError` |
| `connector/domain/transform/providers/deps.py` | `TransformProviderDeps` помечается deprecated (alias на переходный период) |
| `connector/domain/transform/resolver/resolve_deps.py` | `PlanningDependencies` помечается deprecated |
| Engine-классы | `EnricherEngine`, `MatchEngine`, `ResolveEngine` принимают `StageExecutionContext` вместо разрозненных deps |
| Тесты | Тесты context: `require()`, `get()`, scoping |

### Этап 3: StageFactory (Registry Pattern) + сужение DatasetSpec

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform/factory.py` | Создать `StageDescriptor`, `StageFactory` (registry-based: `register()` + `create()`) |
| `connector/delivery/cli/pipeline_registry.py` | Создать `_build_stage_factory()` — регистрация дескрипторов всех 5 стадий (delivery layer) |
| `connector/datasets/spec.py` | Убрать `build_*_stage()`, `build_enrich_deps()`, `build_planning_deps()`, `build_transform_stages()`, `build_planning_stages()` |
| `connector/datasets/employees/spec.py` | Убрать реализации удалённых методов |
| Тесты | Тесты factory: `register()`, `create()`, unknown type error, duplicate registration error |

### Этап 4: PipelineContainer + миграция command handlers

| Файл | Изменение |
|------|-----------|
| `connector/delivery/cli/containers.py` | Создать `PipelineContainer`. Удалить `build_pipeline_context()`, `PipelineContext` |
| `connector/delivery/cli/containers.py` | `AppContainer` — добавить `pipeline = providers.Container(PipelineContainer, ...)` |
| `connector/delivery/commands/normalize.py` | Использовать `PipelineContainer`: запросить только `map_stage`, `normalize_stage` |
| `connector/delivery/commands/enrich.py` | Использовать `PipelineContainer` |
| `connector/delivery/commands/match.py` | Использовать `PipelineContainer`; один путь для `resolver_settings` |
| `connector/delivery/commands/resolve.py` | Использовать `PipelineContainer` |
| `connector/delivery/commands/mapping.py` | Использовать `PipelineContainer` |
| `connector/delivery/commands/import_plan.py` | Использовать `PipelineContainer` |
| Тесты | Integration-тесты: каждая команда запрашивает только свои providers |

### Этап 5: Cleanup

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform/providers/deps.py` | Удалить `TransformProviderDeps` |
| `connector/domain/transform/resolver/resolve_deps.py` | Удалить `PlanningDependencies` |
| `connector/domain/transform/stages/stages.py` | Удалить legacy `StagePipeline`, `@batched()` decorator |

### Инварианты

1. **`StageContract.run()`** — единственный метод вызова стадии извне. Никаких extra kwargs.
2. **`StageExecutionContext`** — иммутабельный: создаётся один раз при сборке стадии, не модифицируется в runtime.
3. **Capability scoping**: стадия видит только те capabilities, которые явно переданы в её context.
4. **`PipelineContainer`** — один экземпляр на вызов CLI-команды. Не переиспользуется между вызовами.
5. **`StageFactory`** — registry-based: единый метод `create(stage_type, spec, context)`. Не содержит hardcoded `create_*()` методов. Не делает I/O.
6. **`StageFactory` registration** — ответственность delivery layer (`_build_stage_factory()`). Domain определяет `StageDescriptor` и `StageFactory`, delivery регистрирует конкретные стадии.
7. **`DatasetSpec`** не содержит `build_*_stage()` методов: только DSL-spec builders.
8. **`resolver_settings`** существует только в `planning_context`. Не материализуется в transform-стадиях.

---

## 🧪 Валидация решения

**Тесты**:
- ✅ `test_all_stages_implement_stage_contract()` — все 5 стадий проходят structural check
- ✅ `test_resolve_stage_run_no_extra_kwargs()` — `ResolveStage.run(source)` без `dataset`
- ✅ `test_enrich_context_scoping()` — enrich context содержит cache+dict+secrets; не содержит PlanningRuntimePort
- ✅ `test_planning_context_scoping()` — planning context содержит PlanningRuntimePort+ResolverSettings; не содержит DictionaryProviderPort
- ✅ `test_normalize_does_not_materialize_planning()` — при запросе `normalize_stage()` из контейнера, `planning_context` не создаётся
- ✅ `test_single_resolver_settings_path_in_match()` — resolver_settings приходит в match ровно одним путём
- ✅ `test_stage_factory_no_io()` — `StageFactory.create()` не обращается к файловой системе
- ✅ `test_stage_factory_unknown_type()` — `factory.create("unknown", ...)` raises `ValueError`
- ✅ `test_stage_factory_duplicate_registration()` — повторный `register()` того же типа raises `ValueError`
- ✅ `test_stage_factory_fail_fast_missing_capability()` — `create("enrich", ..., context_without_cache)` raises `MissingCapabilityError` до создания engine
- ✅ `test_pipeline_orchestrator_full_chain()` — все 5 стадий в одном pipeline
- ✅ `test_pipeline_hooks_called()` — before/after stage hooks вызываются

**Метрики успеха**:
- Количество файлов, затрагиваемых при добавлении новой capability: **≤ 2** (context builder + container provider) вместо текущих 5+
- Количество файлов, затрагиваемых при добавлении новой стадии: **≤ 3** (stage class + factory method + container provider) вместо текущих 5+
- `resolver_settings` в коде `normalize.py`, `enrich.py`, `mapping.py`: **0 упоминаний**

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- `ctx.require(PortType)` не проверяется статически mypy без overload-стабов — динамические запросы engine обнаруживаются в runtime (статически декларированные capabilities проверяются раньше — при `create()`)
- `StageFactory` — registry-based, но регистрация статическая (в `_build_stage_factory()`), не runtime-динамическая. Плагины не подгружаются из внешних пакетов — расширение через код, не через конфигурацию
- `**kwargs` в `StageFactory.create()` — string-keyed bag без статической проверки. Контракт между PipelineContainer и descriptor неявный. На 5 стадиях управляемо; при росте рассмотреть per-stage `BuildParams` dataclass

**Риски**:
- ⚠️ Большой scope рефактора может привести к регрессиям
  - **Митигация**: Поэтапная реализация. Каждый этап — отдельный коммит с зелёными тестами. Переходный период с deprecated aliases
- ⚠️ `StageExecutionContext` может стать новым catch-all (замена `TransformProviderDeps`)
  - **Митигация**: Capability scoping — разные стадии получают разные context builders. Factory methods в контейнере явно определяют, какие capabilities попадают в какой context
- ⚠️ Усложнение mental model: 4 новые абстракции
  - **Митигация**: Каждая абстракция заменяет конкретный ad-hoc код. `StageContract` заменяет 3 протокола. `StageExecutionContext` заменяет 2 deps-контейнера. `StageFactory` заменяет 10 build_* методов. `PipelineOrchestrator` заменяет ad-hoc оркестрацию в 3 command handlers

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `TransformStageProcessor` | Заменяется `StageContract` | Переходный период: оба протокола, затем удаление |
| `TransformProviderDeps` | Заменяется `StageExecutionContext` | Deprecated → удалён |
| `PlanningDependencies` | Заменяется `StageExecutionContext` | Deprecated → удалён |
| `DatasetSpec` | Сужается: только DSL-spec builders | Удаление 10+ методов |
| `EmployeesSpec` | Сужается | Удаление реализаций build_*_stage() |
| `StagePipeline` | Заменяется `PipelineOrchestrator` | Deprecated → удалён |
| `build_pipeline_context()` | Заменяется `PipelineContainer` | Удалён |
| `PipelineContext` dataclass | Удалён | Команды получают stages из контейнера |
| `EnricherEngine` | Принимает `StageExecutionContext` | Конструктор: deps+secret_store+dataset → context |
| `MatchEngine` | Принимает `StageExecutionContext` | Конструктор: cache_gateway → context |
| `ResolveEngine` | Принимает `StageExecutionContext` | Конструктор: cache_gateway+settings → context |
| Command handlers (6 файлов) | Используют `PipelineContainer` | Каждый запрашивает только свои providers |
| `AppContainer` | Добавляется `pipeline` субконтейнер | `providers.Container(PipelineContainer, ...)` |
| `@batched()` decorator | Заменяется `BatchConfig` | Удалён |
| `ProviderGateway` | DI-managed Singleton | `with_defaults()` вызывается в `PipelineContainer`, передаётся через `StageFactory.create()` kwargs |
| `MatchUseCase` / `ResolveUseCase` | Остаются без изменений | Command-specific orchestration поверх generic pipeline |
| `open_match_runtime()` | Остаётся | Match lifecycle (scope, cleanup) управляется use-case, не orchestrator |

---

## 🔗 Связанные документы

- [TRANSFORM-PROBLEM-004](./TRANSFORM-PROBLEM-004-missing-modular-pipeline-architecture.md) — решаемая корневая проблема
- [TRANSFORM-PROBLEM-002](./TRANSFORM-PROBLEM-002-transform-provider-deps-coupling.md) — подпроблема (deps coupling)
- [TRANSFORM-PROBLEM-003](./TRANSFORM-PROBLEM-003-monolithic-pipeline-factory-eager-coupling.md) — подпроблема (eager wiring)
- [TRANSFORM-DEC-002](./TRANSFORM-DEC-002-transform-context-capability-registry.md) — поглощённое решение (TransformContext → StageExecutionContext)
- [TRANSFORM-DEC-003](./TRANSFORM-DEC-003-pipeline-container-lazy-stage-assembly.md) — поглощённое решение (PipelineContainer → расширен)
- [DELIVERY-DEC-006](../delivery/DELIVERY-DEC-006-app-container-composition-root-integration.md) — AppContainer как composition root
- `connector/domain/transform/stages/stages.py` — текущие stage protocols
- `connector/datasets/spec.py` — DatasetSpec protocol
- `connector/delivery/cli/containers.py` — PipelineContext, build_pipeline_context()
- `connector/delivery/commands/` — command handlers

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-22 | Gap-анализ выявил 7 архитектурных разрывов; корневая проблема зафиксирована в TRANSFORM-PROBLEM-004 |
| 2026-02-22 | Решение принято: Modular Pipeline with Scoped Execution Context |
| 2026-02-22 | DEC-002 (TransformContext) и DEC-003 (PipelineContainer) поглощены как частные случаи |
| 2026-02-22 | Дополнено: UseCase layer остаётся (command-specific orchestration); ProviderGateway как DI-managed Singleton |
| 2026-02-22 | Зафиксированы 3 архитектурных решения: (A) match lifecycle в UseCase, (B) dataset→context + buffering в UseCase, (C) import-plan через PipelineContainer |
| 2026-02-22 | StageFactory переработан: hardcoded методы → Registry Pattern (StageDescriptor + register/create). Docstring PipelineContainer исправлен (субконтейнер, не CR) |
| 2026-02-22 | Уточнения Registry: fail-fast проверка capabilities в create(), двухуровневая защита (wiring + runtime), Registry=Singleton / Instances=Transient, string-keyed kwargs как known limitation |
