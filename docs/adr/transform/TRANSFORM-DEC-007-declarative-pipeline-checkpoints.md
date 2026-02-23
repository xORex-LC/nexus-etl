# TRANSFORM-DEC-007: Декларативный реестр чекпоинтов в AppContainer + PipelineComposer

> **Статус**: Открыто (реализация после PLANNER-DEC-001 + TRANSFORM-DEC-006)
> **Дата принятия**: 2026-02-23
> **Решает проблему**: [TRANSFORM-PROBLEM-007](./TRANSFORM-PROBLEM-007-pipeline-composition-hardcoded-imperatively.md)
> **Зависит от**: [TRANSFORM-DEC-006](./TRANSFORM-DEC-006-pipeline-segments-in-container.md), [PLANNER-DEC-001](../planner/PLANNER-DEC-001-pending-replay-at-resolve-boundary.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

После TRANSFORM-DEC-006 состав конвейера для каждого сценария по-прежнему задаётся императивно в Python-коде (`PlanningPipeline`, delivery-команды). Единого декларативного места истины нет. Это блокирует OCP при добавлении стадий, DSL-конфигурацию пайплайна и будущий routing.

---

## 🎯 Решение

`AppContainer` как истинный Composition Root владеет декларативным реестром чекпоинтов `PIPELINE_CHECKPOINTS` — словарём, отображающим имя сценария в упорядоченный список имён стадий. `PipelineComposer` использует этот реестр и фабрики `PipelineContainer`, чтобы собрать `PipelineOrchestrator` для любого сценария без знания о конкретных типах стадий.

`PipelineContainer` остаётся "тупым" поставщиком стадий по имени. Знание о сценариях — исключительно в `AppContainer`.

---

## 🏗️ Архитектурное решение

### Компонент 1: PIPELINE_CHECKPOINTS — реестр чекпоинтов

```python
# connector/delivery/cli/pipeline_config.py


class StageName:
    """Константы имён стадий — единственное место определения строковых ключей.
    Опечатка в stage_registry или compose() ловится немедленно, не в runtime."""
    MAP      = "map_stage"
    NORMALIZE = "normalize_stage"
    ENRICH   = "enrich_stage"
    MATCH    = "match_stage"
    RESOLVE  = "resolve_stage"


class CheckpointName:
    """Константы имён чекпоинтов — ключи PIPELINE_CHECKPOINTS и аргументы compose()."""
    MAP       = "map"
    NORMALIZE = "normalize"
    ENRICH    = "enrich"
    MATCH     = "match"
    PLAN      = "plan"


# Единственное место истины о составе пайплайнов.
# Добавить стадию = одна строка в нужных сценариях.
# Каждый чекпоинт — кумулятивный: включает все предыдущие стадии.
PIPELINE_CHECKPOINTS: dict[str, list[str]] = {
    CheckpointName.MAP:       [StageName.MAP],
    CheckpointName.NORMALIZE: [StageName.MAP, StageName.NORMALIZE],
    CheckpointName.ENRICH:    [StageName.MAP, StageName.NORMALIZE, StageName.ENRICH],
    CheckpointName.MATCH:     [StageName.MAP, StageName.NORMALIZE, StageName.ENRICH, StageName.MATCH],
    CheckpointName.PLAN:      [StageName.MAP, StageName.NORMALIZE, StageName.ENRICH, StageName.MATCH, StageName.RESOLVE],
}
```

> **Примечание**: `match_stage` и `resolve_stage` присутствуют в `plan`-чекпоинте как имена стадий. Lifecycle stateful-части (match runtime scope cleanup) остаётся в `PlanningPipeline` (DEC-006) — это conscious exception, см. раздел «Ограничения».

### Компонент 2: PipelineComposer

```python
# connector/delivery/cli/pipeline_composer.py

class PipelineComposer:
    """
    Собирает PipelineOrchestrator из реестра чекпоинтов и фабрик стадий.
    Не знает о бизнес-сценариях — только о том, как создать стадию по имени.

    stage_registry содержит ссылки на DI-провайдеры (callable), а не инстансы.
    Стадии материализуются лениво при вызове compose() — внутри override()-контекста команды.
    """

    def __init__(
        self,
        stage_registry: dict[str, Callable[[], StageContract]],
        checkpoints: dict[str, list[str]],
    ) -> None:
        self._stages = stage_registry
        self._checkpoints = checkpoints

    def compose(self, checkpoint: str) -> PipelineOrchestrator:
        """Собрать конвейер для указанного чекпоинта включительно.

        Вызывается внутри override()-контекста команды, чтобы provider-ссылки
        разрешались с актуальными dataset_spec, run_id и пр.
        """
        stage_names = self._checkpoints[checkpoint]
        stages = [self._stages[name]() for name in stage_names]
        return PipelineOrchestrator(stages)
```

> **Почему нет `compose_up_to`**: метод был бы эквивалентен `compose(CheckpointName.ENRICH)` —
> чекпоинт `enrich` уже задаёт ровно `[map, normalize, enrich]`. Если нужен другой сегмент,
> правильный путь — добавить именованный чекпоинт в `PIPELINE_CHECKPOINTS`, а не срезать
> по индексу с хрупким строковым поиском (`plan_stages.index("match_stage")`).

### Компонент 3: AppContainer владеет реестром и composer-ом

```python
# connector/delivery/cli/containers.py (AppContainer)

class AppContainer(DeclarativeContainer):
    ...

    # providers.Object — точка подмены в будущем: загрузка из YAML вместо Python-dict
    pipeline_checkpoints = providers.Object(PIPELINE_CHECKPOINTS)

    # providers.Singleton: PipelineComposer stateless, создаётся один раз на invocation.
    # stage_registry — plain Python dict (НЕ providers.Dict!): provider-ссылки передаются
    # как callable, а не разрешаются eager. Стадии материализуются позже, внутри compose().
    pipeline_composer = providers.Singleton(
        PipelineComposer,
        stage_registry={
            StageName.MAP:      pipeline.map_stage,
            StageName.NORMALIZE: pipeline.normalize_stage,
            StageName.ENRICH:   pipeline.enrich_stage,
            StageName.MATCH:    pipeline.match_stage,
            StageName.RESOLVE:  pipeline.resolve_stage,
        },
        checkpoints=pipeline_checkpoints,
    )
```

> **Почему plain dict, не `providers.Dict`**: `providers.Dict` разрешает все значения **eager**
> при вызове `pipeline_composer()` — в `stage_registry` попали бы уже созданные инстансы стадий,
> и `compose()` при попытке `self._stages[name]()` получил бы `TypeError`.
> Plain dict передаётся dependency-injector как есть; provider-объекты внутри него остаются
> callable и разрешаются лениво внутри `compose()` — уже под активными `override()`-контекстами.

### Компонент 4: PlanningPipeline использует PipelineComposer

```python
# connector/delivery/pipelines/planning_pipeline.py (DEC-006, уточнение)

class PlanningPipeline:
    def __init__(self, composer: PipelineComposer, match_stage: MatchStage, resolve_stage: ResolveStage):
        self._composer = composer
        self._match_stage = match_stage
        self._resolve_stage = resolve_stage

    @contextmanager
    def open(self, *, run_id, planning_runtime, ...) -> Iterator[Iterable[TransformResult]]:
        # compose("enrich") = [map, normalize, enrich] — явный чекпоинт, не хрупкий срез по индексу
        transform = self._composer.compose(CheckpointName.ENRICH)
        enriched = iter_ok(transform.run(extractor.run()), ...)

        with open_match_runtime(match_stage=self._match_stage, ...) as match_runtime:
            matched = iter_matched_ok(runtime=match_runtime, enriched_source=enriched)
            resolved = resolve_usecase.iter_resolved(
                matched_source=matched,
                resolve_stage=self._resolve_stage,
                pending_replay=planning_runtime,
            )
            yield iter_ok(resolved)
```

### Компонент 5: Use-cases принимают PipelineOrchestrator вместо индивидуальных стадий

До DEC-007 `NormalizeUseCase`, `EnrichUseCase`, `MappingUseCase` принимали стадии по отдельности
и сами собирали `PipelineOrchestrator` внутри — дублируя знание о порядке стадий, которое должно
жить исключительно в `PIPELINE_CHECKPOINTS`.

```python
# connector/usecases/normalize_usecase.py

class NormalizeUseCase:
    def run(
        self,
        row_source,
        pipeline: PipelineOrchestrator,   # было: map_stage: MapStage, normalize_stage: NormalizeStage
        ...
    ) -> CommandResult:
        extractor = Extractor(row_source, catalog=catalog)
        for result in pipeline.run(extractor.run()):   # не знает, какие стадии внутри
            processor.process(result)
```

```python
# connector/usecases/enrich_usecase.py

class EnrichUseCase:
    def run(
        self,
        row_source,
        pipeline: PipelineOrchestrator,   # было: map_stage, normalize_stage, enrich_stage
        ...
    ) -> CommandResult:
        extractor = Extractor(row_source, catalog=catalog)
        for result in pipeline.run(extractor.run()):
            processor.process(result)
```

```python
# connector/usecases/mapping_usecase.py

class MappingUseCase:
    def run(
        self,
        row_source,
        pipeline: PipelineOrchestrator,   # было: map_stage: MapStage
        ...
    ) -> CommandResult:
        extractor = Extractor(row_source, catalog=catalog)
        for result in pipeline.run(extractor.run()):   # было: map_stage.run(extractor.run())
            processor.process(result)
```

> **Инвариант**: use-case не знает о составе стадий — только о том, что у него есть готовый
> `PipelineOrchestrator`. Знание «какие стадии, в каком порядке» принадлежит исключительно
> `PIPELINE_CHECKPOINTS` + `PipelineComposer` в delivery-слое.

### CLI-команды через AppContainer

После DEC-007 все команды используют единую модель: `composer.compose(checkpoint)` → `PipelineOrchestrator`.

```python
# connector/delivery/commands/mapping.py
composer = ctx.container.pipeline_composer()
usecase.run(
    row_source=pipeline.row_source(),
    pipeline=composer.compose(CheckpointName.MAP),
    ...
)

# connector/delivery/commands/normalize.py
usecase.run(
    row_source=pipeline.row_source(),
    pipeline=composer.compose(CheckpointName.NORMALIZE),
    ...
)

# connector/delivery/commands/enrich.py
usecase.run(
    row_source=pipeline.row_source(),
    pipeline=composer.compose(CheckpointName.ENRICH),
    ...
)

# connector/delivery/commands/match.py  (и аналогично resolve.py)
enriched_rows = iter_ok(
    composer.compose(CheckpointName.ENRICH).run(Extractor(row_source, ...).run()),
)
# Дальше — open_match_runtime(...) как прежде

# connector/delivery/commands/import_plan.py
planning_pipeline = app.pipeline.planning_pipeline()
with planning_pipeline.open(run_id=run_id, ...) as resolved_rows:
    service.run(resolved_rows=resolved_rows, ...)
```

### Поток сборки

```
PIPELINE_CHECKPOINTS  +  PipelineContainer (stage factories)
           ↓                       ↓
       AppContainer.pipeline_composer (providers.Singleton(PipelineComposer))
         stage_registry = plain dict {StageName.X: pipeline.x_stage, ...}  ← provider-ссылки
                       ↓
          composer.compose(CheckpointName.MAP)      →  PipelineOrchestrator([map])
          composer.compose(CheckpointName.NORMALIZE) →  PipelineOrchestrator([map, normalize])
          composer.compose(CheckpointName.ENRICH)   →  PipelineOrchestrator([map, normalize, enrich])
          composer.compose(CheckpointName.MATCH)    →  PipelineOrchestrator([map, normalize, enrich, match])

                   Единая модель для всех команд:
          command → composer.compose(checkpoint) → PipelineOrchestrator
                                                          ↓
                                              usecase.run(pipeline=orchestrator, ...)
                                              pipeline.run(extractor.run())

                   Lifecycle-aware сценарии (планнер):
          PlanningPipeline(composer, match_stage, resolve_stage)
                       ↓
          planning_pipeline.open(run_id, planning_runtime)
                 ├─ composer.compose(CheckpointName.ENRICH) → transform segment
                 ├─ open_match_runtime(match_stage)          → lifecycle
                 └─ ResolveUseCase.iter_resolved(pending_replay)
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ `AppContainer` — единственное место истины о сценариях; добавить стадию = одна строка в `PIPELINE_CHECKPOINTS` + новый провайдер в `PipelineContainer`
- ✅ `PipelineContainer` остаётся pure DI (не знает о сценариях, только о стадиях)
- ✅ OCP: **все** delivery-команды не меняются при добавлении стадий — они запрашивают `compose(checkpoint)`, а не перечисляют стадии вручную
- ✅ Единая модель для всех 6 команд: `composer.compose(checkpoint)` → `PipelineOrchestrator` → `usecase.run(pipeline=...)`; use-cases не знают о составе стадий
- ✅ Путь к DSL: `PIPELINE_CHECKPOINTS` — Python dict, заменимый загрузкой из YAML по аналогии с transform DSL
- ✅ Путь к routing: когда `TransformResult` перестанет нести типизированный `row`, составной граф стадий можно будет выразить в том же реестре

**Недостатки (компромиссы)**:
- ⚠️ `match_stage` перечислен в чекпоинте `plan`, но его lifecycle (scope cleanup) не выражается в словаре — `PlanningPipeline` по-прежнему получает `match_stage` явно. Это conscious exception: lifecycle — это не вопрос состава стадий, это вопрос resource management
- ⚠️ Имена стадий и чекпоинтов — строки; опечатка даст `KeyError` в runtime. Митигация: `StageName` / `CheckpointName` константы в `pipeline_config.py` — единственное место определения этих строк

**Альтернативы, которые отклонили**:
- ❌ **Hardcoded в PlanningPipeline/команды (статус-кво после DEC-006)**: не решает OCP, нет пути к DSL
- ❌ **DSL (YAML) сразу**: преждевременно — требует generalization `TransformResult.row` и lifecycle-хуков в YAML; слишком большой scope

---

## 📐 Будущая эволюция: DSL-конфигурация пайплайна

Следующий шаг после реализации DEC-007 — загрузка `PIPELINE_CHECKPOINTS` из YAML:

```yaml
# datasets/pipeline.yaml (будущее)
checkpoints:
  normalize:
    stages: [map_stage, normalize_stage]
  enrich:
    stages: [map_stage, normalize_stage, enrich_stage]
  plan:
    stages: [map_stage, normalize_stage, enrich_stage, match_stage, resolve_stage]
    lifecycle:
      match_stage: open_match_runtime   # будущий механизм lifecycle-хуков
```

Это разблокирует:
- **Routing**: `if row.state == "unresolved" → resolve_stage, else → skip`
- **Conditional stages**: включение/выключение стадии через конфиг без изменения кода
- **Multi-pipeline datasets**: разные чекпоинты для разных датасетов

**Prerequisite для DSL**: устранение типизированной привязки `TransformResult.row` к конкретному типу стадии (сейчас `MatchStage` ожидает `row: EnrichedRow` внутри). До этого произвольный reordering невозможен.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/delivery/cli/pipeline_config.py` | Новый: `StageName`, `CheckpointName`, `PIPELINE_CHECKPOINTS` |
| `connector/delivery/cli/pipeline_composer.py` | Новый: `PipelineComposer` класс |
| `connector/delivery/cli/containers.py` | `AppContainer` добавляет `pipeline_checkpoints`, `pipeline_composer` провайдеры |
| `connector/delivery/cli/pipeline_registry.py` | Удалить `build_transform_segment` (dead code после DEC-007) |
| `connector/delivery/pipelines/planning_pipeline.py` | Получает `composer: PipelineComposer` вместо `transform_segment: PipelineOrchestrator` |
| `connector/delivery/commands/mapping.py` | Индивидуальные стадии → `composer.compose(CheckpointName.MAP)` |
| `connector/delivery/commands/normalize.py` | Индивидуальные стадии → `composer.compose(CheckpointName.NORMALIZE)` |
| `connector/delivery/commands/enrich.py` | Индивидуальные стадии → `composer.compose(CheckpointName.ENRICH)` |
| `connector/delivery/commands/match.py` | `transform_segment()` → `composer.compose(CheckpointName.ENRICH)` |
| `connector/delivery/commands/resolve.py` | то же |
| `connector/usecases/mapping_usecase.py` | `map_stage: MapStage` → `pipeline: PipelineOrchestrator` |
| `connector/usecases/normalize_usecase.py` | `map_stage, normalize_stage` → `pipeline: PipelineOrchestrator` |
| `connector/usecases/enrich_usecase.py` | `map_stage, normalize_stage, enrich_stage` → `pipeline: PipelineOrchestrator` |
| `tests/unit/delivery/test_pipeline_composer.py` | Тесты `compose()` для каждого чекпоинта, несуществующий чекпоинт |
| `tests/unit/usecases/test_{mapping,normalize,enrich}_usecase.py` | Обновить: передавать `PipelineOrchestrator` вместо индивидуальных стадий |

### Инварианты

1. **`PIPELINE_CHECKPOINTS`** — единственное место, где перечислены stage name sequences
2. **`PipelineComposer`** не знает о бизнес-сценариях — только маппит имена стадий на фабрики
3. **`PipelineContainer`** не знает о `PIPELINE_CHECKPOINTS` — pure DI
4. **Lifecycle stateful-стадий** (match scope) остаётся в `PlanningPipeline`, не выражается в реестре

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `AppContainer` | Расширение | Добавить `pipeline_checkpoints`, `pipeline_composer` провайдеры |
| `PipelineContainer` | Минимальное | Удалить `transform_segment` provider (dead code); добавить `pipeline_composer` как `Dependency` для `planning_pipeline` |
| `PlanningPipeline` | Уточнение | Принимает `composer: PipelineComposer` вместо `transform_segment: PipelineOrchestrator` |
| `match.py`, `resolve.py` | Упрощение | `transform_segment()` → `composer.compose(CheckpointName.ENRICH)` |
| `mapping.py`, `normalize.py`, `enrich.py` | Упрощение | Индивидуальные стадии → `composer.compose(checkpoint)`; передавать `PipelineOrchestrator` в use-case |
| `MappingUseCase`, `NormalizeUseCase`, `EnrichUseCase` | Упрощение сигнатуры | Индивидуальные stage-аргументы → `pipeline: PipelineOrchestrator`; убрать внутреннюю сборку оркестратора |
| `pipeline_registry.py` | Удаление | `build_transform_segment` становится мёртвым кодом, удалить |

---

## 🔗 Связанные документы

- [TRANSFORM-PROBLEM-007](./TRANSFORM-PROBLEM-007-pipeline-composition-hardcoded-imperatively.md) — решаемая проблема
- [TRANSFORM-DEC-006](./TRANSFORM-DEC-006-pipeline-segments-in-container.md) — prerequisite (PlanningPipeline)
- [PLANNER-DEC-001](../planner/PLANNER-DEC-001-pending-replay-at-resolve-boundary.md) — prerequisite (pending_codec)
- [TRANSFORM-DEC-004](./TRANSFORM-DEC-004-modular-pipeline-scoped-execution-context.md) — базовая pipeline-архитектура

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-21 | Решение предложено при обсуждении DEC-006 |
| 2026-02-22 | Принято; реализация запланирована после DEC-006 + PLANNER-DEC-001 |
| 2026-02-23 | Описано решение для достижения консистентности путём полной миграции map/normalize/enrich стадий на PipelineOrchestrator |
