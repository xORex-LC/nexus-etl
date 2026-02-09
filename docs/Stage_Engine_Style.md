# Stage/Engine Style (Decision Log)

## Контекст
В коде есть смешение двух стилей:

1. `DatasetSpec` возвращает готовые стадии (`MapStage/NormalizeStage/EnrichStage`).
2. Для части стадий наружу просачиваются внутренние DSL-детали (или сборка делается в use-case/runtime).

Это снижает консистентность и читаемость.

## Принятое решение
Используем единый стиль:

1. `DatasetSpec` возвращает **готовые stage-объекты** для всех стадий.
2. `*Engine` скрывает DSL и является фасадом стадии.
3. Use-case слой только оркестрирует поток и runtime-параметры, но не собирает внутренности стадии.
4. Оставляем `build_transform_stages(...)` как convenience-агрегатор для стандартного конвейера `map -> normalize -> enrich`.
5. Добавляем `build_planning_stages(...)` как convenience-агрегатор для `match -> resolve`.
6. `SinkSpec` остаётся опциональным (`SinkSpec | None`).
7. Миграция выполняется единоразово, но пошагово (без долгоживущего legacy-слоя).

## Границы ответственности

### DatasetSpec
- собирает зависимости стадии;
- создаёт `*Engine`;
- оборачивает его в `*Stage`;
- возвращает готовую стадию.

### StageEngine
- компилирует stage-spec (через DSL внутри себя);
- создаёт `*Core`;
- предоставляет 1 публичный метод стадии (`map/normalize/enrich/match/resolve`).

### StageCore
- содержит бизнес-логику обработки записи;
- не знает про wiring/DI/use-case.

### Use-case / runtime
- задаёт `run_id`, scope, batch/flush;
- соединяет стадии в поток;
- пишет отчёт.

## Шаблон методов (псевдокод)

### Шаблон в `DatasetSpec`
```python
class DatasetSpec(Protocol):
    # Stage-spec builders (единый паттерн для всех стадий)
    def build_map_spec(self, settings=None) -> MapSpec: ...
    def build_normalize_spec(self, settings=None) -> NormalizeSpec: ...
    def build_enrich_spec(self, settings=None) -> EnrichSpec: ...
    def build_match_spec(self, settings=None) -> MatchSpec: ...
    def build_resolve_spec(self, settings=None) -> ResolveSpec: ...
    def build_sink_spec(self, settings=None) -> SinkSpec | None: ...

    # Convenience builder для базового transform-конвейера
    def build_transform_stages(
        self,
        *,
        catalog: ErrorCatalog,
        enrich_deps: TransformProviderDeps,
    ) -> tuple[MapStage, NormalizeStage, EnrichStage]: ...

    # Convenience builder для planning-конвейера
    def build_planning_stages(
        self,
        *,
        catalog: ErrorCatalog,
        planning_deps: PlanningDependencies,
        include_deleted: bool,
        settings=None,
    ) -> tuple[MatchStage, ResolveStage]: ...

    # Stage builders
    def build_map_stage(self, *, catalog: ErrorCatalog) -> MapStage: ...
    def build_normalize_stage(self, *, catalog: ErrorCatalog) -> NormalizeStage: ...
    def build_enrich_stage(
        self,
        *,
        catalog: ErrorCatalog,
        enrich_deps: TransformProviderDeps,
    ) -> EnrichStage: ...
    def build_match_stage(
        self,
        *,
        catalog: ErrorCatalog,
        planning_deps: PlanningDependencies,
        include_deleted: bool,
        settings=None,
    ) -> MatchStage: ...
    def build_resolve_stage(
        self,
        *,
        catalog: ErrorCatalog,
        planning_deps: PlanningDependencies,
        settings=None,
    ) -> ResolveStage: ...
```

### Шаблон агрегатора `build_transform_stages`
```python
def build_transform_stages(
    self,
    *,
    catalog: ErrorCatalog,
    enrich_deps: TransformProviderDeps,
) -> tuple[MapStage, NormalizeStage, EnrichStage]:
    return (
        self.build_map_stage(catalog=catalog),
        self.build_normalize_stage(catalog=catalog),
        self.build_enrich_stage(catalog=catalog, enrich_deps=enrich_deps),
    )
```

