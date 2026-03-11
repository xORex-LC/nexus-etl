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

#### Типобезопасность при сборке: Generic StageContract + typed factory functions

`StageContract` параметризован по входному и выходному типу данных:

```python
class StageContract(Protocol[T_in, T_out]):
    """Единый контракт стадии конвейера."""

    @property
    def stage_name(self) -> str: ...

    def run(self, source: Iterable[T_in]) -> Iterable[T_out]: ...

# Псевдоним для type-erased представления (orchestrator/registry):
AnyStageContract = StageContract[Any, Any]
```

Каждая стадия явно декларирует инвариант:

| Стадия | `T_in` | `T_out` |
|--------|--------|---------|
| `MapStage` | `SourceRecord` | `MappedRecord` |
| `NormalizeStage` | `MappedRecord` | `NormalizedRecord` |
| `EnrichStage` | `NormalizedRecord` | `EnrichedRecord` |
| `MatchStage` | `EnrichedRecord` | `MatchedRecord` |
| `ResolveStage` | `MatchedRecord` | `ResolvedRecord` |

**Typed factory functions вместо fluent builder**. Поскольку pipeline-комбинации фиксированы (5 стадий, ограниченное число CLI-команд), типизацию обеспечивают typed factory functions в delivery layer — без обобщённого builder-класса:

```python
# connector/delivery/cli/pipeline_registry.py
def build_transform_pipeline(
    map_stage: StageContract[SourceRecord, MappedRecord],
    normalize_stage: StageContract[MappedRecord, NormalizedRecord],
    enrich_stage: StageContract[NormalizedRecord, EnrichedRecord],
) -> PipelineOrchestrator:
    """mypy проверяет совместимость типов при сборке."""
    return PipelineOrchestrator([map_stage, normalize_stage, enrich_stage])
```

**Erasure boundary**:

```
StageContract[T_in, T_out]          ← typed (domain contracts + builder)
     ↓ typed factory function проверила совместимость
PipelineOrchestrator([...])          ← type-erased: Sequence[AnyStageContract]
     ↓ runtime
stage.run(source)                    ← duck-typed, TransformResult envelope
```

**Почему не fluent Generic Builder**: Python не имеет HKT — цепочка `Builder[A→B].then(Stage[B→C])` требует сложных recursive generics, плохо поддерживаемых mypy. Typed factory functions дают те же гарантии для нашего фиксированного набора комбинаций без этой сложности.

**`StageDescriptor` и `StageFactory` остаются type-erased**: registry работает со `StageContract[Any, Any]`. Типобезопасность — ответственность builder-функций, не registry.

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

#### Компромисс: DatasetSpec — DSL coupling (Phase 1)

`DatasetSpec` сужается: убраны `build_*_stage()`, `build_enrich_deps()`, `build_planning_deps()`. Однако typed `build_*_spec()` методы **сохраняются** — для каждой стадии протокол декларирует свой метод (`build_map_spec()`, `build_enrich_spec()`, ...).

Следствие: при добавлении новой стадии требуется изменить 2 дополнительных файла сверх `StageDescriptor` + container provider:

1. `DatasetSpec` (протокол) — добавить `build_new_spec() → NewSpec`
2. `EmployeesSpec` (реализация) — реализовать метод

Это осознанный компромисс **на период жизни `EmployeesSpec`**: хардкод под один датасет, от которого планируется уйти. Пока `EmployeesSpec` существует — typed методы поддерживаемы. Когда `EmployeesSpec` заменится на generic YAML-driven реализацию — `DatasetSpec` мигрирует на `build_spec_for(stage_type: str) → object`, что полностью закрывает OCP.

Проблема зафиксирована в [TRANSFORM-PROBLEM-005](./TRANSFORM-PROBLEM-005-dataset-spec-ocp-violation.md), целевое решение — в [TRANSFORM-DEC-005](./TRANSFORM-DEC-005-dataset-spec-generic-accessor-evolution.md).

**Ключевые решения**:
- `StageFactory` **не делает I/O**: `build_options` приходят снаружи (из DI-контейнера или loader).
- `DatasetSpec` сужается до чистого DSL-конфигуратора (без `build_*_stage()`), typed `build_*_spec()` методы сохраняются (Phase 1 компромисс, см. выше).
- `build_enrich_deps()` и `build_planning_deps()` уходят из `DatasetSpec` — scoping capabilities делается в `PipelineContainer`.
- Регистрация дескрипторов — ответственность delivery layer (`_build_stage_factory()`), не domain.
- `required_capabilities` — enforcement, не documentation. Factory проверяет их в `create()` до создания engine.

### Компонент 4: Pipeline Orchestrator

**Проблема**: `StagePipeline` — наивный chain для 3 стадий. Оркестрация match/resolve размазана по command handlers. Нет lifecycle hooks, error recovery.

**Решение**: `PipelineOrchestrator` — управляет полным потоком:

```python
@dataclass
class PipelineHooks:
    """
    Двухуровневые lifecycle hooks для observability.

    assembly hook (eager) — вызывается при сборке цепочки, до потока данных.
    execution hooks (lazy-aware) — вызываются при реальном потреблении потока.
    """
    # ── Assembly hook ─────────────────────────────────────────────────
    on_stage_bind: Callable[[str], None] | None = None
    """Вызывается при регистрации стадии в цепочке (сборка, не выполнение).
    Полезен для audit/trace: "в этом запуске зарегистрированы стадии X, Y, Z"."""

    # ── Execution hooks (lazy-aware) ──────────────────────────────────
    on_stage_start: Callable[[str], None] | None = None
    """Вызывается при первом pull из stage output — реальный старт обработки.
    В lazy chain: срабатывает когда consumer впервые тянет из конца цепочки."""

    on_stage_complete: Callable[[str, float, dict | None], None] | None = None
    """Вызывается при естественном исчерпании stage output (StopIteration).
    Аргументы: stage_name, duration_ms, stats ({"items": N}, опционально)."""

    on_stage_error: Callable[[str, Exception, float], None] | None = None
    """Вызывается если stage бросила исключение при итерации.
    Аргументы: stage_name, exc, duration_ms."""

    on_stage_abort: Callable[[str, float], None] | None = None
    """Вызывается если поток закрыт до полного consumption (GeneratorExit).
    Это не баг — свойство lazy execution. Аргументы: stage_name, duration_ms."""


class PipelineOrchestrator:
    """
    Управляет выполнением цепочки стадий от source до target.

    Ответственности:
    - Принимает упорядоченный список стадий
    - Передаёт данные из стадии в стадию
    - Поддерживает batching для стадий с BatchConfig
    - Предоставляет двухуровневые lifecycle hooks (assembly + execution)
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
            if self._hooks.on_stage_bind:
                self._hooks.on_stage_bind(stage.stage_name)  # eager: assembly time
            current = self._execute_stage(stage, current)
        return current

    def _execute_stage(
        self,
        stage: StageContract,
        source: Iterable[TransformResult],
    ) -> Iterable[TransformResult]:
        batch_config = getattr(stage, "batch_config", None)
        raw = self._run_batched(stage, source, batch_config) if batch_config else stage.run(source)
        return self._monitored(stage, raw)

    def _monitored(
        self,
        stage: StageContract,
        stream: Iterable[TransformResult],
    ) -> Iterator[TransformResult]:
        """
        Monitoring wrapper: превращает eager-вызовы в lazy-aware события.

        on_stage_start срабатывает на первом pull (не при stage.run()).
        on_stage_complete — только при полном consumption.
        on_stage_abort — при GeneratorExit до исчерпания потока.
        """
        start_time: float | None = None
        items_count = 0
        try:
            for item in stream:
                if start_time is None:
                    start_time = time.monotonic()
                    if self._hooks.on_stage_start:
                        self._hooks.on_stage_start(stage.stage_name)
                items_count += 1
                yield item
            if start_time is not None and self._hooks.on_stage_complete:
                ms = (time.monotonic() - start_time) * 1000
                self._hooks.on_stage_complete(stage.stage_name, ms, {"items": items_count})
        except GeneratorExit:
            if start_time is not None and self._hooks.on_stage_abort:
                ms = (time.monotonic() - start_time) * 1000
                self._hooks.on_stage_abort(stage.stage_name, ms)
            raise
        except Exception as exc:
            if start_time is not None and self._hooks.on_stage_error:
                ms = (time.monotonic() - start_time) * 1000
                self._hooks.on_stage_error(stage.stage_name, exc, ms)
            raise
```

**Ключевые решения**:
- Orchestrator работает с **полным** pipeline (все 5 стадий), а не только с map/normalize/enrich.
- Команда решает, какие стадии включить: `normalize` → `[map, normalize]`, `resolve` → `[map, normalize, enrich, match, resolve]`.
- `PipelineHooks` — **двухуровневые**: assembly hook (`on_stage_bind`, eager) + execution hooks (`on_stage_start/complete/error/abort`, lazy-aware).
- `_monitored()` wrapper — единственное место, где execution hooks превращаются из eager-вызовов в lazy-aware события. `PipelineOrchestrator` владеет generic stream execution semantics; `UseCase` не чинит эту семантику.
- `on_stage_complete` гарантированно срабатывает **только** при полном consumption. Частичное потребление (UseCase вышел раньше) → `on_stage_abort`. Это свойство lazy execution, не баг.
- `on_stage_start` в lazy chain: при первом pull с конца цепочки все upstream-генераторы стартуют каскадно. `on_stage_start` для всех стадий срабатывает почти одновременно — это ожидаемое поведение.
- **`start_time` guard**: `on_stage_start`, `on_stage_complete`, `on_stage_abort`, `on_stage_error` **не срабатывают**, если стадия не отдала ни одного элемента (`start_time is None`). Два случая: (1) пустой входной стрим — нормальное завершение без хуков; (2) исключение до первого pull — re-raise без `on_stage_error`. Это осознанная политика: хуки описывают **data-flow events**, а не control-flow события setup-фазы.

### Модель ошибок

`PipelineOrchestrator` работает со стримом данных, в котором возникают три категории сбоев:

| Уровень | Что вызывает | Кто обрабатывает | Дальнейший путь |
|---------|-------------|-----------------|-----------------|
| **Record-level** | Плохие данные, mapping miss, enrich miss, domain-правило по одной записи | Stage → `context.metadata.catalog` | Запись квалифицирована и пропущена; pipeline продолжается — Python exception **не бросается** |
| **Stage-fatal** | Неверная конфигурация, domain violation, invariant stадии | Stage raises → `_monitored()` → `on_stage_error` + re-raise | Pipeline останавливается; UseCase/handler конвертирует в command outcome |
| **Infra-fatal** | I/O failure (DB, network, файл) в стриме | Аналогично stage-fatal на уровне orchestrator | Тип exception (`IOError`, `DBError`) различает категорию выше — в UseCase/handler |

**Ownership chain**:

```
Stage              → ErrorCatalog (record-level — без exception)
_monitored()       → on_stage_error(name, exc, ms) + raise (stage/infra-fatal)
UseCase / handler  → catches, converts to command outcome / exit code / diagnostic
```

