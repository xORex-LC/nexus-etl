# RESOLVER-DEC-001: Вынесение инфраструктурных механик в DI-сервисы — ResolveStage как чистый per-record трансформер

> **Статус**: Принято (обновлено 2026-02-24)
> **Дата принятия**: 2026-02-24
> **Решает проблему**: [RESOLVER-PROBLEM-001](./RESOLVER-PROBLEM-001-resolve-stage-mixed-responsibilities.md)
> **Зависит от**: [TRANSFORM-DEC-007](../transform/TRANSFORM-DEC-007-declarative-pipeline-checkpoints.md), [TRANSFORM-DEC-008](../transform/TRANSFORM-DEC-008-pending-codec-standalone-feature.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

`ResolveStage` не реализует `StageContract` из-за смешения бизнес-логики данных с инфраструктурными механиками: буферизацией потока для построения `batch_index`, housekeeping sweep просроченных pending в горячем пути обработки записи, сериализацией pending payload в ядре ([RESOLVER-PROBLEM-001](./RESOLVER-PROBLEM-001-resolve-stage-mixed-responsibilities.md)).

Вся core data logic `ResolveCore` — per-record (гейт, merge, link resolution, operation decision, diff). Единственное, что требует cross-record контекста — `batch_index` для разрешения ссылок между записями одного прогона.

Смысл `PIPELINE_CHECKPOINTS` + `PipelineComposer` — стадии не знают порядка, не знают соседей; оркестратор декларативен. Буферизация `matched_rows` в `PlanningPipeline` с явным вызовом `batch_index_service.build(matched)` нарушает этот инвариант: добавить стадию между MATCH и RESOLVE или отключить RESOLVE без правки `PlanningPipeline` — невозможно. Порядок остаётся hardcoded в коде, а не в реестре.

---

## 🎯 Решение

Инфраструктурные механики `ResolveCore` выносятся в три именованных DI-сервиса:

1. **`IBatchIndexService`** — pre-computation `batch_index`. Вызывается `ResolveContextStage` (см. ниже) — отдельной стадией-подготовкой между MATCH и RESOLVE.
2. **`IPendingExpiryService`** — управление TTL, sweep просроченных pending, drain-буфер. Вызывается вне горячего пути: через `PipelineHooks.on_stage_complete` на стадии RESOLVE. Не вызывается из `ResolveCore`.
3. **`IPendingCodec`** — сериализация/десериализация pending payload. Выносится из `ResolveCore` в отдельный injectable порт (смежно с [TRANSFORM-DEC-008](../transform/TRANSFORM-DEC-008-pending-codec-standalone-feature.md)).

Дополнительно вводится **`ResolveContextStage`** (`CheckpointName.RESOLVE_CONTEXT`) — специальная стадия-подготовка, которая буферизует matched rows, строит `batch_index` в `IBatchIndexService` и прозрачно пропускает записи дальше.

Результат — полностью декларативный `PIPELINE_CHECKPOINTS`:

```
PLAN = [MAP, NORMALIZE, ENRICH, MATCH, RESOLVE_CONTEXT, RESOLVE]
```

Use case получает `pipeline: PipelineOrchestrator` — единообразно со всеми остальными use cases. `PlanningPipeline` перестаёт хранить знание о порядке стадий.

Дополнительно:
- `dataset: str | None` kwarg удаляется из `ResolveStage.run()` — датасет переносится в `StageExecutionContext.metadata`.

---

## 🏗️ Архитектурное решение

### Компонент 1: IBatchIndexService

```python
# connector/domain/transform/resolver/ports.py

class IBatchIndexService(Protocol):
    """Хранит pre-computed batch_index для текущего прогона.
    Singleton per pipeline run (через PipelineRunContext).
    ResolveContextStage записывает индекс один раз; ResolveStage читает per-record."""

    def set_index(self, index: dict) -> None:
        """Сохраняет pre-computed индекс. Вызывается ResolveContextStage.
        После вызова get() разрешён."""
        ...

    def get(self) -> dict:
        """Возвращает batch_index для текущего прогона.
        Поднимает RuntimeError если set_index() не был вызван —
        защита от неправильного порядка чекпоинтов в PIPELINE_CHECKPOINTS."""
        ...
```

**Структура индекса**: `{lookup_key: [resolved_ids]}` — без внешнего `dataset`-ключа.
`dataset`-namespace был нужен при shared state между датасетами. `IBatchIndexService` — per-run Singleton через `PipelineRunContext`: изоляция обеспечивается lifecycle, а не ключами. Подробнее — см. раздел «Удаление dataset-параметра».

Реализация: `InMemoryBatchIndexService` — держит индекс в памяти, живёт в рамках одного CLI-вызова.

### Компонент 2: IPendingExpiryService

```python
# connector/domain/transform/resolver/ports.py

class IPendingExpiryService(Protocol):
    """Housekeeping просроченных pending-записей.
    Вызывается вне горячего пути обработки записей."""

    def sweep(self) -> None:
        """Запуск sweep просроченных pending через runtime-порт."""
        ...

    def drain_expired(self) -> list[PendingLink]:
        """Возвращает накопленные expired pending и очищает внутренний буфер."""
        ...
```

### Компонент 3: IPendingCodec как injectable порт

```python
# connector/domain/transform/resolver/ports.py

class IPendingCodec(Protocol):
    """Сериализация/десериализация pending payload.
    Независим от алгоритма resolve."""

    def serialize(self, matched: MatchedRow, desired_state: dict, meta: dict) -> str: ...
    def deserialize(self, pending_rows: list[PendingRow]) -> PendingLoadResult: ...
```

Существующий `pending_codec.py` покрывает сторону десериализации. Сторона сериализации (`_serialize_pending_payload` из `ResolveCore`) выносится сюда же.

### Компонент 4: ResolveContextStage — стадия подготовки контекста

```python
# connector/domain/transform/stages/stages.py

class ResolveContextStage:
    """Прозрачный pass-through: буферизует matched rows, строит batch_index, re-yields.
    Является стадией конвейера (StageContract), делает батч-индекс доступным для ResolveStage."""

    def __init__(
        self,
        batch_index: IBatchIndexService,
        resolver: ResolveProcessor,   # нужен для вызова build_batch_index()
    ) -> None: ...

    @property
    def stage_name(self) -> str:
        return "resolve_context"

    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        all_records = list(source)                              # буферизация — здесь, явно
        index = self._resolver.build_batch_index(all_records)  # вычислить индекс
        self._batch_index.set_index(index)                     # сохранить в сервис
        yield from all_records                                 # прозрачный pass-through
```

`ResolveContextStage` вычисляет индекс через `resolver.build_batch_index()` и передаёт результат в `IBatchIndexService.set_index()`. Сервис — это только typed holder; вся логика вычисления остаётся в `ResolveProcessor`.

Единственная ответственность стадии: подготовить cross-batch контекст разрешения ссылок. Аналог ENRICH по роли — строит контекст для следующей стадии, прозрачна для данных.

### Компонент 5: ResolveStage — чистый per-record трансформер

```python
# connector/domain/transform/stages/stages.py

class ResolveStage:
    def __init__(
        self,
        resolver: ResolveProcessor,
        batch_index: IBatchIndexService,
        catalog: ErrorCatalog,
    ) -> None: ...

    # StageContract: совместима, no extra kwargs
    def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
        for record in source:                        # per-record, никакой буферизации
            result = self._resolver.resolve(
                record,
                batch_index=self._batch_index.get(),
            )
            yield wrap_result(result)
```

### Поток сборки

```
PipelineContainer:
  # Per-run state aggregator (MATCHER-DEC-001)
  run_context = Singleton(PipelineRunContext,
                    dedup_store=Singleton(LocalSourceDedupStore),
                    batch_index=Singleton(InMemoryBatchIndexService))

  # Стадии получают только нужный порт из run_context
  resolve_context_stage = Singleton(ResolveContextStage,
                              batch_index=run_context.provided.batch_index,
                              resolver=resolve_engine)
  resolve_stage         = Singleton(ResolveStage,
                              resolver=resolve_engine,
                              batch_index=run_context.provided.batch_index)

  # Expiry — отдельный сервис, не в run_context (lifecycle отличается)
  pending_expiry = Singleton(PendingExpiryService, gateway=cache.resolve_gateway)
  pending_codec  = Singleton(PendingCodecAdapter)

  # Хуки с явным wiring к pending_expiry
  plan_hooks = Singleton(PlanningPipelineHooks, pending_expiry=pending_expiry)

PIPELINE_CHECKPOINTS:
  PLAN = [MAP, NORMALIZE, ENRICH, MATCH, RESOLVE_CONTEXT, RESOLVE]
          ↑ все стадии — StageContract, PipelineOrchestrator обрабатывает единообразно

PipelineHooks (on_stage_complete для стадии RESOLVE):
  → pending_expiry.drain_expired()    ← явный wiring, вне hot path

Use case:
  def run(self, pipeline: PipelineOrchestrator, ...):
      for result in pipeline.run(source):    ← единообразно с остальными
          ...
```

---

## 🗑️ Удаление dataset-параметра

`build_batch_index(matched_rows, dataset)` и `dataset`-namespace в dedup-ключах — артефакт архитектуры с potentially-shared state между датасетами. С per-run синглтонами через `PipelineRunContext` этот namespace стал излишним.

**Аргумент**: изоляция обеспечивается lifecycle, а не ключами:

| Сценарий | Без dataset-prefix | Безопасно? |
|----------|-------------------|------------|
| Один датасет per process (текущая модель CLI) | Синглтон свежий при каждом запуске | ✅ |
| Несколько датасетов последовательно в одном процессе | `reset()` очищает state между прогонами | ✅ |
| Несколько датасетов параллельно в одном процессе | Нужна изоляция scope, не prefix в ключе | ⚠️ требует per-dataset DI scope (отдельная задача) |

Для параллельных прогонов правильное решение — отдельный `PipelineContainer` per dataset-run, а не namespacing ключей в одном shared store. Prefix в ключе — band-aid, не изоляция.

**Результат изменения**:
- `ResolveProcessor.build_batch_index(matched_rows)` — без `dataset`
- Структура индекса: `{lookup_key: [resolved_ids]}` вместо `{dataset: {lookup_key: [ids]}}`
- `_resolve_links()` читает: `batch_index.get(key, [])` вместо `batch_index.get(dataset, {}).get(key, [])`

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ `ResolveStage` реализует `StageContract` — `run(source) → Iterable`, per-record, без лишних kwargs
- ✅ `PIPELINE_CHECKPOINTS.PLAN` полностью декларативен — стадии не знают порядка и соседей
- ✅ Use case получает `pipeline: PipelineOrchestrator` — единообразно со всеми остальными use cases
- ✅ Добавить стадию между MATCH и RESOLVE → только изменить `PIPELINE_CHECKPOINTS`, не трогать `PlanningPipeline`
- ✅ Отключить RESOLVE → убрать `RESOLVE_CONTEXT` + `RESOLVE` из реестра декларативно
- ✅ `ResolveContextStage` имеет чёткую единственную ответственность: подготовить контекст разрешения
- ✅ SRP восстановлен: `ResolveCore` отвечает только за алгоритм разрешения данных
- ✅ `IPendingExpiryService` вызывается вне hot path — предсказуемое время обработки каждой записи

**Недостатки (компромиссы)**:
- ⚠️ `RESOLVE_CONTEXT` в `PIPELINE_CHECKPOINTS` — техническая стадия, не несущая бизнес-трансформации данных. Это осознанный выбор: буферизация для `batch_index` — алгоритмическое требование, которое должно быть явным в декларативном реестре, а не спрятано в оркестрационном коде.
- ⚠️ `IBatchIndexService` — stateful singleton: если будущий runtime поддержит параллельные прогоны в одном процессе, потребуется scope per-run. В текущей модели (один CLI-вызов = один процесс) это не проблема.

**Альтернативы, которые отклонили**:
- ❌ **Специальная обработка в PipelineComposer**: нарушает инвариант DEC-007, закрепляет исключения как нормальное поведение.
- ❌ **BatchableStage (batch_size=∞)**: буферизация структурно оформлена, но `dataset` kwarg и sweep в hot path остаются; 1:1 инвариант не восстанавливается.
- ❌ **Явная буферизация в PlanningPipeline** (первоначально принятая): `PlanningPipeline` хранит знание о порядке стадий — hardcoded последовательность `list(match) → build_batch_index → resolve`. Нарушает инвариант TRANSFORM-DEC-007 («стадии не знают порядка»). Добавление стадии между MATCH и RESOLVE требует правки `PlanningPipeline`, а не реестра.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform/resolver/ports.py` | Новый: `IBatchIndexService`, `IPendingExpiryService`, `IPendingCodec` порты |
| `connector/domain/transform/resolver/batch_index_service.py` | Новый: `InMemoryBatchIndexService` |
| `connector/domain/transform/resolver/pending_expiry_service.py` | Новый: `PendingExpiryService` (выносит sweep + drain из `ResolveCore`) |
| `connector/domain/transform/resolver/resolve_core.py` | Удалить: `_last_sweep_at`, `_expired_buffer`, `_maybe_sweep_expired()`, `drain_expired()`, `_serialize_pending_payload()`. Добавить: `codec: IPendingCodec` в конструктор |
| `connector/domain/transform/stages/stages.py` | `ResolveStage`: убрать `dataset` kwarg, убрать `list(source)`, инжектировать `IBatchIndexService`. Новый: `ResolveContextStage` |
| `connector/delivery/cli/containers.py` | `PipelineContainer`: добавить `batch_index_service`, `pending_expiry_service`, `pending_codec`, `resolve_context_stage` провайдеры |
| `connector/delivery/cli/pipeline_registry.py` | `PIPELINE_CHECKPOINTS.PLAN`: добавить `CheckpointName.RESOLVE_CONTEXT` между MATCH и RESOLVE |
| `connector/delivery/pipelines/planning_pipeline.py` | Убрать явную буферизацию и `batch_index_service.build()`; получать `pipeline: PipelineOrchestrator` |

### Целевая структура модулей

```
connector/domain/transform/
├── resolver/
│   ├── resolve_core.py                  # ИЗМЕНЁН: убраны _last_sweep_at, _expired_buffer,
│   │                                    #          _maybe_sweep_expired(), drain_expired(),
│   │                                    #          _serialize_pending_payload()
│   │                                    #          добавлен codec: IPendingCodec в конструктор
│   ├── resolve_engine.py                # ИЗМЕНЁН: пробросить IPendingCodec при создании ResolveCore
│   ├── ports.py                         # НОВЫЙ: IBatchIndexService (set_index, get + RuntimeError guard)
│   │                                    #        IPendingExpiryService (sweep, drain_expired)
│   │                                    #        IPendingCodec (serialize, deserialize)
│   ├── batch_index_service.py           # НОВЫЙ: InMemoryBatchIndexService — in-memory holder индекса
│   └── pending_expiry_service.py        # НОВЫЙ: PendingExpiryService — sweep + drain вне hot path
└── stages/
    └── stages.py                        # ИЗМЕНЁН: ResolveStage — убран dataset kwarg, list(source),
                                         #          добавлен batch_index: IBatchIndexService
                                         # НОВЫЙ:   ResolveContextStage — буферизация + set_index

connector/delivery/
├── cli/containers.py                    # ИЗМЕНЁН: run_context (уже в MATCHER-DEC-001)
│                                        #          resolve_context_stage, pending_expiry, pending_codec
│                                        #          planning_pipeline: добавить dedup_store (MATCHER-DEC-001)
└── cli/pipeline_registry.py            # ИЗМЕНЁН: PLAN = [..., MATCH, RESOLVE_CONTEXT, RESOLVE]
                                         #          CheckpointName.RESOLVE_CONTEXT добавлен в enum
```

### Инварианты

1. `ResolveStage.run(source)` — ровно одна запись на вход, ровно одна на выход (или одна с ошибкой)
2. `ResolveContextStage` всегда предшествует `ResolveStage` в `PIPELINE_CHECKPOINTS` — порядок задаётся реестром
3. `IBatchIndexService.set_index()` вызывается строго до первого вызова `IBatchIndexService.get()` — обеспечивается порядком в `PIPELINE_CHECKPOINTS`
4. `IBatchIndexService.get()` поднимает `RuntimeError` если `set_index()` не был вызван — защита от некорректного порядка чекпоинтов
5. `IPendingExpiryService.sweep()` не вызывается из `ResolveCore` — только из `PipelineHooks`
6. Структура `batch_index`: `{lookup_key: [resolved_ids]}` — без `dataset`-namespace; изоляция обеспечивается per-run lifecycle `PipelineRunContext`

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `ResolveCore` | Упрощение | Удалить sweep-state и сериализацию; принять `IPendingCodec` через конструктор |
| `ResolveStage` | Упрощение сигнатуры | Убрать `dataset` kwarg и `list(source)`; принять `IBatchIndexService` |
| `ResolveContextStage` | Новый компонент | Реализовать pass-through с буферизацией и вызовом `IBatchIndexService.set_index()` |
| `PlanningPipeline` | Упрощение | Убрать явную оркестрацию; `dedup_store: ISourceDedupStore` из конструктора (MATCHER-DEC-001); `run()` → `dedup_store.reset()` + `pipeline.run(source)` |
| `PipelineContainer` | Расширение | Добавить 4 новых провайдера (resolver); `planning_pipeline` + `dedup_store` (MATCHER-DEC-001) |
| `PIPELINE_CHECKPOINTS` | Обновление | `PLAN = [..., MATCH, RESOLVE_CONTEXT, RESOLVE]`; `CheckpointName.RESOLVE_CONTEXT` в enum |
| `pending_codec.py` | Промоция | Wrap в `IPendingCodec`-реализацию (смежно с TRANSFORM-DEC-008) |
| `test_stage_factory.py` | Обновление | `build_stage_factory()` регистрирует 6 стадий (добавить RESOLVE_CONTEXT) |
| Тесты `ResolveCore` / `ResolveStage` | Упрощение | Убрать setup инфраструктурного state; мокировать только domain-порты |

---

## 🧪 Тест-стратегия

### Существующие тесты — что меняется

| Файл | Изменение | Причина |
|------|-----------|---------|
| `tests/unit/transform/test_resolver.py` | `test_resolver_uses_batch_index_for_candidates()`: структура `batch_index` меняется с `{"employees": {key: [ids]}}` на `{key: [ids]}` | Удалён dataset-namespace — изоляция через lifecycle |
| `tests/unit/transform/test_resolver.py` | `_make_resolver()` factory: добавить `codec: IPendingCodec` | `IPendingCodec` инжектируется, не создаётся внутри ResolveCore |
| `tests/unit/transform/test_resolver.py` | Sweep-related setup (если есть) убирается из `_make_resolver()` | sweep-state удалён из ResolveCore |
| `tests/e2e/pipelines/test_pipeline_container_e2e.py` | Добавить `ResolveContextStage` в тестовый pipeline | `RESOLVE_CONTEXT` теперь обязательная стадия перед RESOLVE |
| `tests/e2e/pipelines/test_plan_pipeline.py` | Обновить wiring контейнера | `PIPELINE_CHECKPOINTS.PLAN` включает RESOLVE_CONTEXT |

### Новые тесты

#### Unit — доменные сервисы

| Файл | Что тестирует |
|------|--------------|
| `tests/unit/transform/resolver/test_in_memory_batch_index_service.py` | `set_index()` + `get()` happy path; `get()` до `set_index()` → `RuntimeError`; повторный `set_index()` перезаписывает (sequential runs); возвращает пустой dict при пустом индексе |
| `tests/unit/transform/resolver/test_pending_expiry_service.py` | `sweep()` делегирует к gateway; `drain_expired()` возвращает накопленный буфер и очищает его; второй `drain_expired()` возвращает пустой список |

#### Unit — новая стадия

| Файл | Что тестирует |
|------|--------------|
| `tests/unit/transform/test_resolve_context_stage.py` | `run()` буферизует все записи перед yield; вызывает `resolver.build_batch_index(all_records)`; вызывает `batch_index.set_index(index)`; прозрачно re-yields все записи (данные не изменяются); реализует `StageContract` (`stage_name`, сигнатура `run()`) |

#### Архитектурные (в `test_pipeline_architecture.py` или отдельный файл)

| Тест | Инвариант |
|------|-----------|
| `test_resolve_context_precedes_resolve_in_pipeline_checkpoints()` | `RESOLVE_CONTEXT` стоит строго перед `RESOLVE` в `PIPELINE_CHECKPOINTS.PLAN` |
| `test_batch_index_get_raises_runtime_error_before_set_index()` | `InMemoryBatchIndexService().get()` → `RuntimeError` без предварительного `set_index()` |
| `test_resolve_context_stage_satisfies_stage_contract()` | `ResolveContextStage` — структурный подтип `StageContract` (как проверяется в `test_pipeline_stage_contract.py`) |
| `test_resolve_stage_has_no_internal_buffering()` | `ResolveStage.run()` — ленивый генератор, не буферизует источник (проверяется через mock-source с счётчиком вызовов) |

### Примечание по `batch_index` структуре

Тест `test_resolver_uses_batch_index_for_candidates()` использовал `batch_index = {"employees": {key: [ids]}}`. После изменений структура плоская: `batch_index = {key: [ids]}`. Тест обновляется минимально — только убирается внешний dataset-ключ. Семантика теста (resolver находит кандидата через batch_index) сохраняется.

---

## 🔗 Связанные документы

- [RESOLVER-PROBLEM-001](./RESOLVER-PROBLEM-001-resolve-stage-mixed-responsibilities.md) — решаемая проблема
- [TRANSFORM-DEC-007](../transform/TRANSFORM-DEC-007-declarative-pipeline-checkpoints.md) — разблокируемое решение; `RESOLVE_CONTEXT` дополняет декларативный реестр
- [TRANSFORM-DEC-008](../transform/TRANSFORM-DEC-008-pending-codec-standalone-feature.md) — смежное: `pending_codec` в standalone модуль
- [MATCHER-DEC-001](../matcher/MATCHER-DEC-001-externalize-dedup-state-to-di-service.md) — симметричное решение для Matcher; вводит `ISourceDedupStore` и `PipelineRunContext`
- [docs/dev/layers/resolver/functional-capabilities-map.md](../../dev/layers/resolver/functional-capabilities-map.md) — полная карта функциональных возможностей

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-24 | Решение сформулировано в ходе обсуждения RESOLVER-PROBLEM-001 |
| 2026-02-24 | Принято; первоначально буферизация была в `PlanningPipeline` |
| 2026-02-24 | Пересмотрено: явная буферизация в `PlanningPipeline` нарушает инвариант декларативного реестра (TRANSFORM-DEC-007). Принят `ResolveContextStage` (`CheckpointName.RESOLVE_CONTEXT`) как полноправная стадия конвейера |
| 2026-02-24 | Уточнения после детального анализа: (1) `IBatchIndexService.build()` переименован в `set_index()` — явнее семантика; (2) добавлен `RuntimeError`-guard в `get()` при вызове до `set_index()`; (3) `IPendingExpiryService` подключён через `PlanningPipelineHooks.on_stage_complete`, не через `PlanningPipeline`; (4) `PipelineRunContext` объединяет `ISourceDedupStore` (MATCHER-DEC-001) + `IBatchIndexService`; (5) `dataset`-параметр удалён из сигнатур — изоляция через per-run lifecycle, не namespace в ключах |
