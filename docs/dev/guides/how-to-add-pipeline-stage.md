# Как добавить новую стадию пайплайна

> **Практическое руководство** по добавлению новых стадий в transform-конвейер (MAP → RESOLVE).
> Основано на TRANSFORM-DEC-007: декларативный реестр чекпоинтов + PipelineComposer.

---

## Содержание

- [Обзор архитектуры](#обзор-архитектуры)
- [Два пути добавления стадии](#два-пути-добавления-стадии)
- [Путь 1: через StageFactory (stateless стадии)](#путь-1-через-stagefactory-stateless-стадии)
- [Путь 2: через Singleton в PipelineContainer (stateful стадии)](#путь-2-через-singleton-в-pipelinecontainer-stateful-стадии)
- [Capabilities и StageExecutionContext](#capabilities-и-stageexecutioncontext)
- [Включение стадии в чекпоинты](#включение-стадии-в-чекпоинты)
- [Тест-стратегия](#тест-стратегия)
- [Чек-лист](#чек-лист)
- [Частые ошибки](#частые-ошибки)

---

## Обзор архитектуры

Каждая стадия конвейера состоит из двух независимых уровней:

```
Engine                 ← бизнес-логика (enrich, match, resolve...)
  ↓ создаётся engine_factory / providers.Singleton
Stage                  ← StageContract: run(source) → stream
  ↓ регистрируется в stage_registry[StageName.XXX]
PipelineComposer       ← compose(checkpoint) → PipelineOrchestrator
  ↓ вызывается в command handler / PlanningPipeline
PipelineOrchestrator   ← запускает цепочку стадий
```

### Ключевые файлы

| Файл | Роль |
|------|------|
| `connector/domain/transform/stages/stages.py` | `StageContract`, конкретные стадии |
| `connector/domain/transform/factory.py` | `StageFactory`, `StageDescriptor` |
| `connector/delivery/cli/pipeline_config.py` | `StageName`, `CheckpointName`, `PIPELINE_CHECKPOINTS` |
| `connector/delivery/cli/pipeline_composer.py` | `PipelineComposer.compose()` |
| `connector/delivery/cli/pipeline_registry.py` | `build_stage_factory()`, engine/wrapper factories |
| `connector/delivery/cli/containers.py` | `PipelineContainer`: DI-провайдеры стадий |

### Контракт стадии

Любая стадия реализует `StageContract` структурно (без наследования):

```python
class MyStage:
    stage_name: str = "my_stage"          # строка для hooks и диагностики

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        for item in source:
            # обработка записи
            yield item
```

`StageContract` — `@runtime_checkable` Protocol. `isinstance(stage, StageContract)` проверяет
наличие `stage_name` и `run`, но не generic-параметры.

---

## Два пути добавления стадии

Выбор пути определяется наличием разделяемого per-run состояния и lifecycle-зависимостей.

### Путь 1: через StageFactory

**Для стадий без разделяемого состояния** — аналог `map`, `normalize`, `enrich`.

- Engine создаётся через `engine_factory(spec, ctx, **kwargs)` → перевоссоздаётся при каждой команде.
- Stage создаётся через `stage_wrapper(engine, ctx)`.
- Регистрируется в `build_stage_factory()` через `StageDescriptor`.
- Provider в `PipelineContainer` — `providers.Factory`.

### Путь 2: через Singleton в PipelineContainer

**Для стадий с разделяемым состоянием** — аналог `match`, `resolve_context`, `resolve`.

- Engine и Stage создаются как `providers.Singleton` в `PipelineContainer`.
- В `build_stage_factory()` регистрируется stub с `NotImplementedError` — только для
  `StageFactory.registered_types` (introspection).
- `stage_registry` в `pipeline_composer` указывает на тот же Singleton-провайдер.

---

## Путь 1: через StageFactory (stateless стадии)

### Шаг 1: Создать Engine

Engine — бизнес-логика стадии. Принимает `spec` (DSL-spec) и `StageExecutionContext`.

```python
# connector/domain/transform/my_feature/my_engine.py

class MyEngine:
    """
    Назначение:
        Движок стадии my_stage: [описание].

    Граница ответственности:
        - Owns: [что делает].
        - Does NOT: I/O, lifecycle управление, хранение per-run состояния.
    """

    def __init__(
        self,
        spec,                          # DSL-spec: MySpec
        ctx,                           # StageExecutionContext
        *,
        options=None,                  # build options из DSL
    ) -> None:
        self._spec = spec
        self._ctx = ctx
        # если нужен capability:
        # self._port = ctx.require(MyCapabilityPort)

    def process(self, item: TransformResult) -> TransformResult | None:
        """Обработать одну запись. None → запись заблокирована."""
        ...
```

### Шаг 2: Создать Stage

Stage оборачивает Engine и реализует `StageContract`.

```python
# connector/domain/transform/stages/stages.py  (или отдельный модуль)

class MyStage:
    """
    Назначение:
        Стадия my_stage. Реализует StageContract.

    Инварианты:
        - Stateless functor: нет per-run состояния на уровне instance.
        - Record-level ошибки → catalog; stage не бросает исключений per-record.
    """

    stage_name: str = "my_stage"

    def __init__(self, engine: MyEngine, catalog: ErrorCatalog) -> None:
        self.engine = engine
        self.catalog = catalog

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        for item in source:
            if item.row is None:          # пропустить уже заблокированные записи
                yield item
                continue

            boundary_errors: list = []
            result: TransformResult | None = None
            with diagnostic_boundary(
                stage=DiagnosticStage.MY_STAGE,   # добавить в DiagnosticStage enum
                catalog=self.catalog,
                sink=boundary_errors,
                record_ref=item.row_ref,
            ):
                result = self.engine.process(item)

            if result is None:
                builder = item.as_builder()
                builder.set_row(None)
                for err in boundary_errors:
                    builder.add_error_item(err)
                yield builder.build()
                continue

            builder = result.as_builder()
            for err in boundary_errors:
                builder.add_error_item(err)
            yield builder.build()
```

> **Паттерн `if item.row is None: yield item; continue`** — обязателен для всех стадий после map.
> Обеспечивает pass-through error records без повторной обработки.

### Шаг 3: Зарегистрировать в pipeline_registry.py

Добавить `engine_factory` и `stage_wrapper` в
[connector/delivery/cli/pipeline_registry.py](../../../connector/delivery/cli/pipeline_registry.py):

```python
def _my_engine_factory(
    spec: object, ctx: StageExecutionContext, **kwargs: object,
) -> MyEngine:
    return MyEngine(
        spec=spec,  # type: ignore[arg-type]
        ctx=ctx,
        options=kwargs.get("options"),  # type: ignore[arg-type]
    )
```

Для `stage_wrapper` используй готовый хелпер `_stage_wrapper(stage_cls)`, если Stage принимает
`(engine, catalog)`:

```python
# В build_stage_factory():
factory.register(StageDescriptor(
    stage_type="my_stage",
    engine_factory=_my_engine_factory,
    stage_wrapper=_stage_wrapper(MyStage),     # MyStage(engine, catalog)
    required_capabilities=frozenset(),          # или frozenset({MyCapabilityPort})
))
```

Если Stage принимает нестандартные аргументы — пиши wrapper явно:

```python
def _my_stage_wrapper(engine: object, ctx: StageExecutionContext) -> MyStage:
    return MyStage(engine, ctx.metadata.catalog, extra_arg=ctx.metadata.run_id)
```

### Шаг 4: Добавить StageName и провайдер в containers.py

[connector/delivery/cli/pipeline_config.py](../../../connector/delivery/cli/pipeline_config.py):

```python
class StageName:
    MAP = "map_stage"
    # ... существующие ...
    MY_STAGE = "my_stage"       # ← новая строка
```

[connector/delivery/cli/containers.py](../../../connector/delivery/cli/containers.py), секция
«Transform stages»:

```python
my_stage = providers.Factory(
    _create_stage,
    factory=stage_factory,
    stage_type="my_stage",
    spec=providers.Factory(lambda s: s.build_my_spec(), s=dataset_spec),
    ctx=transform_context,          # или enrich_context / planning_context
    options=my_options,
)
```

Если нужны build options — добавь соответствующий `providers.Factory` в секцию «Build options»:

```python
my_options = providers.Factory(
    lambda s: load_my_build_options_for_dataset(s.dataset_name),
    s=dataset_spec,
)
```

### Шаг 5: Добавить в stage_registry и checkpoints

[containers.py](../../../connector/delivery/cli/containers.py), секция `pipeline_composer`:

```python
pipeline_composer = providers.Singleton(
    PipelineComposer,
    stage_registry={
        StageName.MAP: map_stage,
        # ... существующие ...
        StageName.MY_STAGE: my_stage,    # ← добавить
    },
    checkpoints=providers.Object(PIPELINE_CHECKPOINTS),
)
```

[pipeline_config.py](../../../connector/delivery/cli/pipeline_config.py), раздел
`PIPELINE_CHECKPOINTS`:

```python
PIPELINE_CHECKPOINTS: dict[str, list[str]] = {
    CheckpointName.MAP: [StageName.MAP],
    # ... вставить стадию в нужный checkpoint (см. раздел «Включение в чекпоинты»)
}
```

---

## Путь 2: через Singleton в PipelineContainer (stateful стадии)

Используй этот путь если стадия:
- требует разделяемого состояния между несколькими компонентами (как `_batch_index` между
  `ResolveContextStage` и `ResolveStage`), или
- принимает в конструкторе зависимости недоступные через стандартный `_stage_wrapper(stage_cls)`
  (как `IMatchBatchSettings` у `MatchStage`).

### Шаги 1–2: Engine и Stage — аналогично Пути 1

Единственное отличие: Engine может хранить per-run состояние, т.к. он сам является Singleton-ом
и сбрасывается через `dedup_store.reset()` или аналогичный механизм.

### Шаг 3: Создать Singleton-провайдеры в PipelineContainer

```python
# containers.py — секция «Planning stages» или «Per-run state singletons»

_my_engine = providers.Singleton(
    MyEngine,
    spec=providers.Factory(lambda s: s.build_my_spec(), s=dataset_spec),
    ctx=planning_context,
    options=my_options,
    shared_state=_shared_state_singleton,    # разделяемые зависимости
)

my_stage = providers.Singleton(
    MyStage,
    engine=_my_engine,
    catalog=catalog,
    extra_dep=_shared_state_singleton,
)
```

> **Singleton в override()-контексте**: при команде `mapping` `my_stage` не материализуется
> (lazy). При команде, использующей нужный checkpoint, Singleton создаётся один раз и
> переиспользуется в рамках одного вызова CLI-команды.

### Шаг 4: Зарегистрировать stub в build_stage_factory()

Stub нужен ТОЛЬКО для `StageFactory.registered_types` (introspection в тестах).
При попытке вызвать `create()` — бросает `NotImplementedError`, что тестируется явно.

```python
# pipeline_registry.py

def _my_stage_stub_wrapper(
    engine: object, ctx: StageExecutionContext,
) -> MyStage:
    """Stub. MyStage создаётся напрямую в PipelineContainer (требует extra_dep)."""
    raise NotImplementedError("my_stage is created directly in PipelineContainer, not via StageFactory")


# В build_stage_factory():
factory.register(StageDescriptor(
    stage_type="my_stage",
    engine_factory=lambda spec, ctx, **kw: (_ for _ in ()).throw(
        NotImplementedError("my_stage engine is a Singleton in PipelineContainer")
    ),
    stage_wrapper=_my_stage_stub_wrapper,
    required_capabilities=frozenset(),
))
```

Или более читаемо:

```python
def _my_stage_stub_factory(spec: object, ctx: StageExecutionContext, **kw: object) -> None:
    raise NotImplementedError("my_stage is a Singleton in PipelineContainer, not via StageFactory")

factory.register(StageDescriptor(
    stage_type="my_stage",
    engine_factory=_my_stage_stub_factory,
    stage_wrapper=_my_stage_stub_wrapper,
    required_capabilities=frozenset(),
))
```

### Шаг 5–6: StageName, stage_registry, checkpoints

Аналогично Пути 1, шаги 4–5.

```python
# containers.py — pipeline_composer:
stage_registry={
    # ...
    StageName.MY_STAGE: my_stage,   # Singleton-провайдер
},
```

---

## Capabilities и StageExecutionContext

`StageExecutionContext` предоставляет стадии только те портовые зависимости, которые ей разрешены.

### Когда нужен capability

Если Engine обращается к внешнему порту (кэш, runtime) — объяви его через `required_capabilities`
в `StageDescriptor`. StageFactory проверит наличие capability до создания Engine (fail-fast).

```python
# ports (Protocol) — в connector/domain/ports/
class MyServicePort(Protocol):
    def lookup(self, key: str) -> str | None: ...

# Engine:
class MyEngine:
    def __init__(self, spec, ctx: StageExecutionContext, **kwargs):
        self._service = ctx.require(MyServicePort)   # MissingCapabilityError если нет
```

```python
# StageDescriptor:
required_capabilities=frozenset({MyServicePort})
```

### Как добавить capability в context

В `containers.py` создай нужный context-билдер или расширь существующий:

```python
def _build_my_context(
    metadata: PipelineMetadata,
    cache_roles: ...,
) -> StageExecutionContext:
    caps: dict[type, object] = {
        MyServicePort: cache_roles.my_service,
    }
    return StageExecutionContext(metadata=metadata, capabilities=caps)
```

Три готовых context-а:
- `transform_context` — базовый (без capabilities, только metadata)
- `enrich_context` — добавляет `EnrichLookupPort`, `SecretStorePort`, `DictionaryPort`
- `planning_context` — добавляет `MatchRuntimePort`, `ResolveRuntimePort`, `ResolverSettings`

Если твоя стадия нужна в `enrich_context` или `planning_context` — добавь capability туда.
Если нужен принципиально новый context — создай `_build_my_context` по образцу.

---

## Включение стадии в чекпоинты

`PIPELINE_CHECKPOINTS` — единственное место истины о составе pipeline.
Чекпоинты кумулятивные: `ENRICH` включает MAP + NORMALIZE + ENRICH.

Решение о включении: в какой команде нужна твоя стадия?

| Команда | Checkpoint | Итоговая цепочка |
|---------|-----------|-----------------|
| `mapping` | `MAP` | MAP |
| `normalize` | `NORMALIZE` | MAP → NORMALIZE |
| `enrich` | `ENRICH` | MAP → NORMALIZE → ENRICH |
| `match` | `MATCH` | MAP → NORMALIZE → ENRICH → MATCH |
| `resolve`, `import_plan` (pre-resolve) | `RESOLVE_CONTEXT` | MAP → … → MATCH → RESOLVE_CONTEXT |
| `resolve`, `import_plan` (full) | `RESOLVE` / `PLAN` | MAP → … → RESOLVE_CONTEXT → RESOLVE |

**Пример**: стадия нужна между ENRICH и MATCH:

```python
# pipeline_config.py

class CheckpointName:
    # ... существующие ...
    MY_STAGE = "my_stage"           # опционально: новый checkpoint для прямого доступа

PIPELINE_CHECKPOINTS: dict[str, list[str]] = {
    CheckpointName.MAP:     [StageName.MAP],
    CheckpointName.NORMALIZE: [StageName.MAP, StageName.NORMALIZE],
    CheckpointName.ENRICH:  [StageName.MAP, StageName.NORMALIZE, StageName.ENRICH],
    CheckpointName.MATCH:   [
        StageName.MAP,
        StageName.NORMALIZE,
        StageName.ENRICH,
        StageName.MY_STAGE,    # ← вставляем перед MATCH
        StageName.MATCH,
    ],
    CheckpointName.RESOLVE_CONTEXT: [
        StageName.MAP,
        StageName.NORMALIZE,
        StageName.ENRICH,
        StageName.MY_STAGE,    # ← и здесь тоже
        StageName.MATCH,
        StageName.RESOLVE_CONTEXT,
    ],
    # ... аналогично для RESOLVE и PLAN
}
```

> **Важно**: если стадия входит в несколько чекпоинтов — обнови **каждый** из них.
> `PipelineComposer.compose()` берёт список стадий из `PIPELINE_CHECKPOINTS` буквально.

### Новый сценарий без нового checkpoint

Если новая стадия просто входит в существующую цепочку — новый `CheckpointName` не нужен.
Добавляй `CheckpointName` только если нужно останавливать pipeline на этой стадии (новая команда).

---

## Тест-стратегия

### 1. Unit-тест стадии

Тестируй `Stage.run()` напрямую с моком engine:

```python
# tests/unit/transform/test_my_stage.py

from unittest.mock import Mock
from connector.domain.transform.stages.stages import MyStage
from connector.domain.transform.core.result import TransformResult


def _make_ok_result(**kwargs) -> TransformResult:
    """Helper: TransformResult с row."""
    return TransformResult(row=Mock(), record=Mock(), **kwargs)


def _make_error_result() -> TransformResult:
    """Helper: TransformResult с errors (row=None)."""
    return TransformResult(row=None, record=Mock(), errors=(Mock(),))


class TestMyStageRun:
    def test_passes_through_error_records(self):
        """row=None пропускается без обработки engine."""
        stage = MyStage(engine=Mock(), catalog=Mock())
        error_rec = _make_error_result()

        results = list(stage.run([error_rec]))

        assert len(results) == 1
        assert results[0].row is None
        stage.engine.process.assert_not_called()

    def test_processes_ok_record(self):
        """row не None — engine.process() вызывается."""
        engine = Mock()
        engine.process.return_value = _make_ok_result()
        stage = MyStage(engine=engine, catalog=Mock())

        results = list(stage.run([_make_ok_result()]))

        assert len(results) == 1
        engine.process.assert_called_once()

    def test_blocks_record_on_engine_none(self):
        """engine.process() → None → запись блокируется (row=None)."""
        engine = Mock()
        engine.process.return_value = None
        stage = MyStage(engine=engine, catalog=Mock())

        results = list(stage.run([_make_ok_result()]))

        assert len(results) == 1
        assert results[0].row is None
```

### 2. Архитектурный тест (statelessness)

Добавь стадию в `tests/unit/transform/test_pipeline_architecture.py`:

```python
from connector.domain.transform.stages.stages import MyStage

def test_invariant_stages_are_stateless():
    # ... существующий тест ...
    my_stage = MyStage(engine=Mock(), catalog=catalog)
    stages = [..., my_stage]
    # тест проверяет отсутствие mutable state (кроме engine + catalog)
```

### 3. Тест StageFactory stub (Путь 2)

```python
# tests/unit/delivery/test_stage_factory.py (или аналогичный)

def test_my_stage_registered_in_factory():
    """my_stage зарегистрирована в StageFactory (introspection)."""
    from connector.delivery.cli.pipeline_registry import build_stage_factory
    factory = build_stage_factory()
    assert "my_stage" in factory.registered_types


def test_my_stage_create_raises_not_implemented():
    """StageFactory.create('my_stage') → NotImplementedError (Singleton в PipelineContainer)."""
    from connector.delivery.cli.pipeline_registry import build_stage_factory
    import pytest
    factory = build_stage_factory()
    with pytest.raises(NotImplementedError):
        factory.create("my_stage", spec=Mock(), context=Mock())
```

### 4. Тест PipelineComposer

```python
# tests/unit/delivery/test_pipeline_composer.py

def test_compose_includes_my_stage():
    """checkpoint включает my_stage."""
    from connector.delivery.cli.pipeline_config import CheckpointName, PIPELINE_CHECKPOINTS, StageName
    assert StageName.MY_STAGE in PIPELINE_CHECKPOINTS[CheckpointName.MATCH]
```

### 5. Запустить тесты

```bash
.venv/bin/python -m pytest tests/unit/ -x -q
```

Все 580+ тестов должны быть зелёными.

---

## Чек-лист

### Путь 1 (StageFactory)

- [ ] Engine создан в `connector/domain/transform/`
- [ ] Stage создан в `stages/stages.py` или отдельном модуле
- [ ] `if item.row is None: yield item; continue` добавлен в `run()`
- [ ] `_my_engine_factory` и `_stage_wrapper(MyStage)` в `pipeline_registry.py`
- [ ] `StageDescriptor` зарегистрирован в `build_stage_factory()`
- [ ] `StageName.MY_STAGE = "my_stage"` добавлен в `pipeline_config.py`
- [ ] `my_options` provider добавлен в `PipelineContainer` (если нужны build options)
- [ ] `my_stage = providers.Factory(_create_stage, ...)` добавлен в `PipelineContainer`
- [ ] `StageName.MY_STAGE: my_stage` добавлен в `stage_registry` в `pipeline_composer`
- [ ] `StageName.MY_STAGE` вставлен в нужные чекпоинты в `PIPELINE_CHECKPOINTS`
- [ ] Unit-тест `Stage.run()` написан
- [ ] Добавлено в `test_invariant_stages_are_stateless`
- [ ] Тесты зелёные

### Путь 2 (Singleton)

- [ ] Engine создан в `connector/domain/transform/`
- [ ] Stage создан в `stages/stages.py` или отдельном модуле
- [ ] `if item.row is None: yield item; continue` добавлен в `run()` (если применимо)
- [ ] `_my_engine = providers.Singleton(...)` добавлен в `PipelineContainer`
- [ ] `my_stage = providers.Singleton(...)` добавлен в `PipelineContainer`
- [ ] `StageName.MY_STAGE: my_stage` добавлен в `stage_registry` в `pipeline_composer`
- [ ] `StageName.MY_STAGE = "my_stage"` добавлен в `pipeline_config.py`
- [ ] Stub (`NotImplementedError`) зарегистрирован в `build_stage_factory()` для introspection
- [ ] `StageName.MY_STAGE` вставлен в нужные чекпоинты в `PIPELINE_CHECKPOINTS`
- [ ] Unit-тест `Stage.run()` написан
- [ ] Тест stub `NotImplementedError` написан
- [ ] Тесты зелёные

---

## Частые ошибки

### KeyError при compose()

```
KeyError: 'my_stage'
```

**Причина**: `StageName.MY_STAGE` добавлен в `PIPELINE_CHECKPOINTS`, но не добавлен в
`stage_registry` в `pipeline_composer`.

**Решение**: убедись, что `stage_registry` в `pipeline_composer` содержит
`StageName.MY_STAGE: my_stage`.

---

### Стадия материализуется раньше override()-контекста

**Симптом**: стадия получает `dataset_spec` из предыдущей команды или `None`.

**Причина**: `providers.Dict` разрешает значения eager — при создании Singleton-а,
а не при вызове `compose()`.

**Решение**: `stage_registry` должен быть обычным `dict` с provider-объектами как значениями
(не `providers.Dict`). `compose()` вызывает `self._stages[name]()` уже в активном override()-контексте.

---

### Stage не является stateless

**Симптом**: второй вызов команды возвращает результаты от первого; тест
`test_invariant_stages_are_stateless` падает.

**Причина**: Stage хранит per-run состояние (список, счётчик) в instance-атрибуте.

**Решение**: per-run состояние — только в Engine через Singleton (Путь 2) с явным `reset()`.
Stage должен быть stateless functor: только engine-ссылки и catalog.

---

### row=None не передаётся дальше

**Симптом**: записи с ошибками исчезают или вызывают `AttributeError` в твоей стадии.

**Причина**: в `run()` нет проверки `if item.row is None`.

**Решение**: первая строка inner-loop:

```python
if item.row is None:
    yield item
    continue
```

---

### MissingCapabilityError при создании engine

```
MissingCapabilityError: Capability MyServicePort is not available.
```

**Причина**: `required_capabilities=frozenset({MyServicePort})` в `StageDescriptor`, но стадия
использует `transform_context` без этого capability.

**Решение**: либо добавь capability в соответствующий context-билдер, либо используй
`enrich_context` / `planning_context`, либо создай новый context с нужным capability.

---

## Связанные документы

- [ADR TRANSFORM-DEC-007](../../adr/transform/TRANSFORM-DEC-007-declarative-pipeline-checkpoints.md) — архитектурное решение по чекпоинтам
- [ADR TRANSFORM-DEC-004](../../adr/transform/TRANSFORM-DEC-004-modular-pipeline-scoped-execution-context.md) — StageContract и StageExecutionContext
- [Тест-гайд](testing-guide.md) — общие паттерны тестирования