**Ключевые инварианты модели**:
- Stage **не должен** бросать Python exception для record-level ошибок — exception означает stage-fatal. Record-level ошибки уходят в `context.metadata.catalog`.
- `PipelineOrchestrator._monitored()` **никогда не подавляет** исключения после вызова `on_stage_error` — всегда re-raises.
- Разграничение stage-fatal vs infra-fatal делается **выше** orchestrator — по типу exception в UseCase/handler. На уровне pipeline оба пути идентичны.

### Lifecycle стадий

`StageContract` не включает `close()` или `__exit__` — cleanup обеспечивается Python-протоколом генераторов без дополнительного контракта.

**Три уровня владения ресурсами**:

| Уровень | Пример | Где живёт | Cleanup |
|---------|--------|-----------|---------|
| **Per-record** | DB cursor, транзакция на запись | Локальная переменная внутри итерации генератора | `try/finally` внутри цикла |
| **Per-run** | Буфер батча, connection lease | Локальная переменная генератора (до первого `yield`) | `try/finally` генератора; `GeneratorExit` гарантированно триггерит `finally` |
| **Long-lived** | DB engine, HTTP client, кэш | DI container (`PipelineContainer`) | `AppContainer.shutdown_resources()` |

**Ключевое правило**: Long-lived ресурсы **не принадлежат** стадиям. Они инъецируются через `StageExecutionContext` и управляются DI-контейнером. Стадии — **stateless functors**: нет состояния на уровне instance между вызовами `run()`.

**Generator cleanup chain**: `GeneratorExit` при partial consumption каскадно проходит через весь generator chain — от consumer-итератора через `_monitored()` до исходного генератора стадии. Каждый `try/finally` в цепочке гарантированно выполняется.

**UseCase — владелец cleanup-гарантии**: UseCase является конечным потребителем pipeline iterator и **отвечает** за корректное закрытие итератора. Паттерны:

```python
# Полное consumption — natural close (GeneratorExit не нужен)
for item in orchestrator.run(source):
    process(item)

# Partial consumption — явное закрытие
stream = orchestrator.run(source)
try:
    for item in stream:
        if done: break
finally:
    stream.close()  # → GeneratorExit cascade через все стадии

# contextlib.closing — декларативно
with contextlib.closing(orchestrator.run(source)) as stream:
    for item in stream:
        process(item)
```

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

`gateway` передаётся в `StageFactory.create()` через `**kwargs` — descriptor для `"enrich"` извлекает его через `kw.get("gateway")`:

```python
# В PipelineContainer (wiring):
enrich_stage = providers.Factory(
    lambda f, spec, ctx, opts, gw: f.create("enrich", spec.build_enrich_spec(), ctx, options=opts, gateway=gw),
    f=stage_factory, spec=dataset_spec,
    ctx=enrich_context, opts=enrich_options,
    gw=provider_gateway,          # ← из DI Singleton, не hardcoded в EnricherEngine
)

# StageDescriptor для "enrich":
StageDescriptor(
    stage_type="enrich",
    engine_factory=lambda spec, ctx, **kw: EnricherEngine(
        spec=spec, context=ctx, providers=kw.get("gateway"),  # ← из kwargs
        ...
    ),
    ...
)
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

#### Решение D: Per-command wiring через override context managers

**Проблема**: `PipelineContainer` — субконтейнер `AppContainer`, который создаётся один раз в `run_with_report()` (Composition Root). Но per-command данные (`dataset_spec`, `source_has_header`, `secret_store`, `run_id`) появляются позже — в command handler. Как безопасно передать их в PipelineContainer?

**Два варианта:**

| Вариант | Подход | Проблема |
|---------|--------|----------|
| A: Прямой `.override()` | `pipeline.dataset_spec.override(spec)` | Мутация "протекает" — если забыть `.reset_override()`, состояние остаётся в следующих вызовах |
| B: Per-command контейнер | Создавать `PipelineContainer()` в каждом handler | Теряется связь с `AppContainer`, дублирование wiring |

**Решение**: dependency-injector **context managers** — самый безопасный путь:

```python
# В command handler (delivery layer):
pipeline = ctx.container.pipeline

with pipeline.dataset_spec.override(dataset_spec), \
     pipeline.source_has_header.override(has_header), \
     pipeline.run_id.override(run_id), \
     pipeline.secret_store.override(secret_store):

    # Внутри блока — override действует
    orchestrator = pipeline.transform_pipeline()
    result = orchestrator.run(pipeline.row_source())

