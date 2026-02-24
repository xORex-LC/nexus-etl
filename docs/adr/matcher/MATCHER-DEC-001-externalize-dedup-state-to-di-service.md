# MATCHER-DEC-001: Вынесение dedup-state в ISourceDedupStore — MatchStage как чистый per-record трансформер; введение PipelineRunContext

> **Статус**: Принято
> **Дата принятия**: 2026-02-24
> **Решает проблему**: [MATCHER-PROBLEM-001](./MATCHER-PROBLEM-001-match-stage-mixed-responsibilities.md)
> **Зависит от**: [RESOLVER-DEC-001](../resolver/RESOLVER-DEC-001-externalize-mechanics-to-di-services.md) — вводит `IBatchIndexService`; оба сервиса объединяются в `PipelineRunContext`
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

`MatchCore` хранит mutable runtime-state дедупликации источника (`_seen_source`) внутри экземпляра и требует lifecycle-управления через `reset_source_dedup()` и `bind_runtime_scope()` до начала потока ([MATCHER-PROBLEM-001](./MATCHER-PROBLEM-001-match-stage-mixed-responsibilities.md)). Это не нарушает сигнатуру `StageContract`, но смешивает бизнес-алгоритм с инфраструктурным state и делает регистрацию в `PipelineContainer` зависимой от знания о порядке lifecycle-вызовов.

Параллельно [RESOLVER-DEC-001](../resolver/RESOLVER-DEC-001-externalize-mechanics-to-di-services.md) вводит `IBatchIndexService` — per-run singleton для Resolver. Оба сервиса имеют одинаковый lifecycle: Singleton в рамках одного pipeline run, сброс перед каждым новым прогоном. Это естественная точка объединения в `PipelineRunContext`.

---

## 🎯 Решение

Dedup-state `_seen_source` выносится из `MatchCore` в injectable `ISourceDedupStore`. Выбор реализации (локальная / разделяемая через `cache_gateway`) фиксируется при DI-сборке, а не через runtime-вызов `bind_runtime_scope()`.

`ISourceDedupStore` и `IBatchIndexService` объединяются в `PipelineRunContext` — единый per-run агрегатор state для обеих стадий. `PipelineContainer` регистрирует `PipelineRunContext` как Singleton.

---

## 🏗️ Архитектурное решение

### Компонент 1: ISourceDedupStore

```python
# connector/domain/transform/matcher/ports.py

class DedupOutcome(Protocol):
    """Результат проверки дедупликации для одной записи."""
    is_first: bool          # True — первое появление, пропустить
    is_duplicate: bool      # одинаковый fingerprint — hard drop
    is_conflict: bool       # другой fingerprint — политика warn/error

class ISourceDedupStore(Protocol):
    """Хранилище seen-fingerprints для source-dedup внутри потока.
    Singleton per pipeline run. Не содержит бизнес-политики — только check/register."""

    def check_and_register(self, key: str, fingerprint: str) -> DedupOutcome:
        """Проверяет, встречался ли key. Регистрирует fingerprint при первом появлении."""
        ...

    def reset(self) -> None:
        """Сбрасывает seen-state перед новым прогоном. Вызывается PlanningPipeline."""
        ...
```

Две реализации:
- `LocalSourceDedupStore` — in-memory dict, полный аналог текущего `_seen_source`
- `ScopedSourceDedupStore` — делегирует к `cache_gateway` для разделяемого runtime-state (аналог текущего scoped-режима)

Выбор реализации — решение DI при сборке, не runtime-переключатель.

### Компонент 2: PipelineRunContext — per-run aggregator

```python
# connector/domain/transform/pipeline_run_context.py

@dataclass
class PipelineRunContext:
    """Агрегирует per-run инфраструктурный state для стадий сопоставления и разрешения.
    Singleton per pipeline run в PipelineContainer. Не содержит бизнес-логики."""

    dedup_store: ISourceDedupStore    # для MatchStage
    batch_index: IBatchIndexService   # для ResolveStage (RESOLVER-DEC-001)
```

Каждая стадия инжектирует только нужную часть через свой порт — `PipelineRunContext` не протекает в бизнес-логику:

```python
# MatchStage инжектирует ISourceDedupStore, не PipelineRunContext напрямую
# ResolveStage инжектирует IBatchIndexService, не PipelineRunContext напрямую
```

### Компонент 3: MatchCore — алгоритм без state

После изменений `MatchCore` не хранит mutable state:

```python
class MatchCore:
    def __init__(
        self,
        dataset: str,
        cache_gateway: MatchRuntimePort,
        matching_rules: MatchingRules,
        resolve_rules: ResolveRules,
        include_deleted: bool,
        catalog: ErrorCatalog,
        dedup_store: ISourceDedupStore,   # ← инжектируется, не создаётся внутри
    ) -> None: ...

    def match(self, enriched: TransformResult) -> TransformResult[MatchedRow]:
        # Алгоритм сопоставления — как сейчас, но без _seen_source
        ...

    def match_with_source_dedup(self, enriched: TransformResult) -> TransformResult[MatchedRow]:
        result = self.match(enriched)
        if result.row is None:
            return result
        outcome = self._dedup_store.check_and_register(
            key=_build_dedup_key(result.row.identity),   # без dataset-prefix
            fingerprint=result.row.fingerprint,
        )
        return _apply_dedup_outcome(result, outcome, self._catalog)

    # Убраны: reset_source_dedup(), bind_runtime_scope(), _seen_source
```

**Удаление `dataset` из ключа дедупликации**: `_build_dedup_key(self._dataset, identity)` → `_build_dedup_key(identity)`. `dataset`-prefix был нужен при модели с potentially-shared state между датасетами. `ISourceDedupStore` — per-run Singleton через `PipelineRunContext`: изоляция обеспечивается lifecycle (отдельный экземпляр на каждый прогон + `reset()` перед следующим), а не пространством имён ключей. Аналогично RESOLVER-DEC-001 (удаление `dataset`-namespace из структуры `batch_index`).

### Компонент 4: PipelineContainer — wiring

```python
class PipelineContainer(containers.DeclarativeContainer):

    run_context = providers.Singleton(
        PipelineRunContext,
        dedup_store=providers.Singleton(LocalSourceDedupStore),
        batch_index=providers.Singleton(InMemoryBatchIndexService),
    )

    match_stage = providers.Singleton(
        MatchStage,
        matcher=...,
        dedup_store=run_context.provided.dedup_store,  # только нужная часть
        catalog=...,
    )

    resolve_stage = providers.Singleton(
        ResolveStage,
        resolver=...,
        batch_index=run_context.provided.batch_index,  # только нужная часть
        catalog=...,
    )

    planning_pipeline = providers.Factory(
        PlanningPipeline,
        pipeline=...,                                  # PipelineOrchestrator
        dedup_store=run_context.provided.dedup_store,  # только порт для reset()
    )
```

### Компонент 5: PlanningPipeline — явная оркестрация lifecycle

`bind_runtime_scope()` исчезает как runtime-метод. Scope фиксируется в DI при выборе реализации `ISourceDedupStore`. `reset()` остаётся, но переходит к сервису и вызывается явно в начале прогона.

`PlanningPipeline` получает `dedup_store: ISourceDedupStore` через constructor injection — только тот порт, который нужен для lifecycle-сброса. `batch_index` сбрасывается неявно: `ResolveContextStage.set_index()` атомарно заменяет индекс в начале каждого run — явный `reset()` не требуется.

```python
class PlanningPipeline:
    def __init__(
        self,
        pipeline: PipelineOrchestrator,    # все стадии через PIPELINE_CHECKPOINTS
        dedup_store: ISourceDedupStore,    # только для reset() перед прогоном
    ) -> None: ...

    def run(self, source: Iterable) -> Iterable:
        self._dedup_store.reset()           # lifecycle: сброс перед прогоном
        yield from self._pipeline.run(source)  # декларативно: PIPELINE_CHECKPOINTS
```

`PlanningPipeline` не знает о порядке стадий, не знает о `batch_index` — только о том, что перед каждым прогоном нужно сбросить dedup-state.

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ `MatchCore` лишается mutable state — алгоритм сопоставления теперь зависит только от явных входов
- ✅ Выбор local/scoped dedup-хранилища — решение DI при сборке, видимо и явно, а не скрытый runtime-переключатель
- ✅ `reset()` и выбор scope — оркестрационная ответственность `PlanningPipeline`, а не lifecycle-метод на самой стадии
- ✅ `PipelineRunContext` явно выражает «это per-run state двух связанных стадий» — не два случайных синглтона
- ✅ Тест бизнес-логики `MatchCore` не требует настройки lifecycle: передаёшь мок `ISourceDedupStore`, проверяешь алгоритм
- ✅ `MatchStage` и `ResolveStage` симметричны: обе per-record, обе через DI, обе без внутреннего state

**Недостатки (компромиссы)**:
- ⚠️ `ScopedSourceDedupStore` (реализация через `cache_gateway`) требует аккуратного DI-wiring: нужно пробросить правильный `cache_gateway` при сборке — потенциально условная логика в container при переключении режимов. Решается через конфигурационный провайдер или фабрику.
- ⚠️ `PipelineRunContext` — новый тип, который нужно сопровождать. Минимален (dataclass из двух полей), но требует обновлений при добавлении новых per-run сервисов.

