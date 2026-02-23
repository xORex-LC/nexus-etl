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

# Единственное место истины о составе пайплайнов.
# Добавить стадию = одна строка в нужных сценариях.
PIPELINE_CHECKPOINTS: dict[str, list[str]] = {
    "normalize": ["map_stage", "normalize_stage"],
    "enrich":    ["map_stage", "normalize_stage", "enrich_stage"],
    "match":     ["map_stage", "normalize_stage", "enrich_stage", "match_stage"],
    "plan":      ["map_stage", "normalize_stage", "enrich_stage", "match_stage", "resolve_stage"],
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
    """

    def __init__(
        self,
        stage_registry: dict[str, Callable[[], StageContract]],
        checkpoints: dict[str, list[str]],
    ) -> None:
        self._stages = stage_registry
        self._checkpoints = checkpoints

    def compose(self, checkpoint: str) -> PipelineOrchestrator:
        """Собрать конвейер до указанного чекпоинта включительно."""
        stage_names = self._checkpoints[checkpoint]
        stages = [self._stages[name]() for name in stage_names]
        return PipelineOrchestrator(stages)

    def compose_up_to(self, before: str) -> PipelineOrchestrator:
        """Собрать конвейер из стадий, предшествующих чекпоинту (не включая его)."""
        plan_stages = self._checkpoints["plan"]
        cutoff = plan_stages.index(before)
        stages = [self._stages[name]() for name in plan_stages[:cutoff]]
        return PipelineOrchestrator(stages)
```

### Компонент 3: AppContainer владеет реестром и composer-ом

```python
# connector/delivery/cli/containers.py (AppContainer)

class AppContainer(DeclarativeContainer):
    ...

    pipeline_checkpoints = providers.Object(PIPELINE_CHECKPOINTS)

    pipeline_composer = providers.Factory(
        PipelineComposer,
        stage_registry=providers.Dict({
            "map_stage":       pipeline.map_stage,
            "normalize_stage": pipeline.normalize_stage,
            "enrich_stage":    pipeline.enrich_stage,
            "match_stage":     pipeline.match_stage,
            "resolve_stage":   pipeline.resolve_stage,
        }),
        checkpoints=pipeline_checkpoints,
    )
```

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
        transform = self._composer.compose_up_to("match_stage")  # map+normalize+enrich
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

### CLI-команды через AppContainer

```python
# connector/delivery/commands/normalize.py
composer = app.pipeline_composer()
pipeline = composer.compose("normalize")   # → PipelineOrchestrator([map, normalize])

# connector/delivery/commands/import_plan.py
planning_pipeline = app.pipeline.planning_pipeline()   # PipelineContainer.Factory(PlanningPipeline, composer=...)
with planning_pipeline.open(run_id=run_id, ...) as resolved_rows:
    service.run(resolved_rows=resolved_rows, ...)
```

### Поток сборки

```
PIPELINE_CHECKPOINTS  +  PipelineContainer (stage factories)
           ↓                       ↓
       AppContainer.pipeline_composer (providers.Factory(PipelineComposer))
                       ↓
          composer.compose("enrich")  →  PipelineOrchestrator([map, normalize, enrich])
          composer.compose_up_to("match_stage")  →  PipelineOrchestrator([map, normalize, enrich])

                   Lifecycle-aware сценарии (планнер):
          PlanningPipeline(composer, match_stage, resolve_stage)
                       ↓
          planning_pipeline.open(run_id, planning_runtime)
                 ├─ composer.compose_up_to("match_stage") → transform segment
                 ├─ open_match_runtime(match_stage)        → lifecycle
                 └─ ResolveUseCase.iter_resolved(pending_replay)
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ `AppContainer` — единственное место истины о сценариях; добавить стадию = одна строка в `PIPELINE_CHECKPOINTS` + новый провайдер в `PipelineContainer`
- ✅ `PipelineContainer` остаётся pure DI (не знает о сценариях, только о стадиях)
- ✅ OCP: delivery-команды не меняются при добавлении стадий — они запрашивают `compose("enrich")`, а не перечисляют стадии вручную
- ✅ Путь к DSL: `PIPELINE_CHECKPOINTS` — Python dict, заменимый загрузкой из YAML по аналогии с transform DSL
- ✅ Путь к routing: когда `TransformResult` перестанет нести типизированный `row`, составной граф стадий можно будет выразить в том же реестре

**Недостатки (компромиссы)**:
- ⚠️ `match_stage` перечислен в чекпоинте `plan`, но его lifecycle (scope cleanup) не выражается в словаре — `PlanningPipeline` по-прежнему получает `match_stage` явно. Это conscious exception: lifecycle — это не вопрос состава стадий, это вопрос resource management
- ⚠️ `PipelineComposer.compose_up_to()` знает имя стадии `"match_stage"` как строку — хрупко при переименовании. Митигация: typed enum `StageName` или константы

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
| `connector/delivery/cli/pipeline_config.py` | Новый: `PIPELINE_CHECKPOINTS` dict |
| `connector/delivery/cli/pipeline_composer.py` | Новый: `PipelineComposer` класс |
| `connector/delivery/cli/containers.py` | `AppContainer` добавляет `pipeline_checkpoints`, `pipeline_composer` провайдеры |
| `connector/delivery/pipelines/planning_pipeline.py` | Уточнение DEC-006: получает `composer: PipelineComposer` вместо списка стадий |
| `connector/delivery/commands/*.py` | Команды используют `composer.compose(checkpoint)` вместо ручной сборки |
| `tests/unit/delivery/test_pipeline_composer.py` | Тесты `compose()`, `compose_up_to()`, неизвестный чекпоинт |

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
| `PipelineContainer` | Минимальное | Убрать `transform_segment()` (если добавлялся в DEC-006); остаётся pure DI |
| `PlanningPipeline` | Уточнение | Принимает `composer` вместо отдельных stage-аргументов для transform-части |
| CLI-команды | Упрощение | Заменить ручную сборку на `composer.compose(checkpoint)` |
| `planning_match_runtime.py` | Перемещение | Поглощается `PlanningPipeline.open()` (DEC-006) |

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
| 2026-02-23 | Решение предложено при обсуждении DEC-006 |
| 2026-02-23 | Принято; реализация запланирована после DEC-006 + PLANNER-DEC-001 |