# Вне блока — override автоматически откатился
```

**Почему context managers:**

- **Безопасность**: override гарантированно откатывается при выходе из `with`-блока (даже при исключении), мутация не "протекает" в другие команды или тесты
- **Простота**: PipelineContainer остаётся субконтейнером AppContainer, не нужно создавать новый контейнер на каждую команду
- **Тестируемость**: тесты используют тот же механизм — `with pipeline.provider.override(mock):` — единообразный подход для production и test кода
- **Встроенная поддержка**: dependency-injector нативно поддерживает `provider.override()` как context manager, это не самописное решение

**Что override-ится, а что нет:**

| Provider | Источник | Override в handler? |
|----------|----------|---------------------|
| `dataset_spec` | CLI args → `DatasetSpec` | Да — per-command |
| `source_has_header` | CLI flag | Да — per-command |
| `run_id` | Генерируется в handler | Да — per-command |
| `secret_store` | Vault rollout result | Да — per-command (может быть None) |
| `catalog` | `AppContainer` | Нет — приходит из parent container |
| `app_settings` | `AppContainer` | Нет — приходит из parent container |
| `cache_roles` | `AppContainer` | Нет — приходит из parent container |
| `stage_factory` | Singleton, статический | Нет — один на всё приложение |
| `provider_gateway` | Singleton | Нет — один на всё приложение |

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
    source_has_header  = providers.Dependency(instance_of=bool)
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
        lambda spec, h: spec.build_record_source(source_has_header=h),
        spec=dataset_spec, h=source_has_header,
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

### Контракт совместимости стадий

Сводная таблица I/O, capabilities и поведенческих свойств каждой стадии. Служит reference при реализации новых стадий и code review.

| Стадия | Входной тип | Выходной тип | Required capabilities | Optional capabilities | Side effects | Batching |
|--------|-------------|-------------|----------------------|----------------------|--------------|---------|
| `MapStage` | `SourceRecord` | `MappedRecord` | — | — | `ErrorCatalog` (record-level ошибки маппинга) | Запрещает |
| `NormalizeStage` | `MappedRecord` | `NormalizedRecord` | — | — | `ErrorCatalog` (record-level ошибки нормализации) | Запрещает |
| `EnrichStage` | `NormalizedRecord` | `EnrichedRecord` | `EnrichLookupPort` | `DictionaryProviderPort`, `SecretStoreProtocol` | Чтение из cache lookup; `ErrorCatalog` (enrich miss) | Допускает (`BatchConfig`) |
| `MatchStage` | `EnrichedRecord` | `MatchedRecord` | `PlanningRuntimePort` | — | Чтение/запись match runtime; dedup tracking | Требует\* |
| `ResolveStage` | `MatchedRecord` | `ResolvedRecord` | `PlanningRuntimePort`, `ResolverSettings` | — | Запись resolved/pending links; DB-транзакции | Требует\* |

**Легенда — колонка Batching**:
- **Запрещает**: стадия — streaming functor (один-в-один или фильтр); буферизация не нужна и нежелательна
- **Допускает**: стадия поддерживает `BatchableStage.batch_config`; Orchestrator буферизует при ненулевом `BatchConfig`
- **Требует\***: стадия не реализует `BatchableStage`, но буферизация обязательна — обеспечивается UseCase (micro-batching с `flush_interval_ms`); Orchestrator получает уже буферизованный поток

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **Единый контракт**: все 5 стадий реализуют `StageContract.run()` — pipeline покрывает весь поток от source до resolved
- ✅ **Scoped context**: каждая стадия получает только свои capabilities. Map не видит vault. Normalize не видит cache. Enrich не видит resolver_settings
- ✅ **Pay-for-what-you-use**: команда normalize запрашивает только `map_stage` + `normalize_stage`. Planning deps, resolver_settings, match/resolve stages не материализуются
- ✅ **Single source of truth**: `resolver_settings` существует в одном месте — `planning_context`. Нет дублирования путей
- ✅ **Open/closed для capabilities**: новая capability = новый provider в контейнере + передача в нужный context builder. Остальные команды не меняются
- ✅ **Open/closed для стадий**: новая стадия = новый `StageDescriptor` + `factory.register(descriptor)` + provider в контейнере. `StageFactory` не меняется. `DatasetSpec` — осознанный компромисс Phase 1 (см. раздел "Компромисс: DatasetSpec")
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

> **Стратегия**: каждый этап — отдельный коммит с зелёными тестами. Переходный период с deprecated aliases там, где нужно сохранить обратную совместимость на время миграции.

### Этап 1: StageContract + PipelineOrchestrator + BatchConfig

**Цель**: единый контракт для всех стадий; orchestrator с hooks и _monitored(); батчинг через BatchConfig.

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform/stages/stages.py` | Добавить `StageContract[T_in, T_out]`, `AnyStageContract`, `BatchConfig`, `BatchableStage`. `MapStage`, `NormalizeStage`, `EnrichStage`, `MatchStage` реализуют `StageContract`. `ResolveStage.run()` — убрать `dataset` kwarg. |
| `connector/domain/transform/stages/stages.py` | `StagePipeline` — добавить deprecated alias, указывающий на `PipelineOrchestrator`. |
| `connector/domain/transform/stages/stages.py` | Создать `PipelineOrchestrator` с `PipelineHooks`, `_monitored()`, `_execute_stage()`, поддержкой `BatchConfig`. |
| `connector/domain/transform/stages/stages.py` | `TransformStageProcessor` — добавить deprecated alias на `StageContract` (переходный период). |
| `connector/delivery/cli/pipeline_registry.py` | Создать typed factory functions: `build_transform_pipeline()`, `build_full_pipeline()`. |
| Тесты (architecture) | `test_all_stages_implement_stage_contract`, `test_resolve_stage_run_no_extra_kwargs`, `test_stage_contract_is_protocol_not_abc`, `test_batchable_stage_is_subtype_of_stage_contract` |
| Тесты (unit) | `test_orchestrator_*` (full chain, empty stages, batching), `test_pipeline_hook_*` (все hooks), `test_pipeline_hook_on_stage_complete_not_fired_for_empty_stream`, `test_pipeline_hook_on_stage_error_not_fired_before_first_pull` |

### Этап 2: PipelineMetadata + StageExecutionContext

