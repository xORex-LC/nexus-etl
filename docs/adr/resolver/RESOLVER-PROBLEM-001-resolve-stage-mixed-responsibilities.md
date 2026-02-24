# RESOLVER-PROBLEM-001: ResolveStage перегружена — смешение бизнес-логики с инфраструктурными механиками

> **Статус**: Открыта / Решена в [RESOLVER-DEC-001](./RESOLVER-DEC-001-externalize-mechanics-to-di-services.md)
> **Дата создания**: 2026-02-24
> **Затронутые компоненты**: `ResolveStage`, `ResolveCore`, `StageContract`, `PipelineContainer`, `PipelineComposer`

---

## 📋 Контекст

В рамках реализации [TRANSFORM-DEC-007](../transform/TRANSFORM-DEC-007-declarative-pipeline-checkpoints.md) (`PipelineComposer` + декларативный реестр чекпоинтов) предпринята попытка зарегистрировать `ResolveStage` как стандартную стадию в `PipelineContainer` и включить её в `PIPELINE_CHECKPOINTS`.

Попытка вскрыла архитектурную проблему: `ResolveStage` не реализует `StageContract` и не может быть встроена в конвейер наравне с `MapStage`, `NormalizeStage`, `EnrichStage`. Анализ показал, что причина — не в природе самой задачи resolve, а в том, что стадия несёт ответственности двух разных уровней: бизнес-логику данных и инфраструктурные механики обработки потока.

---

## ⚠️ Проблема

`ResolveStage` и её ядро `ResolveCore` совмещают в одном классе:

1. **Бизнес-логику данных** (per-record): гейт по статусу сопоставления, merge/fill-from-existing, link resolution, pending/hard-error политика, вычисление операции (create/update/skip), diff, source reference, секреты.
2. **Инфраструктурные механики**: накопление всего потока в буфер, построение batch_index, периодический sweep просроченных pending, сериализация pending payload в JSON.

Смешение делает `ResolveStage` несовместимой со `StageContract` (`run(source) → result`, one-record-in / one-record-out) и закрывает путь к её регистрации в `PipelineContainer` как обычной стадии.

---

## 🔍 Симптомы

- **Сигнатура нарушает протокол**: `ResolveStage.run(source, *, dataset)` — лишний kwarg не входит в `StageContract(source) -> Iterable`.
- **Внутренняя буферизация всего потока**: `run()` делает `list(source)` для построения `batch_index` до начала обработки записей — нарушение streaming-контракта.
- **Housekeeping в горячем пути**: `ResolveCore._maybe_sweep_expired()` вызывается перед каждой записью — sweep просроченных pending не связан с решением по текущей строке, но занимает hot path.
- **Сериализация в ядре**: `ResolveCore._serialize_pending_payload()` — формирование storage-JSON живёт в том же классе, что и алгоритм разрешения конфликтов.
- **Нельзя добавить в `PIPELINE_CHECKPOINTS`**: `compose(CheckpointName.PLAN)` не может включить `resolve_stage` как рядовую стадию — требуется специальная обработка, что нарушает инвариант DEC-007.

---

## 📊 Масштаб проблемы

- **Частота**: Всегда (архитектурный дефект, а не runtime-условие)
- **Критичность**: Блокирующая для второго этапа TRANSFORM-DEC-007; средняя для текущего функционала
- **Затронуто**: Все ETL-пайплайны со стадией resolve, PipelineContainer, PipelineComposer, PlanningPipeline

---

## 🚫 Почему это проблема?

- **Блокирует DEC-007**: `ResolveStage` не может войти в декларативный реестр чекпоинтов — нарушен контракт стадии.
- **Нарушает SRP**: класс меняется по двум несвязанным причинам — новый алгоритм resolve и изменение механики буферизации/sweep.
- **Затрудняет расширение**: новая логика разрешения конфликтов или ссылок будет добавляться в класс, который также управляет буферизацией и sweep — растёт coupling.
- **Затрудняет тестирование**: тест чистой бизнес-логики resolve требует настройки инфраструктурного state (`_last_sweep_at`, `batch_index`).
- **Нарушает 1:1 инвариант**: если стадия буферизует весь поток и затем отдаёт батч, upstream delivery-report и счётчики записей строятся на нарушенном предположении.

---

## 💡 Возможные решения (обсуждение)

### Вариант 1: Принять несовместимость — специальная обработка в PipelineComposer
- **Идея**: `compose()` знает о том, что resolve — особая стадия, и применяет разный путь сборки.
- **Плюсы**: Минимум изменений в `ResolveCore`.
- **Минусы**: Нарушает инвариант DEC-007 («все стадии обрабатываются одинаково»), закрепляет технический долг, накапливает исключения.

### Вариант 2: BatchableStage — буферизация через оркестратор
- **Идея**: `ResolveStage` реализует `BatchableStage` с `batch_size=∞`, `PipelineOrchestrator` буферизует поток и передаёт батч в `run()`.
- **Плюсы**: Буферизация структурно оформлена.
- **Минусы**: `dataset` kwarg всё равно нарушает протокол; sweep и сериализация остаются в ядре; 1:1 инвариант не восстанавливается.

### Вариант 3: Вынести инфраструктурные механики в DI-сервисы
- **Идея**: `IBatchIndexService` (pre-computation), `IPendingExpiryService` (sweep/drain) регистрируются как DI-синглтоны; `ResolveStage.run()` обрабатывает одну запись, делегируя state сервисам.
- **Плюсы**: `ResolveStage` реализует `StageContract`; SRP восстановлен; DEC-007 разблокирован; расширение новой логикой локально.
- **Минусы**: Буферизация для построения `batch_index` перемещается в `PlanningPipeline` — становится явной оркестрационной ответственностью, а не скрытой деталью стадии.

---

## 🔗 Связанные документы

- [RESOLVER-DEC-001](./RESOLVER-DEC-001-externalize-mechanics-to-di-services.md) — принятое решение
- [TRANSFORM-DEC-007](../transform/TRANSFORM-DEC-007-declarative-pipeline-checkpoints.md) — декларативный реестр чекпоинтов (заблокирован этой проблемой)
- [TRANSFORM-PROBLEM-008](../transform/TRANSFORM-PROBLEM-008-pending-codec-stage-coupling.md) — смежная проблема: pending_codec привязан к стадии resolver
- [TRANSFORM-DEC-008](../transform/TRANSFORM-DEC-008-pending-codec-standalone-feature.md) — вынесение pending_codec в standalone модуль
- [docs/dev/layers/resolver/functional-capabilities-map.md](../../dev/layers/resolver/functional-capabilities-map.md) — полная карта функциональных возможностей и аудит ответственности

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-24 | Проблема выявлена при попытке реализации TRANSFORM-DEC-007 (включение resolve в PIPELINE_CHECKPOINTS) |
| 2026-02-24 | Проведён аудит ответственностей; решение принято в RESOLVER-DEC-001 |
