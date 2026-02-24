# MATCHER-PROBLEM-001: MatchStage несёт инфраструктурный state и lifecycle — смешение с бизнес-логикой сопоставления

> **Статус**: Открыта / Решена в [MATCHER-DEC-001](./MATCHER-DEC-001-externalize-dedup-state-to-di-service.md)
> **Дата создания**: 2026-02-24
> **Затронутые компоненты**: `MatchStage`, `MatchCore`, `StageContract`, `PipelineContainer`, `PipelineComposer`

---

## 📋 Контекст

В рамках той же работы по [TRANSFORM-DEC-007](../transform/TRANSFORM-DEC-007-declarative-pipeline-checkpoints.md), что вскрыла проблему [RESOLVER-PROBLEM-001](../resolver/RESOLVER-PROBLEM-001-resolve-stage-mixed-responsibilities.md), исследование `MatchStage` выявило аналогичный паттерн: смешение бизнес-логики сопоставления с инфраструктурными механиками управления state.

В отличие от `ResolveStage`, которая буферизует весь поток, `MatchStage` уже обрабатывает записи per-record. Однако её ядро `MatchCore` несёт в себе mutable runtime-state дедупликации источника и требует явного lifecycle-управления снаружи, что создаёт несимметричную зависимость между стадией и оркестратором.

---

## ⚠️ Проблема

`MatchCore` совмещает в одном классе:

1. **Бизнес-логику данных** (per-record): выбор идентичности по правилам, exact/fuzzy сопоставление, scoring, формирование объяснимого решения, политика source-dedup как правило качества данных.
2. **Инфраструктурный runtime-state**: таблица `_seen_source` (`{canonical_key → fingerprint}`) хранится внутри экземпляра класса и читается/пишется в горячем пути обработки каждой записи.
3. **Lifecycle-управление из снаружи**: `reset_source_dedup()` должен вызываться до начала потока; `bind_runtime_scope(scope)` — для переключения между локальным и разделяемым хранилищем. Эти методы делают класс lifecycle-aware объектом с публичными управляющими методами, а не чистым трансформером.

Смешение этих ответственностей не нарушает StageContract на уровне сигнатуры `run()` — `MatchStage` технически per-record. Но делает невозможной чистую регистрацию в `PipelineContainer` без специального оркестрационного знания о том, когда вызывать `reset_source_dedup()` и `bind_runtime_scope()`.

---

## 🔍 Симптомы

- **Mutable state в ядре**: `MatchCore._seen_source` — изменяемый словарь внутри класса, от которого зависит корректность per-record решений. Это нарушает принцип «ядро стадии — чистый алгоритм».
- **Lifecycle-методы на публичном интерфейсе**: `reset_source_dedup()` и `bind_runtime_scope()` — публичные методы с side-effects, которые обязан вызывать внешний код в правильном порядке. Стадия неявно зависит от правильной последовательности вызовов.
- **Двойная схема хранения dedup-state**: `_seen_source` в памяти экземпляра + `cache_gateway` для scoped режима — две разные системы хранения за одним алгоритмом, управляемые через `bind_runtime_scope()`.
- **Тестирование бизнес-логики требует настройки state**: чтобы протестировать поведение source-dedup, нужно вызвать `reset_source_dedup()` и при необходимости `bind_runtime_scope()` — тест знает о lifecycle.
- **Регистрация в PipelineContainer требует оркестрационного знания**: `PlanningPipeline` вынуждена знать, что перед запуском `match_stage.run()` нужно выполнить reset и scope binding — это инфраструктурная деталь, просочившаяся в orchestration-слой.

---

## 📊 Масштаб проблемы

- **Частота**: Всегда (архитектурный дефект)
- **Критичность**: Средняя — `MatchStage` уже per-record, StageContract на уровне сигнатуры не нарушен; проблема в чистоте boundaries и сложности DI-регистрации
- **Затронуто**: `MatchCore`, `MatchStage`, `PlanningPipeline`, `PipelineContainer`

