# MATCHER-PROBLEM-002: MatchStage заблокирована от PipelineOrchestrator-композиции — micro-batch оркестрация и scope cleanup вынесены наружу

> **Статус**: Открыта / Решена в [MATCHER-DEC-002](./MATCHER-DEC-002-internalize-batch-execution-to-stage.md)
> **Дата создания**: 2026-02-25
> **Затронутые компоненты**: `MatchStage`, `MatchUseCase`, `open_match_runtime`, `PlanningPipeline`, `PipelineOrchestrator`, `PIPELINE_CHECKPOINTS`

---

## 📋 Контекст

После реализации [MATCHER-DEC-001](./MATCHER-DEC-001-externalize-dedup-state-to-di-service.md) `MatchCore` стал чистым алгоритмом без mutable state. Однако `MatchStage` по-прежнему не является полноправным участником `PipelineOrchestrator` — её исполнение невозможно без специального внешнего обрамления: `open_match_runtime` + `iter_matched_ok`.

Это симметричная проблема с [RESOLVER-PROBLEM-001](../resolver/RESOLVER-PROBLEM-001-resolve-stage-mixed-responsibilities.md), где `ResolveStage` не мог войти в оркестратор из-за буферизации и sweep в hot path. Для Resolver проблема решена в [RESOLVER-DEC-001](../resolver/RESOLVER-DEC-001-externalize-mechanics-to-di-services.md) — `ResolveStage.run()` стал чистым per-record трансформером.

Для Matcher аналогичная проблема остаётся нерешённой: две инфраструктурные механики заблокированы снаружи стадии.

---

## ⚠️ Проблема

`MatchStage` совмещает с точки зрения оркестрации два внешних зависимых механизма:

### 1. Micro-batch оркестрация в `MatchUseCase`

`MatchStage.run(source)` вызывается не напрямую с потоком, а порциями через `MatchUseCase._iter_matched()`:

```python
# connector/usecases/match_usecase.py
def _iter_matched(self, enriched_source, match_stage):
    for batch in iter_micro_batches(
        enriched_source,
        batch_size=self.batch_size,          # per-command параметры
        flush_interval_ms=self.flush_interval_ms,
    ):
        for matched in match_stage.run(batch):
            yield matched
```

`batch_size` и `flush_interval_ms` — параметры `MatchUseCase`, передаются в каждый handler вручную из `app_settings.matching_runtime`. Стадия не контролирует свой batch-режим исполнения — им управляет use-case снаружи.

### 2. Scope cleanup в `open_match_runtime`

`clear_runtime_scope()` вызывается в `finally` контекстного менеджера, который обязан обрамлять каждый вызов match:

```python
# connector/delivery/cli/planning_match_runtime.py
@contextmanager
def open_match_runtime(*, run_id, match_stage, match_runtime, ...) -> Iterator[MatchRuntime]:
    runtime_scope = f"run:{run_id}"
    match_usecase = MatchUseCase(batch_size=..., flush_interval_ms=...)  # per-command wiring
    ...
    try:
        yield runtime
    finally:
        match_runtime.clear_runtime_scope(runtime_scope)  # обязательный cleanup
```

Это внешний lifecycle, который нельзя вынести в `PipelineHooks` без доработки.

---

## 🔍 Симптомы

- **Дублирование паттерна**: `open_match_runtime + iter_matched_ok` повторяется в `resolve.py` и `planning_pipeline.py` — два handler'а несут одинаковый шаблонный код.
- **`PlanningPipeline` знает о match-инфраструктуре**: вынужден вызывать `open_match_runtime`, `iter_matched_ok` — нарушает принцип «стадии не знают соседей».
- **`CheckpointName.PLAN` непоследователен**: декларирует `[MAP, NORMALIZE, ENRICH, MATCH, RESOLVE_CONTEXT, RESOLVE]`, но MATCH реализован как специальный case с отдельным context manager, а не как uniform stage в `PipelineOrchestrator`.
- **Per-command wiring `MatchUseCase`**: `batch_size`, `flush_interval_ms`, `include_matched_items` создаются в каждом handler вручную — дублирование настроек без единого источника правды.
- **`MatchStage` не может войти в `PipelineOrchestrator`**: оркестратор вызывает `stage.run(source)` — но для MATCH нужен дополнительный `open_match_runtime` wrapper, который `PipelineOrchestrator` не умеет создавать.