### Шаблон агрегатора `build_planning_stages`
```python
def build_planning_stages(
    self,
    *,
    catalog: ErrorCatalog,
    planning_deps: PlanningDependencies,
    include_deleted: bool,
    settings=None,
) -> tuple[MatchStage, ResolveStage]:
    return (
        self.build_match_stage(
            catalog=catalog,
            planning_deps=planning_deps,
            include_deleted=include_deleted,
            settings=settings,
        ),
        self.build_resolve_stage(
            catalog=catalog,
            planning_deps=planning_deps,
            settings=settings,
        ),
    )
```

### Шаблон реализации `build_*_stage` (пример)
```python
def build_normalize_stage(self, *, catalog: ErrorCatalog) -> NormalizeStage:
    spec = load_normalize_spec_for_dataset(self.dataset_name)
    sink_spec = load_sink_spec_for_dataset(self.dataset_name)
    engine = NormalizerEngine(
        spec=spec,
        catalog=catalog,
        registry=self._build_dsl_registry(),  # или engine=TransformationEngine(...)
        sink_spec=sink_spec,
        row_builder=NormalizedRowType,        # transitional, позже убрать
    )
    return NormalizeStage(engine, catalog)
```

### Шаблон `StageEngine`
```python
class NormalizerEngine:
    def __init__(
        self,
        *,
        spec: NormalizeSpec,
        catalog: ErrorCatalog,
        registry: OperationRegistry | None = None,
        sink_spec: SinkSpec | None = None,
        row_builder: RowBuilder | None = None,
    ) -> None:
        # NOTE: registry is test/migration hook. DatasetSpec must not pass it
        # in production path. Remove from public constructor after DSL stabilizes.
        registry = registry or build_default_registry()
        dsl = NormalizerDsl(registry=registry)      # скрыто внутри
        self.core = dsl.compile(
            spec,
            catalog=catalog,
            sink_spec=sink_spec,
            row_builder=row_builder,
        )

    def normalize(self, item: TransformResult) -> TransformResult:
        return self.core.normalize(item)
```

### Шаблон internal helper для shared-compile (пример resolve)
```python
class EmployeesSpec:
    def build_resolve_spec(self, settings=None) -> ResolveSpec:
        ...

    def build_resolve_rules(self, settings=None) -> ResolveRules:
        return self._compile_resolve(settings).resolve_rules

    def build_link_rules(self, settings=None) -> LinkRules:
        return self._compile_resolve(settings).link_rules

    def _compile_resolve(self, settings=None):
        # internal optimization helper, не внешний контракт
        spec = self.build_resolve_spec(settings=settings)
        sink = self.build_sink_spec(settings=settings)
        return ResolveDsl().compile(spec, sink_spec=sink)
```

Правило:
1. Наличие internal compile-helper допустимо.
2. Но внешний API спеки должен оставаться единообразным для всех стадий:
   - сначала `build_<stage>_spec`,
   - затем `build_<stage>_stage`.
3. Не делать «особый паттерн только для одной стадии» без фиксации в доке.
4. `build_transform_stages` не заменяет stage-builders, а только агрегирует их.
5. `build_planning_stages` не заменяет stage-builders, а только агрегирует их.

## Runtime-параметры (важно)
`run_id/runtime_scope/batch_size/flush_interval_ms` не относятся к dataset-конфигу.
Они задаются в use-case/runtime и передаются в stage/engine только при запуске.

## Компромисс по `registry` (зафиксировано)
Используем компромиссный вариант:

1. В `StageEngine` можно оставить параметр `registry: OperationRegistry | None = None`.
2. Этот параметр нужен только для тестов и переходного периода миграции.
3. `DatasetSpec` не должен прокидывать `registry` в `build_*_stage`.
4. В production-пути используется registry по умолчанию внутри engine.

Требование к реализации:
1. В коде рядом с параметром `registry` оставить явный комментарий:
   - это тестовый/migration hook;
   - после стабилизации DSL можно убрать из публичного конструктора engine.

## BuildOptions для всех стадий (зафиксировано)
Вводим `*DslBuildOptions` для всех стадий:

1. `MapDslBuildOptions`
2. `NormalizeDslBuildOptions`
3. `EnrichDslBuildOptions`
4. `MatchDslBuildOptions`
5. `ResolveDslBuildOptions`

Важно:
1. `BuildOptions` не являются частью stage-rules YAML.
2. `BuildOptions` — это compile-policy движка, а не бизнес-правила данных.
3. В DSL core вводится базовый класс `BaseDslBuildOptions`, а stage-классы наследуются от него.