**Цель**: scoped context для стадий; замена разрозненных deps-объектов; fail-fast capability check.

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform/context.py` | Создать `PipelineMetadata` (frozen dataclass), `StageExecutionContext` (require/get/has), `MissingCapabilityError`. |
| `connector/domain/transform/providers/deps.py` | `TransformProviderDeps` — добавить deprecation warning, alias на `StageExecutionContext` (переходный период). |
| `connector/domain/transform/resolver/resolve_deps.py` | `PlanningDependencies` — добавить deprecation warning (переходный период). |
| Engine-классы | `EnricherEngine`, `MatchEngine`, `ResolveEngine` принимают `StageExecutionContext` вместо разрозненных deps. Внутри engine: `ctx.require(EnrichLookupPort)`, `ctx.metadata.catalog`, etc. |
| Тесты (unit) | `test_context_require_*`, `test_context_get_*`, `test_context_has_*`, `test_context_is_frozen`, `test_enrich_context_scoping`, `test_planning_context_scoping`, `test_capabilities_not_visible_cross_stage` |
| Тесты (architecture) | `test_stage_execution_context_is_frozen`, `test_pipeline_metadata_is_frozen_dataclass` |

### Этап 3: StageFactory (Registry Pattern) + сужение DatasetSpec

**Цель**: registry-based factory; delivery layer регистрирует дескрипторы; DatasetSpec теряет `build_*_stage()`.

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform/factory.py` | Создать `StageDescriptor` (frozen dataclass), `StageFactory` (registry: `register()` + `create()` с fail-fast capability check). |
| `connector/delivery/cli/pipeline_registry.py` | Создать `_build_stage_factory()` — регистрация дескрипторов всех 5 стадий (`"map"`, `"normalize"`, `"enrich"`, `"match"`, `"resolve"`). `ProviderGateway` передаётся через kwargs. |
| `connector/datasets/spec.py` | Убрать `build_*_stage()`, `build_enrich_deps()`, `build_planning_deps()`, `build_transform_stages()`, `build_planning_stages()`. Сохранить typed `build_*_spec()` (Phase 1 компромисс). |
| `connector/datasets/employees/spec.py` | Убрать реализации удалённых методов. |
| Тесты (unit) | `test_stage_factory_no_io`, `test_stage_factory_unknown_type`, `test_stage_factory_duplicate_registration`, `test_stage_factory_fail_fast_missing_capability`, `test_stage_factory_create_calls_engine_factory_with_kwargs`, `test_stage_factory_create_calls_stage_wrapper`, `test_stage_factory_introspection` |
| Тесты (integration) | `test_all_5_stage_types_registered_in_build_stage_factory` |
| Тесты (architecture) | `test_stage_descriptor_is_frozen_dataclass` |

### Этап 4: PipelineContainer + миграция command handlers

**Цель**: DI-сборка pipeline; per-command wiring через override context managers; каждый handler запрашивает только нужные стадии.

| Файл | Изменение |
|------|-----------|
| `connector/delivery/cli/containers.py` | Создать `PipelineContainer` (DeclarativeContainer): providers `dataset_spec`, `run_id`, `source_has_header`, `secret_store`, `catalog`, `app_settings`, `cache_roles`, `dictionaries`; scoped contexts (`transform_context`, `enrich_context`, `planning_context`); `stage_factory` Singleton; `provider_gateway` Singleton; все 5 stage providers; `transform_pipeline`, `full_pipeline` orchestrators. |
| `connector/delivery/cli/containers.py` | `AppContainer`: добавить `pipeline = providers.Container(PipelineContainer, catalog=..., app_settings=..., cache_roles=...)`. |
| `connector/delivery/cli/containers.py` | `build_pipeline_context()` и `PipelineContext` — добавить deprecation warning (удалить в Этапе 5). |
| `connector/delivery/commands/normalize.py` | Per-command override context manager: `dataset_spec`, `run_id`, `source_has_header`. Запрашивает только `map_stage()`, `normalize_stage()`. |
| `connector/delivery/commands/enrich.py` | Per-command override. Запрашивает `map_stage()`, `normalize_stage()`, `enrich_stage()`. |
| `connector/delivery/commands/match.py` | Per-command override включая `secret_store`. Запрашивает `match_stage()`. Один путь для `resolver_settings`. |
| `connector/delivery/commands/resolve.py` | Per-command override. Запрашивает `resolve_stage()`. |
| `connector/delivery/commands/mapping.py` | Per-command override. Запрашивает `map_stage()`. |
| `connector/delivery/commands/import_plan.py` | Per-command override включая vault deps. Запрашивает все 5 stages. |
| Тесты (integration) | `test_normalize_does_not_materialize_planning`, `test_single_resolver_settings_path_in_match`, `test_pipeline_container_*_command_wiring` (normalize/enrich/match/resolve), `test_pipeline_container_override_context_manager_resets`, `test_pipeline_container_override_resets_on_exception`, `test_provider_gateway_is_singleton_across_stages` |
| Тесты (e2e) | `test_e2e_pipeline_container_full_wiring_normalize` |

### Этап 5: Cleanup — удаление legacy