---

## 📊 Масштаб проблемы

- **Частота**: Всегда (архитектурный дефект)
- **Критичность**: Высокая — `PIPELINE_CHECKPOINTS.PLAN` не может быть полностью декларативным; `TRANSFORM-DEC-007` заблокирован для сценариев match/resolve/plan
- **Затронуто**: `MatchStage`, `MatchUseCase`, `open_match_runtime`, `PlanningPipeline`, `resolve.py`, `match.py` handlers

---

## 🚫 Почему это проблема?

- **`TRANSFORM-DEC-007` не реализуем полностью**: `compose(CheckpointName.PLAN)` не может включить MATCH как обычную стадию — нет механизма для `open_match_runtime` внутри compose.
- **Нарушение SRP на уровне оркестрации**: `PlanningPipeline` знает о micro-batch деталях match (через `open_match_runtime`), хотя должна только вызывать `pipeline.run(source)`.
- **Дублирование инфраструктурного кода**: каждый handler, работающий с match, воспроизводит одинаковый `open_match_runtime + iter_matched_ok + MatchUseCase(batch_size=...)` шаблон.
- **Скрытые per-command настройки**: `batch_size` и `flush_interval_ms` для match передаются через `MatchUseCase` — нет единой точки конфигурации (в отличие от `ResolverSettings` → DI).

---

## 💡 Возможные решения (обсуждение)

### Вариант 1: Оставить как есть — зафиксировать MATCH как lifecycle-границу

- **Идея**: `CheckpointName` разбивается на сегменты: `compose(ENRICH)` + `open_match_runtime` + `compose(RESOLVE_TAIL)`. MATCH — явная граница, не входит в compose.
- **Плюсы**: Нулевые изменения в match-логике. `transform_segment` заменяется на `compose(ENRICH)`.
- **Минусы**: `PIPELINE_CHECKPOINTS` остаётся неполным; `PlanningPipeline` всё ещё знает о match-инфраструктуре; паттерн нельзя унифицировать.

### Вариант 2: Интернализировать micro-batch в `MatchStage.run()` + cleanup через hooks

- **Идея**: `MatchStage.run(source)` принимает полный поток и делает micro-batching внутри через `IMatchBatchSettings`. `clear_runtime_scope()` → `IMatchScopeService` → `PipelineHooks.on_stage_complete("match")`.
- **Плюсы**: `MatchStage` становится uniform StageContract; `open_match_runtime` исчезает; `CheckpointName.PLAN` полностью декларативен; паттерн симметричен RESOLVER-DEC-001.
- **Минусы**: Требует доработки `MatchStage`, `PipelineContainer`, `PlanningPipelineHooks`; `MatchScopeService` — новый тип в DI.

---

## 🔗 Связанные документы

- [MATCHER-DEC-002](./MATCHER-DEC-002-internalize-batch-execution-to-stage.md) — принятое решение
- [MATCHER-PROBLEM-001](./MATCHER-PROBLEM-001-match-stage-mixed-responsibilities.md) — предыдущая проблема (dedup-state); решена в MATCHER-DEC-001
- [RESOLVER-PROBLEM-001](../resolver/RESOLVER-PROBLEM-001-resolve-stage-mixed-responsibilities.md) — симметричная проблема в Resolver
- [RESOLVER-DEC-001](../resolver/RESOLVER-DEC-001-externalize-mechanics-to-di-services.md) — применённое решение для Resolver; шаблон для MATCHER-DEC-002
- [TRANSFORM-DEC-007](../transform/TRANSFORM-DEC-007-declarative-pipeline-checkpoints.md) — разблокируемое решение

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-25 | Проблема выявлена при анализе блокирующих gaps для TRANSFORM-DEC-007 |
| 2026-02-25 | Подтверждена симметрия с RESOLVER-PROBLEM-001; решение принято в MATCHER-DEC-002 |
