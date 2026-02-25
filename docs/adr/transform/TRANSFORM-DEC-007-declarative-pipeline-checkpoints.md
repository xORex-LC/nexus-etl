# TRANSFORM-DEC-007: Декларативный реестр чекпоинтов в AppContainer + PipelineComposer

> **Статус**: Принято / Реализовано
> **Дата принятия**: 2026-02-23
> **Решает проблему**: [TRANSFORM-PROBLEM-007](./TRANSFORM-PROBLEM-007-pipeline-composition-hardcoded-imperatively.md)
> **Зависит от**: [TRANSFORM-DEC-006](./TRANSFORM-DEC-006-pipeline-segments-in-container.md), [PLANNER-DEC-001](../planner/PLANNER-DEC-001-pending-replay-at-resolve-boundary.md)
> **Зависит от (дополнительно)**: [MATCHER-DEC-002](../matcher/MATCHER-DEC-002-internalize-batch-execution-to-stage.md) — после реализации DEC-002 `open_match_runtime` удаляется из `PlanningPipeline`; `MatchStage` становится uniform StageContract-участником
> **Согласовано с**: [MATCHER-DEC-001](../matcher/MATCHER-DEC-001-externalize-dedup-state-to-di-service.md), [MATCHER-DEC-002](../matcher/MATCHER-DEC-002-internalize-batch-execution-to-stage.md), [RESOLVER-DEC-001](../resolver/RESOLVER-DEC-001-externalize-mechanics-to-di-services.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

После TRANSFORM-DEC-006 состав конвейера для каждого сценария по-прежнему задаётся императивно в Python-коде (`PlanningPipeline`, delivery-команды). Единого декларативного места истины нет. Это блокирует OCP при добавлении стадий, DSL-конфигурацию пайплайна и будущий routing.

После синхронных изменений SRP в matcher/resolver слоях (MATCHER-DEC-001, RESOLVER-DEC-001)
целевая модель DEC-007 распространяется на **все data-stage** (map → normalize → enrich → match
→ resolve_context → resolve), а не только на "transform-сегмент". При этом `PlanningPipeline`
дополнительно несёт lifecycle sidecars (match runtime cleanup, resolver hooks для housekeeping
expired pending). Это не отменяет цель DEC-007, но требует явно отделять: декларативный
**состав стадий** vs imperative **lifecycle orchestration**.

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
    RESOLVE_CONTEXT = "resolve_context_stage"
    RESOLVE  = "resolve_stage"


class CheckpointName:
    """Константы имён чекпоинтов — ключи PIPELINE_CHECKPOINTS и аргументы compose().

    Чекпоинты бывают двух типов:
    - stage-terminal (map/normalize/enrich/match/resolve)
    - scenario alias (plan) — может совпадать по stage-chain с terminal checkpoint
      и отличаться только lifecycle sidecars в orchestration wrapper.
    """
    MAP       = "map"
    NORMALIZE = "normalize"
    ENRICH    = "enrich"
    MATCH     = "match"
    RESOLVE   = "resolve"
    PLAN      = "plan"


# Единственное место истины о составе пайплайнов.
# Добавить стадию = одна строка в нужных сценариях.
# Каждый чекпоинт — кумулятивный: включает все предыдущие стадии.
PIPELINE_CHECKPOINTS: dict[str, list[str]] = {
    CheckpointName.MAP:       [StageName.MAP],
    CheckpointName.NORMALIZE: [StageName.MAP, StageName.NORMALIZE],
    CheckpointName.ENRICH:    [StageName.MAP, StageName.NORMALIZE, StageName.ENRICH],
    CheckpointName.MATCH:     [StageName.MAP, StageName.NORMALIZE, StageName.ENRICH, StageName.MATCH],
    CheckpointName.RESOLVE:   [
        StageName.MAP,
        StageName.NORMALIZE,
        StageName.ENRICH,
        StageName.MATCH,
        StageName.RESOLVE_CONTEXT,
        StageName.RESOLVE,
    ],
    CheckpointName.PLAN:      [
        StageName.MAP,
        StageName.NORMALIZE,
        StageName.ENRICH,
        StageName.MATCH,
        StageName.RESOLVE_CONTEXT,
        StageName.RESOLVE,
    ],
}
```

> **Примечание**: `CheckpointName.RESOLVE` и `CheckpointName.PLAN` могут иметь одинаковый stage-chain.
> Это не дублирование ответственности: `resolve` — stage-terminal checkpoint, `plan` — scenario alias
> (например для import_plan) с тем же составом стадий, но потенциально иными lifecycle sidecars.
>
> `match_stage`, `resolve_context_stage` и `resolve_stage` присутствуют в `plan`
> чекпоинте как имена стадий. Lifecycle sidecars (match runtime scope cleanup, resolver
> housekeeping hooks вроде `pending_expiry.sweep()` через `PipelineHooks`) остаются в
> `PlanningPipeline` — это conscious exception, см. раздел «Ограничения».

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
            StageName.RESOLVE_CONTEXT: pipeline.resolve_context_stage,
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

### Компонент 4: PlanningPipeline использует PipelineComposer (единый stage-chain + lifecycle sidecars)

После [MATCHER-DEC-002](../matcher/MATCHER-DEC-002-internalize-batch-execution-to-stage.md) `open_match_runtime` удаляется. Scope cleanup переходит в `PipelineHooks.on_stage_complete("match")` → `IMatchScopeService.clear_scope()`, встроенный в `plan_pipeline_hooks`. `PlanningPipeline` больше не принимает `match_stage` как отдельную зависимость.

```python
# connector/delivery/pipelines/planning_pipeline.py (после MATCHER-DEC-002 + DEC-007)

class PlanningPipeline:
    # Зависимости — только lifecycle sidecars (не порядок стадий):
    #   - composer: источник declarative stage-chain
    #   - plan_pipeline_hooks: PipelineHooks с on_stage_complete для "match" и "resolve"
    #     (match_scope.clear_scope() + pending_expiry.sweep() — из PlanningPipelineHooks)
    #   - pending_expiry: drain_expired() в finally (housekeeping после прогона)
    # match_stage отдельным параметром НЕТ — он встроен в compose(PLAN).
    def __init__(
        self,
        composer: PipelineComposer,
        plan_pipeline_hooks: PipelineHooks,   # on_stage_complete("match") + ("resolve")
        pending_expiry: IPendingExpiryService,
    ):
        self._composer = composer
        self._plan_hooks = plan_pipeline_hooks
        self._pending_expiry = pending_expiry

    @contextmanager
    def open(self, *, run_id, planning_runtime, ...) -> Iterator[Iterable[TransformResult]]:
        # Единый declarative stage-chain с hooks для обоих lifecycle sidecars.
        # PLAN — scenario alias; по data-stage составу совпадает с RESOLVE.
        plan_pipeline = self._composer.compose(CheckpointName.PLAN, hooks=self._plan_hooks)
        #   ↑ hooks.on_stage_complete("match") → match_scope.clear_scope()
        #   ↑ hooks.on_stage_complete("resolve") → pending_expiry.sweep()

        resolved_rows = resolve_usecase.iter_resolved(
            row_source=pipeline.row_source(),
            pipeline=plan_pipeline,
            pending_replay=planning_runtime,
            pending_expiry=self._pending_expiry,
        )
        try:
            yield resolved_rows
        finally:
            self._pending_expiry.drain_expired()
```

> **Инвариант DEC-007**: matcher/resolver стадии не являются исключением из композиции.
> `open_match_runtime` удалён после MATCHER-DEC-002. Единственные оставшиеся explicit sidecars —
> lifecycle hooks (через `PipelineHooks`) и `pending_expiry.drain_expired()` в finally.

> **MATCH команда — переходное состояние (DEC-002 до DEC-007)**:
> `match.py` использует явный `try/finally` с `match_scope.clear_scope()` вместо hooks,
> поскольку в этом сценарии `PipelineOrchestrator` ещё не применяется.
> Миграция: убрать `try/finally`, передать `plan_pipeline_hooks` в `compose(CheckpointName.MATCH, hooks=plan_pipeline_hooks)`.
> Подробнее — [MATCHER-DEC-002, раздел «Переходное состояние»](../matcher/MATCHER-DEC-002-internalize-batch-execution-to-stage.md).

### Компонент 5: Use-cases принимают PipelineOrchestrator вместо индивидуальных стадий (включая matcher/resolver)

До DEC-007 use-cases (и command-level orchestration вокруг них) частично принимают стадии по
отдельности и/или собирают сегменты pipeline вручную — включая matcher/resolver path. Это дублирует
знание о порядке стадий, которое должно жить исключительно в `PIPELINE_CHECKPOINTS`.

Для `MappingUseCase` / `NormalizeUseCase` / `EnrichUseCase` это прямой переход на
`pipeline: PipelineOrchestrator`.

Для `MatchUseCase` / `ResolveUseCase` целевая модель та же для **data-stage composition**:
они получают `PipelineOrchestrator` c checkpoint `MATCH` / `RESOLVE`, а lifecycle/reporting wrappers
(runtime cleanup, hooks, pending housekeeping, transactions) остаются отдельными зависимостями и
не подменяют собой composition-слой.

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

```python
# connector/usecases/match_usecase.py (target DEC-007 shape)

class MatchUseCase:
    def run(
        self,
        row_source,
        pipeline: PipelineOrchestrator,   # compose(CheckpointName.MATCH)
        report,
        ...
    ) -> CommandResult:
        ...
```

```python
# connector/usecases/resolve_usecase.py (target DEC-007 shape)

class ResolveUseCase:
    def run(
        self,
        row_source,
        pipeline: PipelineOrchestrator,   # compose(CheckpointName.RESOLVE) / PLAN alias
        report,
        *,
        # lifecycle sidecars остаются явными контрактами:
        pending_expiry: IPendingExpiryService,
        resolve_hooks: PipelineHooks,
        ...
    ) -> CommandResult:
        ...
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

# connector/delivery/commands/match.py
# plan_pipeline_hooks содержит on_stage_complete("match") → match_scope.clear_scope()
# (до DEC-007: match.py использовал явный try/finally — см. MATCHER-DEC-002)
match_usecase.run(
    row_source=pipeline.row_source(),
    pipeline=composer.compose(CheckpointName.MATCH, hooks=plan_pipeline_hooks),
    ...
)

# connector/delivery/commands/resolve.py
resolve_usecase.run(
    row_source=pipeline.row_source(),
    pipeline=composer.compose(CheckpointName.RESOLVE),  # или CheckpointName.PLAN как scenario alias
    ...,
    # lifecycle sidecars остаются explicit:
    pending_expiry=pipeline.pending_expiry(),
    resolve_hooks=pipeline.resolve_stage_hooks(),
)

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
          composer.compose(CheckpointName.RESOLVE)  →  PipelineOrchestrator([map, normalize, enrich, match, resolve_context, resolve])
          composer.compose(CheckpointName.PLAN)     →  PipelineOrchestrator([map, normalize, enrich, match, resolve_context, resolve])

                   Единая модель composition для всех стадий:
          command → composer.compose(checkpoint) → PipelineOrchestrator
                                                          ↓
                                              usecase.run(pipeline=orchestrator, ...)
                                              pipeline.run(extractor.run())

                   Lifecycle-aware сценарии (планнер):
          PlanningPipeline(composer, match_stage, resolve_stage_hooks, pending_expiry, ...)
                       ↓
          planning_pipeline.open(run_id, planning_runtime)
                 ├─ composer.compose(CheckpointName.PLAN)    → canonical stage-chain source
                 ├─ open_match_runtime(match_stage)           → lifecycle sidecar (match cleanup)
                 └─ resolve_usecase.iter_resolved(..., pipeline=PLAN, resolve_hooks=...)
                         ↳ pipeline contains ... → match → resolve_context → resolve
                         ↳ resolver hooks/pending expiry stay explicit sidecars
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ `AppContainer` — единственное место истины о сценариях; добавить стадию = одна строка в `PIPELINE_CHECKPOINTS` + новый провайдер в `PipelineContainer`
- ✅ `PipelineContainer` остаётся pure DI (не знает о сценариях, только о стадиях)
- ✅ OCP: **все** delivery-команды не меняются при добавлении стадий — они запрашивают `compose(checkpoint)`, а не перечисляют стадии вручную
- ✅ Единая модель composition для всех стадий (включая matcher/resolver): `composer.compose(checkpoint)` → `PipelineOrchestrator`; lifecycle sidecars не владеют порядком стадий
- ✅ `MatchUseCase` / `ResolveUseCase` перестают быть architectural exceptions в части stage composition: special-case остаётся только на уровне lifecycle/reporting wrappers
- ✅ Путь к DSL: `PIPELINE_CHECKPOINTS` — Python dict, заменимый загрузкой из YAML по аналогии с transform DSL
- ✅ Путь к routing: когда `TransformResult` перестанет нести типизированный `row`, составной граф стадий можно будет выразить в том же реестре

**Недостатки (компромиссы)**:
- ⚠️ `match_stage`, `resolve_context_stage` и `resolve_stage` перечислены в чекпоинте `plan`, но lifecycle sidecars (match runtime cleanup, resolver hooks для pending expiry housekeeping) не выражаются в словаре — `PlanningPipeline` по-прежнему получает соответствующие зависимости явно. Это conscious exception: lifecycle — это не вопрос состава стадий, это вопрос resource management
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
  resolve:
    stages: [map_stage, normalize_stage, enrich_stage, match_stage, resolve_context_stage, resolve_stage]
  plan:
    stages: [map_stage, normalize_stage, enrich_stage, match_stage, resolve_context_stage, resolve_stage]  # scenario alias to resolve-chain
    lifecycle:
      match_stage: open_match_runtime   # будущий механизм lifecycle-хуков
      resolve_stage.on_stage_complete: pending_expiry_sweep  # resolver housekeeping sidecar
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
| `connector/delivery/commands/match.py` | `transform_segment()`/ручная сборка match chain → `composer.compose(CheckpointName.MATCH)` |
| `connector/delivery/commands/resolve.py` | `transform_segment()`/ручная сборка resolve chain → `composer.compose(CheckpointName.RESOLVE)` (или `PLAN` как scenario alias) + lifecycle sidecars отдельными deps |
| `connector/usecases/mapping_usecase.py` | `map_stage: MapStage` → `pipeline: PipelineOrchestrator` |
| `connector/usecases/normalize_usecase.py` | `map_stage, normalize_stage` → `pipeline: PipelineOrchestrator` |
| `connector/usecases/enrich_usecase.py` | `map_stage, normalize_stage, enrich_stage` → `pipeline: PipelineOrchestrator` |
| `connector/usecases/match_usecase.py` | `enriched_source + match_stage` → `row_source + pipeline: PipelineOrchestrator` (checkpoint `MATCH`) + lifecycle/reporting wrappers |
| `connector/usecases/resolve_usecase.py` | `matched_source + resolve_stage` → `row_source + pipeline: PipelineOrchestrator` (checkpoint `RESOLVE`/`PLAN`) + lifecycle/reporting wrappers (`pending_expiry`, hooks, transactions) |
| `tests/unit/delivery/test_pipeline_composer.py` | Тесты `compose()` для каждого чекпоинта, несуществующий чекпоинт |
| `tests/unit/usecases/test_{mapping,normalize,enrich}_usecase.py` | Обновить: передавать `PipelineOrchestrator` вместо индивидуальных стадий |
| `tests/unit/usecases/test_{match,resolve}_usecase.py` | Добавить/обновить: use-case принимает `PipelineOrchestrator`, lifecycle wrappers тестируются отдельно от stage composition |

### Инварианты

1. **`PIPELINE_CHECKPOINTS`** — единственное место, где перечислены stage name sequences
2. **`PipelineComposer`** не знает о бизнес-сценариях — только маппит имена стадий на фабрики
3. **`PipelineContainer`** не знает о `PIPELINE_CHECKPOINTS` — pure DI
4. **CheckpointName.RESOLVE** — canonical stage-terminal checkpoint для полного data-stage chain до resolver
5. **CheckpointName.PLAN** — scenario alias (может совпадать по stage-chain с `resolve`), но не заменяет `resolve` как terminal checkpoint
6. **Lifecycle sidecars** (match runtime cleanup, resolver pending-expiry hooks) остаются в `PlanningPipeline`/delivery wrappers и не выражаются в реестре

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `AppContainer` | Расширение | Добавить `pipeline_checkpoints`, `pipeline_composer` провайдеры |
| `PipelineContainer` | Минимальное | Удалить `transform_segment` provider (dead code); добавить `pipeline_composer` как `Dependency` для `planning_pipeline` |
| `PlanningPipeline` | Уточнение | Принимает `composer: PipelineComposer` вместо `transform_segment: PipelineOrchestrator`; использует `CheckpointName.PLAN` как canonical source stage-chain, а lifecycle sidecars держит отдельно |
| `match.py`, `resolve.py` | Упрощение | Ручная сборка стадий/`transform_segment()` → `composer.compose(CheckpointName.MATCH/RESOLVE)` |
| `mapping.py`, `normalize.py`, `enrich.py` | Упрощение | Индивидуальные стадии → `composer.compose(checkpoint)`; передавать `PipelineOrchestrator` в use-case |
| `MappingUseCase`, `NormalizeUseCase`, `EnrichUseCase` | Упрощение сигнатуры | Индивидуальные stage-аргументы → `pipeline: PipelineOrchestrator`; убрать внутреннюю сборку оркестратора |
| `MatchUseCase`, `ResolveUseCase` | Уточнение сигнатур | Переход на `pipeline: PipelineOrchestrator` для stage composition; lifecycle/reporting wrappers остаются отдельными контрактами |
| `pipeline_registry.py` | Удаление | `build_transform_segment` становится мёртвым кодом, удалить |

---

## 🔗 Связанные документы

- [TRANSFORM-PROBLEM-007](./TRANSFORM-PROBLEM-007-pipeline-composition-hardcoded-imperatively.md) — решаемая проблема
- [TRANSFORM-DEC-006](./TRANSFORM-DEC-006-pipeline-segments-in-container.md) — prerequisite (PlanningPipeline)
- [PLANNER-DEC-001](../planner/PLANNER-DEC-001-pending-replay-at-resolve-boundary.md) — prerequisite (pending_codec)
- [MATCHER-DEC-001](../matcher/MATCHER-DEC-001-externalize-dedup-state-to-di-service.md) — SRP matcher: dedup lifecycle вынесен из MatchUseCase/MatchEngine в DI/store
- [RESOLVER-DEC-001](../resolver/RESOLVER-DEC-001-externalize-mechanics-to-di-services.md) — SRP resolver: ResolveContextStage + pending expiry hooks/lifecycle sidecars
- [TRANSFORM-DEC-004](./TRANSFORM-DEC-004-modular-pipeline-scoped-execution-context.md) — базовая pipeline-архитектура

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-21 | Решение предложено при обсуждении DEC-006 |
| 2026-02-22 | Принято; реализация запланирована после DEC-006 + PLANNER-DEC-001 |
| 2026-02-23 | Описано решение для достижения консистентности через чекпоинты и `PipelineComposer` (единая composition-модель для всех стадий — целевая форма DEC-007) |
| 2026-02-25 | ADR синхронизирован с MATCHER-DEC-001 / RESOLVER-DEC-001: добавлен `CheckpointName.RESOLVE`, `plan` оформлен как scenario alias к resolve-chain; matcher/resolver включены в единый checkpoint-driven composition, lifecycle sidecars явно отделены от реестра чекпоинтов |
| 2026-02-25 | Добавлена зависимость на MATCHER-DEC-002: `open_match_runtime` удаляется из `PlanningPipeline`; scope cleanup переезжает в `plan_pipeline_hooks`; `match_stage` больше не отдельный параметр `PlanningPipeline`; переходный паттерн `match.py` (явный `try/finally` до DEC-007) зафиксирован в MATCHER-DEC-002 |