**Цель**: удалить deprecated aliases и legacy компоненты; тесты без deprecated кода.

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform/providers/deps.py` | Удалить `TransformProviderDeps` (или весь файл если пуст). |
| `connector/domain/transform/resolver/resolve_deps.py` | Удалить `PlanningDependencies` (или весь файл если пуст). |
| `connector/domain/transform/stages/stages.py` | Удалить `StagePipeline`, `TransformStageProcessor` (deprecated aliases), `@batched()` decorator. |
| `connector/delivery/cli/containers.py` | Удалить `build_pipeline_context()`, `PipelineContext`. |
| Все тесты, импортирующие deprecated | Обновить импорты на новые символы. |
| Тесты (architecture) | `test_invariant_stages_are_stateless`, `test_long_lived_resource_not_closed_by_stage_on_generator_exit` |
| Тесты (e2e) | `test_e2e_*` полный набор: normalize, enrich, full chain, error record, partial consumption |

### Инварианты

1. **`StageContract.run()`** — единственный метод вызова стадии извне. Никаких extra kwargs.
2. **`StageExecutionContext`** — иммутабельный: создаётся один раз при сборке стадии, не модифицируется в runtime.
3. **Capability scoping**: стадия видит только те capabilities, которые явно переданы в её context.
4. **`PipelineContainer`** — один экземпляр на вызов CLI-команды. Не переиспользуется между вызовами.
5. **`StageFactory`** — registry-based: единый метод `create(stage_type, spec, context)`. Не содержит hardcoded `create_*()` методов. Не делает I/O.
6. **`StageFactory` registration** — ответственность delivery layer (`_build_stage_factory()`). Domain определяет `StageDescriptor` и `StageFactory`, delivery регистрирует конкретные стадии.
7. **`DatasetSpec`** не содержит `build_*_stage()` методов: только DSL-spec builders.
8. **`resolver_settings`** существует только в `planning_context`. Не материализуется в transform-стадиях.
9. **Record-level ошибки** — Stage использует `context.metadata.catalog`. Stage **не бросает** Python exception для ошибок отдельных записей. Exception = stage-fatal сигнал.
10. **Stage/infra-fatal ошибки** — `PipelineOrchestrator._monitored()` вызывает `on_stage_error` (если стадия успела получить хотя бы один элемент), затем **re-raises** без подавления. Если исключение произошло до первого pull (`start_time is None`) — re-raise без хука. Конвертация exception в outcome — ответственность UseCase/handler, не orchestrator.
11. **Стадии — stateless functors**: нет состояния на уровне instance. Per-run ресурсы (буферы, leases) аллоцируются внутри генератора `run()` и освобождаются в `try/finally`. Long-lived ресурсы принадлежат DI-контейнеру, не стадиям.
12. **UseCase закрывает pipeline iterator**: UseCase обязан гарантировать закрытие итератора при partial consumption — через `stream.close()` в `finally` или `contextlib.closing`. Это обеспечивает каскадный `GeneratorExit` через все стадии.

---

## 🧪 Валидация решения

#### Architecture tests (структурная корректность, инварианты протоколов)

> Цель: зафиксировать контракты на уровне типов и структур. Ломаются при изменении интерфейса, не при изменении логики.

- ✅ `test_all_stages_implement_stage_contract()` — все 5 стадий проходят structural check через `isinstance(stage, StageContract)` / mypy Protocol
- ✅ `test_resolve_stage_run_no_extra_kwargs()` — `ResolveStage.run(source)` без `dataset` kwarg; сигнатура соответствует `StageContract`
- `test_stage_contract_is_protocol_not_abc()` — `StageContract` — Protocol, не ABC; реализация через structural subtyping без `register()`
- `test_batchable_stage_is_subtype_of_stage_contract()` — `BatchableStage` структурно совместим с `StageContract`; orchestrator принимает оба
- `test_stage_run_signature_iterable_to_iterable()` — все 5 стадий: `run()` принимает `Iterable[T_in]`, возвращает `Iterable[T_out]`
- `test_stage_execution_context_is_frozen()` — `_capabilities` dict недоступен для модификации извне после создания контекста
- `test_pipeline_metadata_is_frozen_dataclass()` — `PipelineMetadata` — `frozen=True`; попытка изменить поле raises `FrozenInstanceError`
- `test_stage_descriptor_is_frozen_dataclass()` — `StageDescriptor` — `frozen=True`
- `test_invariant_stages_are_stateless()` — вызов `stage.run()` дважды на одном экземпляре даёт независимые результаты (нет instance-level state)

#### Unit tests (изолированные компоненты)

**StageExecutionContext**

- `test_context_require_returns_registered_capability()` — `ctx.require(CachePort)` возвращает зарегистрированный экземпляр
- `test_context_require_raises_missing_capability_error()` — `ctx.require(MissingPort)` raises `MissingCapabilityError`
- `test_context_get_returns_none_for_missing()` — `ctx.get(MissingPort)` возвращает `None`, не raises
- `test_context_has_returns_true_for_registered()` — `ctx.has(RegisteredPort)` == `True`
- `test_context_has_returns_false_for_missing()` — `ctx.has(MissingPort)` == `False`
- ✅ `test_enrich_context_scoping()` — enrich context содержит `EnrichLookupPort`; не содержит `PlanningRuntimePort`
- ✅ `test_planning_context_scoping()` — planning context содержит `PlanningRuntimePort` + `ResolverSettings`; не содержит `DictionaryProviderPort`
- `test_capabilities_not_visible_cross_stage()` — `enrich_context` не имеет `PlanningRuntimePort`; `transform_context` не имеет `EnrichLookupPort`

**StageFactory**

- ✅ `test_stage_factory_no_io()` — `StageFactory.create()` не обращается к файловой системе (mock filesystem: no calls)
- ✅ `test_stage_factory_unknown_type()` — `factory.create("unknown", ...)` raises `ValueError`
- ✅ `test_stage_factory_duplicate_registration()` — повторный `register()` того же `stage_type` raises `ValueError`
- ✅ `test_stage_factory_fail_fast_missing_capability()` — `create("enrich", ..., context_without_cache)` raises `MissingCapabilityError` до вызова `engine_factory`
- `test_stage_factory_create_calls_engine_factory_with_kwargs()` — `create("enrich", spec, ctx, gateway=gw)` передаёт `gateway` в `engine_factory(**kw)`
- `test_stage_factory_create_calls_stage_wrapper()` — `create()` вызывает `stage_wrapper(engine, ctx)` и возвращает результат
- `test_stage_factory_introspection()` — после `register()` тип доступен через `factory._registry`

**PipelineOrchestrator**

- ✅ `test_pipeline_orchestrator_full_chain()` — все 5 стадий обрабатывают данные в правильном порядке
- `test_orchestrator_empty_stages_passes_source_unchanged()` — пустой список стадий: `orchestrator.run(source)` возвращает source без изменений
- `test_orchestrator_single_stage_chain()` — один stage: данные корректно проходят через `_monitored()`
- `test_orchestrator_batching_for_batchable_stage()` — стадия с `BatchConfig(batch_size=3)` получает батчи, а не отдельные записи
- `test_orchestrator_no_batching_for_non_batchable_stage()` — стадия без `batch_config` получает поток 1-в-1

**PipelineHooks**

- ✅ `test_pipeline_hook_on_stage_bind_is_eager()` — `on_stage_bind` вызывается при `orchestrator.run()` до потребления данных
- ✅ `test_pipeline_hook_on_stage_start_is_lazy()` — `on_stage_start` вызывается только при первом pull, не при `run()`
- ✅ `test_pipeline_hook_on_stage_complete_on_full_consumption()` — `on_stage_complete` вызывается при исчерпании потока; `stats["items"]` == числу записей
- ✅ `test_pipeline_hook_on_stage_abort_on_partial_consumption()` — `on_stage_abort` вызывается при `GeneratorExit`; duration_ms > 0
- ✅ `test_pipeline_hook_on_stage_error_on_exception()` — `on_stage_error(stage_name, exc, duration_ms)` вызывается при исключении в стадии
- `test_pipeline_hook_on_stage_complete_not_fired_for_empty_stream()` — пустой входной стрим: `on_stage_start` и `on_stage_complete` **не** вызываются (start_time guard)
- `test_pipeline_hook_on_stage_error_not_fired_before_first_pull()` — исключение в stage до первого yield: `on_stage_error` **не** вызывается; исключение re-raises
- `test_pipeline_hook_stats_items_count_matches_output()` — `on_stage_complete` stats["items"] == реальному числу yielded элементов
- `test_pipeline_hooks_none_by_default_orchestrator_runs_normally()` — `PipelineHooks()` без callbacks: orchestrator работает без ошибок

**Модель ошибок**

- ✅ `test_stage_does_not_raise_for_record_level_error()` — запись с ошибкой попадает в `ErrorCatalog`; pipeline продолжается без exception; следующие записи обрабатываются
- ✅ `test_orchestrator_reraises_after_on_stage_error()` — `_monitored()` вызывает `on_stage_error`, затем re-raises; исключение не подавляется
- `test_error_catalog_receives_all_record_level_errors()` — несколько плохих записей в потоке: все попадают в catalog, хорошие записи yield-ятся
- `test_infra_fatal_exception_propagates_to_use_case()` — `IOError` в стадии propagates через orchestrator к UseCase; не подавляется

**Lifecycle стадий**

- ✅ `test_stage_per_run_resource_released_on_generator_exit()` — per-run ресурс (счётчик в `finally`) освобождается при `GeneratorExit`
- ✅ `test_use_case_closes_pipeline_iterator_on_partial_consumption()` — UseCase вызывает `stream.close()` при early exit; `GeneratorExit` проходит каскадно
- `test_generator_exit_cascades_through_full_5_stage_chain()` — при `stream.close()` на выходе full pipeline: `GeneratorExit` доходит до `MapStage`; все `finally` выполняются
- `test_long_lived_resource_not_closed_by_stage_on_generator_exit()` — ресурс из DI (mock Singleton): `close()` **не** вызывается при `GeneratorExit` в стадии

#### Integration tests (межкомпонентное взаимодействие, DI wiring)

- ✅ `test_normalize_does_not_materialize_planning()` — при запросе `normalize_stage()` из контейнера, `planning_context` не создаётся
- ✅ `test_single_resolver_settings_path_in_match()` — resolver_settings приходит в match ровно одним путём (через `planning_context`)
- `test_pipeline_container_normalize_command_wiring()` — override: dataset_spec + run_id; `normalize_stage()` разрешается; `planning_context` не вызывается
- `test_pipeline_container_enrich_command_wiring()` — `enrich_stage()` разрешается с `enrich_context`; `planning_context` не создаётся
- `test_pipeline_container_match_command_wiring()` — `match_stage()` разрешается с `planning_context`; `resolver_settings` доступен
- `test_pipeline_container_resolve_command_wiring()` — `resolve_stage()` разрешается; `resolver_settings` приходит из `planning_context`, а не из другого пути
- `test_pipeline_container_override_context_manager_resets()` — `pipeline.dataset_spec.override(spec)` context manager: после выхода из `with` override сброшен
- `test_pipeline_container_override_resets_on_exception()` — при исключении внутри `with pipeline.provider.override(...)`: override сброшен в `finally`
- `test_all_5_stage_types_registered_in_build_stage_factory()` — `_build_stage_factory()` регистрирует `"map"`, `"normalize"`, `"enrich"`, `"match"`, `"resolve"`
- `test_enrich_stage_receives_provider_gateway_from_di()` — `enrich_stage()` создаётся с `ProviderGateway` из `provider_gateway` Singleton
- `test_provider_gateway_is_singleton_across_stages()` — `enrich_stage()` дважды: `ProviderGateway` — тот же экземпляр
- ✅ `test_use_case_catches_stage_fatal_converts_to_outcome()` — UseCase конвертирует stage exception в command outcome

#### E2E tests (полный поток данных от source до выходного типа)

- `test_e2e_normalize_pipeline()` — `SourceRecord` → `MapStage` → `NormalizeStage` → `List[NormalizedRecord]`; проверка output shape
- `test_e2e_enrich_pipeline_with_mock_lookup()` — source → map → normalize → enrich с mock `EnrichLookupPort`; enrich miss идёт в catalog
- `test_e2e_full_pipeline_happy_path()` — все 5 стадий с mock capabilities; `ResolvedRecord` на выходе
- `test_e2e_error_record_does_not_stop_pipeline()` — один плохой record в потоке: остальные обработаны; catalog содержит ошибку
- `test_e2e_stage_fatal_stops_pipeline_use_case_converts()` — stage raises domain exception: pipeline останавливается; UseCase логирует/конвертирует в outcome
- `test_e2e_partial_consumption_cleanup()` — consume 3 из 1000 записей; `stream.close()`; все стадии очищены (`GeneratorExit` cascade)
- `test_e2e_pipeline_container_full_wiring_normalize()` — `PipelineContainer` собирается с mock `AppContainer` deps; normalize command flow проходит end-to-end

**Метрики успеха**:
- Количество файлов, затрагиваемых при добавлении новой capability: **≤ 2** (context builder + container provider) вместо текущих 5+
- Количество файлов, затрагиваемых при добавлении новой стадии: **≤ 5** (stage class + StageDescriptor registration + DatasetSpec protocol + EmployeesSpec impl + container provider). DatasetSpec coupling — осознанный компромисс Phase 1, устраняется в Phase 2 ([TRANSFORM-DEC-005](./TRANSFORM-DEC-005-dataset-spec-generic-accessor-evolution.md))
- `resolver_settings` в коде `normalize.py`, `enrich.py`, `mapping.py`: **0 упоминаний**

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- `ctx.require(PortType)` не проверяется статически mypy без overload-стабов — динамические запросы engine обнаруживаются в runtime (статически декларированные capabilities проверяются раньше — при `create()`)
- `StageFactory` — registry-based, но регистрация статическая (в `_build_stage_factory()`), не runtime-динамическая. Плагины не подгружаются из внешних пакетов — расширение через код, не через конфигурацию
- `**kwargs` в `StageFactory.create()` — string-keyed bag без статической проверки. Контракт между PipelineContainer и descriptor неявный. На 5 стадиях управляемо; при росте рассмотреть per-stage `BuildParams` dataclass
- `DatasetSpec` сохраняет typed `build_*_spec()` методы (Phase 1 компромисс): добавление новой стадии требует изменений в протоколе (`DatasetSpec`) и реализации (`EmployeesSpec`). Устраняется в Phase 2 при замене `EmployeesSpec` на generic YAML-driven impl — [TRANSFORM-DEC-005](./TRANSFORM-DEC-005-dataset-spec-generic-accessor-evolution.md)
- `StageExecutionContext` — v1: одна capability на один `port_type`. Два экземпляра одного порта в одном контексте невозможны. Workaround: typed aggregate (`CachePair`, `DualLookupPort`). Named capability tokens — v2, откладывается до появления конкретного use case

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
- [TRANSFORM-PROBLEM-005](./TRANSFORM-PROBLEM-005-dataset-spec-ocp-violation.md) — DatasetSpec OCP violation: typed `build_*_spec()` методы требуют изменений при добавлении стадии
- [TRANSFORM-DEC-005](./TRANSFORM-DEC-005-dataset-spec-generic-accessor-evolution.md) — двухфазная эволюция DatasetSpec к generic `build_spec_for(stage_type)`

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
| 2026-02-22 | Решение D: per-command wiring через dependency-injector override context managers — безопасная передача per-command данных в PipelineContainer |
| 2026-02-22 | StageContract уточнён: Generic[T_in, T_out]. Typed factory functions в delivery (не fluent builder). PipelineOrchestrator/StageFactory — type-erased. Erasure boundary зафиксирована |
| 2026-02-22 | PipelineHooks переработан: двухуровневая модель (assembly: on_stage_bind + execution: on_stage_start/complete/error/abort). Добавлен _monitored() wrapper для lazy-aware execution hooks |
| 2026-02-22 | DatasetSpec OCP gap зафиксирован как осознанный компромисс Phase 1. Typed `build_*_spec()` остаются до замены `EmployeesSpec`. Открыта TRANSFORM-PROBLEM-005, целевое решение TRANSFORM-DEC-005 |
| 2026-02-22 | Добавлена явная модель ошибок: три уровня (record / stage-fatal / infra-fatal), ownership chain Stage → _monitored() → UseCase/handler. Инварианты 9 и 10 |
| 2026-02-22 | Зафиксирована lifecycle-политика стадий: stateless functor, три уровня владения ресурсами, per-run ресурсы в generator try/finally, long-lived в DI. UseCase отвечает за закрытие pipeline iterator. Инварианты 11 и 12 |
| 2026-02-22 | Добавлен "Контракт совместимости стадий": сводная таблица I/O типов, required/optional capabilities, side effects и batching-политики для всех 5 стадий. Known limitation: StageExecutionContext v1 — одна capability на port_type |
| 2026-02-22 | Ревизия консистентности: (1) Решение D перемещено в раздел "Архитектурные решения"; (2) исправлен раздел ProviderGateway (Registry Pattern API); (3) уточнён Инвариант 10 (start_time guard); (4) исправлен буллет Open/closed для стадий; (5) задокументировано поведение _monitored() для пустых стримов. Набор тестов расширен и категоризирован (architecture/unit/integration/e2e). План миграции Этапов 1-5 детализирован: явный список тестов по каждому этапу, явный шаг для TransformStageProcessor, per-command override wiring в Этапе 4. |