---

## 🚫 Почему это проблема?

- **Нарушает SRP**: `MatchCore` меняется по двум независимым причинам — новый алгоритм сопоставления и изменение способа хранения/сброса dedup-state.
- **Скрытая зависимость порядка вызовов**: корректность алгоритма source-dedup зависит от того, был ли вызван `reset_source_dedup()` до начала потока. Нарушение порядка ведёт к ошибкам, которые не видны на уровне типов.
- **Переключение хранилища через `bind_runtime_scope()`**: решение о том, где хранить seen-fingerprints (локально или в shared cache), принимается в runtime через вызов метода — вместо того чтобы быть зафиксированным при сборке зависимостей в DI.
- **Сложнее расширять**: добавление новой dedup-политики или нового режима scope требует трогать тот же класс, что содержит алгоритм сопоставления.

---

## 💡 Возможные решения (обсуждение)

### Вариант 1: Оставить как есть, документировать порядок вызовов
- **Идея**: Явно задокументировать, что `reset_source_dedup()` и `bind_runtime_scope()` обязаны вызываться в определённом порядке.
- **Плюсы**: Нулевые изменения кода.
- **Минусы**: Закрепляет скрытую зависимость; новый разработчик может нарушить порядок; не решает проблему mutable state в ядре.

### Вариант 2: Вынести dedup-state в отдельный injectable `ISourceDedupStore`
- **Идея**: `_seen_source` и связанная логика переходят в `ISourceDedupStore`; `MatchCore` получает его через конструктор и вызывает `store.check_and_register(key, fingerprint)` per-record.
- **Плюсы**: `MatchCore` лишается mutable state; выбор реализации (local vs scoped) фиксируется при DI-сборке, не через runtime-вызов; `reset()` — метод сервиса, а не стадии.
- **Минусы**: Небольшой дополнительный объект в dependency graph.

### Вариант 3: `ISourceDedupStore` внутри `PipelineRunContext` — shared per-run aggregator
- **Идея**: `ISourceDedupStore` и `IBatchIndexService` (из [RESOLVER-DEC-001](../resolver/RESOLVER-DEC-001-externalize-mechanics-to-di-services.md)) объединяются в `PipelineRunContext` — один Singleton per run в `PipelineContainer`.
- **Плюсы**: Единая точка per-run state для обеих стадий; упрощает DI-wiring; явно выражает «это state одного прогона».
- **Минусы**: Стадии получают доступ только к своей части через свой порт — `PipelineRunContext` не протекает в бизнес-логику.

---

## 🔗 Связанные документы

- [MATCHER-DEC-001](./MATCHER-DEC-001-externalize-dedup-state-to-di-service.md) — принятое решение
- [RESOLVER-PROBLEM-001](../resolver/RESOLVER-PROBLEM-001-resolve-stage-mixed-responsibilities.md) — аналогичная проблема в Resolver
- [RESOLVER-DEC-001](../resolver/RESOLVER-DEC-001-externalize-mechanics-to-di-services.md) — решение для Resolver; вводит `IBatchIndexService`, которое объединяется с `ISourceDedupStore` в `PipelineRunContext`
- [TRANSFORM-DEC-007](../transform/TRANSFORM-DEC-007-declarative-pipeline-checkpoints.md) — декларативный реестр чекпоинтов (в контексте которого обнаружена проблема)
- [docs/dev/layers/matcher/functional-capabilities-map.md](../../dev/layers/matcher/functional-capabilities-map.md) — полная карта функциональных возможностей; раздел 11.2 описывает проблему dedup-state как `Stage technical support` с рекомендацией выделения

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-24 | Проблема выявлена при анализе MatchStage в контексте TRANSFORM-DEC-007 и RESOLVER-PROBLEM-001 |
| 2026-02-24 | Функциональный аудит подтверждён по functional-capabilities-map.md (разделы 4, 10, 11.2) |
| 2026-02-24 | Решение принято в MATCHER-DEC-001 |