### Базовый класс (DSL core)
`BaseDslBuildOptions` содержит только truly-common поля:

1. `strict: bool` — общий fail-fast/soft режим compile-политики.
2. `fail_on_unknown_ops: bool` — политика для неизвестных ops.
3. `fail_on_schema_warnings: bool` — повышать warnings до ошибок.
4. `emit_compile_report: bool` — формировать расширенный compile diagnostics.

Пример:
```python
@dataclass(frozen=True)
class BaseDslBuildOptions:
    strict: bool = False
    fail_on_unknown_ops: bool = True
    fail_on_schema_warnings: bool = False
    emit_compile_report: bool = False

@dataclass(frozen=True)
class EnrichDslBuildOptions(BaseDslBuildOptions):
    require_match_key: bool = False
```

Правило применения:
1. Сначала применяются общие политики `BaseDslBuildOptions`.
2. Затем применяются stage-specific политики наследника.
3. Stage-specific поля не поднимаются в базовый класс.

### Откуда берутся значения BuildOptions
Значения задаются декларативно через конфиг политики (например, `datasets/registry.yml`):

```yaml
datasets:
  employees:
    build_options:
      mapping:
        require_targets_exist_in_sink_spec: true
      normalize:
        validate_only_touched_fields: true
      enrich:
        require_match_key: true
      match:
        require_primary_identity_rule: true
      resolve:
        allow_pending_links: true
```

### Merge-стратегия
При сборке стадии применяется merge:

1. `code defaults` (`BuildOptions.default()`)
2. `global policy overrides`
3. `dataset.stage overrides`

Итоговый `BuildOptions` передаётся в соответствующий `StageDsl`.

## Не делать
1. Не прокидывать наружу `dsl=...` из `DatasetSpec`.
2. Не собирать `*Core` в use-case.
3. Не дублировать сборку stage в командах.

## Чеклист консистентности
1. Все 5 стадий (`map/normalize/enrich/match/resolve`) возвращаются из `DatasetSpec` как `*Stage`.
2. Для всех стадий use-case получает stage и запускает её, без ручной сборки core/rules.
3. Внешний API `*Engine` одинаково фасадный: `spec + stable deps`, DSL скрыт внутри.

## Отложенная архитектурная доработка (не в текущем рефакторе)
Текущее `Settings` содержит поля разных доменов (source/cache/transform/resolve/apply/report/diagnostics),
что повышает связанность при передаче в stage-core.

План после завершения текущей миграции:
1. Ввести композиционный конфиг:
   - `AppSettings` (корневой)
   - `SourceSettings`
   - `CacheSettings`
   - `TransformSettings`
   - `ResolveSettings`
   - `ApplySettings`
   - `ReportSettings`
   - `DiagnosticsSettings`
2. Передавать в каждую стадию только профильную секцию настроек.
3. Убрать переходные адаптеры/билдеры, которые маппят “толстый” `Settings` в локальные dataclass.

Статус:
1. Зафиксировано как следующий этап.
2. В текущем этапе не реализуем.

## Execution Plan (Stage Consistency Migration)

Цель:
1. Привести все стадии (`map/normalize/enrich/match/resolve`) к единому стилю `build_*_stage`.
2. Оставить `build_transform_stages` и добавить `build_planning_stages` как два симметричных агрегатора.
3. Убрать legacy-методы сборки planning после полного перехода.

### Iteration 1: API Contract Alignment (`DatasetSpec`)
Задачи:
1. Обновить `DatasetSpec` контракт под единый стиль:
   - добавить `build_map_stage`
   - добавить `build_normalize_stage`
   - добавить `build_enrich_stage`
   - добавить `build_match_stage`
   - добавить `build_resolve_stage`
   - оставить `build_transform_stages` как convenience-агрегатор
   - добавить `build_planning_stages` как convenience-агрегатор
2. Зафиксировать единые сигнатуры (keyword-only, `catalog` обязателен).
3. Оставить `SinkSpec | None` в контракте.

Файлы:
1. `connector/datasets/spec.py`

Критерии завершения:
1. `DatasetSpec` содержит только целевой набор stage-builder методов.
2. Типы/докстринги отражают целевой стиль.