**Альтернативы, которые отклонили**:
- ❌ **Документировать порядок вызовов**: закрепляет скрытую зависимость, не решает проблему mutable state.
- ❌ **Два отдельных синглтона без `PipelineRunContext`**: работает, но не выражает явно, что `dedup_store` и `batch_index` — это одна логическая единица «state текущего прогона».
- ❌ **Один общий сервис с единым API для обеих стадий**: механики слишком разные (incremental check-and-set vs bulk pre-computation) — объединение создаёт god-объект с несвязанными ответственностями.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform/matcher/ports.py` | Новый: `ISourceDedupStore`, `DedupOutcome` |
| `connector/domain/transform/matcher/dedup_store.py` | Новый: `LocalSourceDedupStore`, `ScopedSourceDedupStore` |
| `connector/domain/transform/matcher/match_core.py` | Удалить: `_seen_source`, `reset_source_dedup()`, `bind_runtime_scope()`. Добавить: `dedup_store: ISourceDedupStore` в конструктор |
| `connector/domain/transform/pipeline_run_context.py` | Новый: `PipelineRunContext` (dataclass из `ISourceDedupStore` + `IBatchIndexService`) |
| `connector/delivery/cli/containers.py` | `PipelineContainer`: добавить `run_context = providers.Singleton(PipelineRunContext, ...)` |
| `connector/delivery/pipelines/planning_pipeline.py` | Убрать вызовы `bind_runtime_scope()` / `reset_source_dedup()` и явную побочную оркестрацию; добавить `dedup_store: ISourceDedupStore` в конструктор; вызывать `dedup_store.reset()` перед `pipeline.run(source)` |

### Целевая структура модулей

```
connector/domain/transform/
├── pipeline_run_context.py              # НОВЫЙ: PipelineRunContext — dataclass(dedup_store, batch_index)
│                                        #        per-run aggregator; стадии получают только нужный им порт
└── matcher/
    ├── match_core.py                    # ИЗМЕНЁН: убраны _seen_source, bind_runtime_scope(), reset_source_dedup()
    │                                    #          добавлен dedup_store: ISourceDedupStore в конструктор
    ├── match_engine.py                  # ИЗМЕНЁН: пробросить dedup_store при создании MatchCore
    ├── ports.py                         # НОВЫЙ: ISourceDedupStore (check_and_register, reset), DedupOutcome
    └── dedup_store.py                   # НОВЫЙ: LocalSourceDedupStore (in-memory dict)
                                         #        ScopedSourceDedupStore (через cache_gateway)

connector/delivery/
├── cli/containers.py                    # ИЗМЕНЁН: run_context = Singleton(PipelineRunContext, ...)
│                                        #          planning_pipeline = Factory(PlanningPipeline, ..., dedup_store=...)
└── pipelines/planning_pipeline.py      # ИЗМЕНЁН: убрана явная оркестрация match/build_index/resolve
                                         #          добавлен dedup_store: ISourceDedupStore в конструктор
                                         #          run(): dedup_store.reset() → pipeline.run(source)