### Iteration 2: EmployeesSpec Rewire
Задачи:
1. В `EmployeesSpec` реализовать публичные:
   - `build_map_stage`
   - `build_normalize_stage`
   - `build_enrich_stage`
   - `build_match_stage`
   - `build_resolve_stage`
2. Перестроить `build_transform_stages` как вызов `build_map_stage/build_normalize_stage/build_enrich_stage`.
3. Добавить `build_planning_stages` как вызов `build_match_stage/build_resolve_stage`.
4. Привести порядок методов к линейному:
   - `build_*_spec`
   - `build_*_stage`
   - агрегаторы (`build_transform_stages`, `build_planning_stages`)
   - internal helpers (`_compile_*`)
5. В `*Engine` оставить `registry` только как test/migration hook (с комментарием), из `DatasetSpec` не прокидывать.

Файлы:
1. `connector/datasets/employees/spec.py`
2. (точечно) `connector/domain/transform/*/*_engine.py` — только комментарии и сигнатурная чистка, без изменения бизнес-логики.

Критерии завершения:
1. `EmployeesSpec` строит все стадии через `build_*_stage`.
2. Внутренние зависимости DSL не торчат наружу через `DatasetSpec`.

### Iteration 3: Use-case/Command Orchestration Cleanup
Задачи:
1. Перевести команды/use-cases на stage-builders из `DatasetSpec`.
2. Убрать ручную сборку matcher/resolver в use-case слое.
3. Оставить runtime-binding (`run_id/scope`) в `MatchUseCase` (как зафиксировано).
4. Сохранить текущую семантику `pending replay`.

Файлы:
1. `connector/delivery/commands/match.py`
2. `connector/delivery/commands/resolve.py`
3. `connector/usecases/import_plan_service.py`
4. `connector/usecases/planning_match_runtime.py`

Критерии завершения:
1. Use-case слой оркестрирует, но не собирает core/rules вручную.
2. Поведение match/resolve/pending не меняется.

### Iteration 4: BuildOptions Foundation
Задачи:
1. Ввести `BaseDslBuildOptions` в DSL core.
2. Ввести stage-наследники:
   - `MapDslBuildOptions`
   - `NormalizeDslBuildOptions`
   - `EnrichDslBuildOptions`
   - `MatchDslBuildOptions`
   - `ResolveDslBuildOptions`
3. Реализовать минимальный loader/merge для options:
   - defaults (code)
   - global policy
   - dataset.stage policy
4. Подключить в stage builders без изменения текущей бизнес-логики.

Файлы:
1. `connector/domain/dsl/specs.py` (или dedicated options module)
2. `connector/domain/dsl/loader.py`
3. `connector/domain/transform/*/*_dsl.py`
4. `connector/datasets/employees/spec.py`

Критерии завершения:
1. У всех стадий есть единый options-паттерн.
2. `EnrichDslBuildOptions` встроен в общую схему, не особый случай.

### Iteration 5: Legacy Removal
Задачи:
1. Удалить legacy planning-builders:
   - `build_planning_bundle`
   - лишние `build_*_rules` как внешний API (если не нужны больше для internal reuse).
2. Удалить неиспользуемые transitional вызовы/импорты.
3. Подчистить документацию и UML по финальному контракту.

Файлы:
1. `connector/datasets/spec.py`
2. `connector/datasets/employees/spec.py`
3. связанные use-cases/commands
4. `docs/Stage_Engine_Style.md`
5. `docs/uml/transform/*` (если затронуты контракты)

Критерии завершения:
1. В репозитории один консистентный способ сборки стадий.
2. Нет дублей/legacy API в production path.

### Iteration 6: Test/Quality Gate
Задачи:
1. Добавить/обновить тесты на контракт builders:
   - каждый `build_*_stage` возвращает runnable stage
   - `build_transform_stages` возвращает корректную тройку
   - `build_planning_stages` возвращает корректную пару
2. Добавить тесты на orchestration:
   - use-cases не собирают core/rules напрямую
3. Добавить тесты на options merge.

Файлы:
1. `tests/transform/*`
2. `tests/planning/*`
3. `tests/usecases/*`

Критерии завершения:
1. Тесты покрывают новый контракт и guardrails.
2. Регрессий по текущему pipeline нет.

## Rollout Order (рекомендуемый)
1. Iteration 1
2. Iteration 2
3. Iteration 3
4. Iteration 6 (быстрая верификация)
5. Iteration 4
6. Iteration 5
7. Iteration 6 (финальная)