```

### Инварианты

1. `MatchCore` не хранит mutable state между вызовами `match()` / `match_with_source_dedup()`
2. `ISourceDedupStore.reset()` вызывается строго до начала `pipeline.run()` в рамках прогона — в `PlanningPipeline.run()`
3. Выбор `LocalSourceDedupStore` vs `ScopedSourceDedupStore` — решение DI, не runtime-параметр
4. `PipelineRunContext` не передаётся в `MatchCore`, `ResolveCore` или `PlanningPipeline` напрямую — только нужные им порты
5. Ключ дедупликации строится без `dataset`-prefix — изоляция обеспечивается per-run lifecycle `ISourceDedupStore`, а не пространством имён
6. `PlanningPipeline` получает `dedup_store: ISourceDedupStore`, но не `batch_index` — `batch_index` сбрасывается через `IBatchIndexService.set_index()` внутри `ResolveContextStage` без участия `PlanningPipeline`

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `MatchCore` | Упрощение | Удалить `_seen_source`, `reset_source_dedup()`, `bind_runtime_scope()`; принять `ISourceDedupStore` |
| `MatchEngine` | Минимальное | Пробросить `dedup_store` при сборке `MatchCore` |
| `PlanningPipeline` | Уточнение | Добавить `dedup_store: ISourceDedupStore` в конструктор; убрать явную оркестрацию; `run()` → `dedup_store.reset()` + `pipeline.run(source)` |
| `PipelineContainer` | Расширение | Добавить `run_context` Singleton; `planning_pipeline` — добавить `dedup_store=run_context.provided.dedup_store`; упростить wiring `match_stage` и `resolve_stage` |
| `PipelineRunContext` | Новый тип | Dataclass из двух полей — `dedup_store` и `batch_index` |
| Тесты `MatchCore` | Упрощение | Не нужен lifecycle setup; передаётся мок `ISourceDedupStore` |
| Тесты `MatchStage` | Минимальное | Убрать вызовы `reset_source_dedup()` из тест-кода |
| `test_stage_factory.py` | Обновление | `build_stage_factory()` регистрирует 6 стадий (добавить RESOLVE_CONTEXT) |

---

## 🧪 Тест-стратегия

### Существующие тесты — что меняется

| Файл | Изменение | Причина |
|------|-----------|---------|
| `tests/unit/planning/test_matcher_source_dedup.py` | `_build_matcher()`: добавить `dedup_store=LocalSourceDedupStore()` | MatchCore больше не создаёт _seen_source сам |
| `tests/unit/planning/test_matcher_source_dedup.py` | `test_source_dedup_reads_scoped_runtime_state_from_identity_repo()`: **полный rewrite** | Тест проверял `bind_runtime_scope()` — метод удалён. Концепция переезжает в `ScopedSourceDedupStore` |
| `tests/unit/planning/test_matcher_fuzzy_scoring.py` | `_matcher()`: добавить `dedup_store=LocalSourceDedupStore()` | Аналогично factory выше |
| `tests/integration/planning/test_matcher_identity_rules.py` | Аналогичное обновление фабрики | Аналогично |

### Новые тесты

#### Unit — доменные сервисы (порты и реализации)

| Файл | Что тестирует |
|------|--------------|
| `tests/unit/transform/matcher/test_local_source_dedup_store.py` | `check_and_register()` → DedupOutcome (first/duplicate/conflict); `reset()` очищает state; независимость двух экземпляров |
| `tests/unit/transform/matcher/test_scoped_source_dedup_store.py` | Делегирует к `cache_gateway`; два экземпляра с одним scope видят общее состояние (замена удалённого теста `bind_runtime_scope`) |
| `tests/unit/transform/test_pipeline_run_context.py` | Конструкция dataclass; доступ к `dedup_store` и `batch_index`; стадии получают только нужный порт (не весь run_context) |

#### Архитектурные (в `test_pipeline_architecture.py` или отдельный файл)

| Тест | Инвариант |
|------|-----------|
| `test_planning_pipeline_calls_dedup_reset_before_run()` | `dedup_store.reset()` вызван строго до `pipeline.run()` — порядок lifecycle |
| `test_match_core_has_no_mutable_state_between_calls()` | Два последовательных `match()` с мок `ISourceDedupStore` не разделяют internal state |
| `test_dedup_store_not_injected_into_match_core_directly_as_run_context()` | MatchCore принимает `ISourceDedupStore`, но не `PipelineRunContext` — граница соблюдена |

### Примечание по `bind_runtime_scope()`

Старый тест `test_source_dedup_reads_scoped_runtime_state_from_identity_repo()` проверял, что два экземпляра `MatchCore` с одним `scope` видят общее `_seen_source` через `cache_gateway`. После изменений это становится свойством `ScopedSourceDedupStore` — тест переезжает туда и проверяет поведение хранилища напрямую, без MatchCore.

---

## 🔗 Связанные документы

- [MATCHER-PROBLEM-001](./MATCHER-PROBLEM-001-match-stage-mixed-responsibilities.md) — решаемая проблема
- [RESOLVER-DEC-001](../resolver/RESOLVER-DEC-001-externalize-mechanics-to-di-services.md) — симметричное решение для Resolver; вводит `IBatchIndexService`, объединяемый с `ISourceDedupStore` в `PipelineRunContext`
- [TRANSFORM-DEC-007](../transform/TRANSFORM-DEC-007-declarative-pipeline-checkpoints.md) — разблокируемое решение
- [docs/dev/layers/matcher/functional-capabilities-map.md](../../dev/layers/matcher/functional-capabilities-map.md) — раздел 11.2 и 11.3 описывают целевое разделение

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-24 | Решение сформулировано в ходе анализа MATCHER-PROBLEM-001 и RESOLVER-DEC-001 |
| 2026-02-24 | Принято; `PipelineRunContext` добавлен как точка объединения per-run state для Matcher и Resolver |
| 2026-02-24 | Реализация запланирована в составе этапа 2 TRANSFORM-DEC-007 |
| 2026-02-24 | Уточнения: `dataset`-prefix удалён из ключа `_build_dedup_key()` — изоляция через per-run lifecycle `PipelineRunContext`, а не namespace. Симметрично удалению `dataset`-namespace в RESOLVER-DEC-001 |
| 2026-02-24 | Уточнения архитектуры PlanningPipeline: (1) псевдокод обновлён — убрана явная оркестрация match/build_index/resolve; `PlanningPipeline.run()` только вызывает `dedup_store.reset()` + `pipeline.run(source)`; (2) constructor injection: `PlanningPipeline` получает `dedup_store: ISourceDedupStore`, а не весь `run_context` — inject only what you need; (3) `batch_index` сброс не нужен явно — `set_index()` атомарно заменяет при каждом `ResolveContextStage.run()` |
