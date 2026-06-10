# ECS Logging Conventions (поля, уровни, словарь действий)

> **Статус**: Планируется (вводится [OBSERVABILITY-DEC-003](../../../adr/observability/OBSERVABILITY-DEC-003-ecs-renderer-and-field-mapping.md), Фаза 1)
> **Машинно-авторитетный источник**: `connector/infra/logging/ecs.py` (таблица маппинга + enum'ы `EventAction`/`EventOutcome`/`EventKind`)
> **Этот документ**: прозаический каталог для людей — что есть какое поле, какой уровень когда, какие действия существуют и как пополнять словарь.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [✅ Принципы Построения Таксономии](#-принципы-построения-таксономии)
- [🧭 Где живёт истина](#-где-живёт-истина)
- [🗂️ Каталог ECS-полей](#️-каталог-ecs-полей)
- [🔬 Анатомия лог-строки (worked examples)](#-анатомия-лог-строки-worked-examples)
- [🎚️ Правила уровней](#️-правила-уровней)
- [🧱 Зона 1: Runtime Orchestrator / CLI Lifecycle](#-зона-1-runtime-orchestrator--cli-lifecycle)
- [🧱 Зона 2: Command-Specific Delivery Lifecycle](#-зона-2-command-specific-delivery-lifecycle)
- [🧱 Зона 3: Pipeline Stage Lifecycle](#-зона-3-pipeline-stage-lifecycle)
- [📖 Словарь `event.action`](#-словарь-eventaction)
- [📋 Карта call-site → event.action (по всему коду)](#-карта-call-site--eventaction-по-всему-коду)
- [🔖 `event.outcome` и `event.kind`](#-eventoutcome-и-eventkind)
- [🛠️ Как пополнять](#️-как-пополнять)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

Все JSON-логи приводятся к [Elastic Common Schema (ECS)](https://www.elastic.co/docs/reference/ecs/ecs-field-reference)
процессором `ecs_transform` (см. [observability-logging.md](./observability-logging.md) и
[DEC-003](../../../adr/observability/OBSERVABILITY-DEC-003-ecs-renderer-and-field-mapping.md)).
Этот документ фиксирует **семантику**: какие поля мы эмитим, что они значат, какой уровень логирования
когда выбирать и какие значения допустимы для `event.action`/`event.outcome`/`event.kind`.

Три цели логирования (ими руководствуемся при выборе уровня и полей):
1. **Трассируемость** — по `trace.id` можно восстановить полный ход одного прогона.
2. **Actionability** — каждое WARNING+ содержит достаточно контекста, чтобы понять проблему без чтения кода.
3. **Signal-to-noise** — DEBUG подробен; INFO — операционная база; выше — редко и значимо.

Формат ключей — **dotted** (`"log.level"`, `"event.action"`, `"trace.id"`); ES/Filebeat
разворачивают их в объекты автоматически.

---

## ✅ Принципы построения таксономии

Короткий checklist, которым руководствуемся при наполнении `event.action`, выборе ECS-полей и
раскладке событий по уровням. Если новая запись не проходит этот список, её не стоит сразу
добавлять в taxonomy.

1. **Таксономия описывает наблюдаемое поведение, а не структуру кода.**
   Новый action вводится для операционно значимого события (`run`, `stage`, `retry`, `fallback`,
   `external I/O`, `failure`), а не потому, что в коде появился новый helper/method.
2. **Один action = одно устойчивое семантическое значение.**
   `event.action` должен переживать рефакторинг реализации. Переименование функции не должно
   автоматически требовать нового action.
3. **Сначала ECS canonical field, потом project namespace, потом `labels.*`.**
   Если для смысла есть подходящее ECS-поле — используем его. Если нет — кладём в `nexus.*`.
   `labels.*` остаётся для плоской корреляции и простых keyword-тегов, а не для всего подряд.
   Для текущей taxonomy это означает: `run_id -> trace.id`, `component -> service.type`,
   `scope -> nexus.subsystem`, `dataset -> event.dataset`, `stage -> nexus.stage.name`,
   `pipeline_run_id -> labels.pipeline_run_id`.
4. **Различия выражаем сначала полями, а не раздуванием action-словаря.**
   Перед добавлением нового action проверяем, нельзя ли выразить различие через `event.outcome`,
   `event.type`, `nexus.stage.name`, `nexus.subsystem`, `error.*` или `nexus.*`.
5. **Каждый action обязан иметь корзину по шумности и назначению.**
   Минимальные корзины: `INFO milestone`, `DEBUG decision`, `TRACE diagnostic`.
   Action без корзины в taxonomy не принимается.
6. **`INFO` должен давать целостную картину одного прогона.**
   На одном `INFO`-потоке оператор должен увидеть старт команды, ключевые этапы, завершение стадий
   и итог прогона.
7. **`DEBUG` описывает решения, а не дублирует milestone-события.**
   `DEBUG` нужен для `hit/miss`, `retry`, `skip`, `fallback`, `candidate rejected`,
   `branch selected`, а не для второго сообщения о том же самом старте/завершении.
8. **`TRACE` — только для режима расследования.**
   В `TRACE` попадают детальные execution seams, циклы, повторные входы, подозрительные переходы
   и иные диагностические события. `TRACE` не должен становиться свалкой "всего подряд".
9. **Не каждый log call-site требует отдельный taxonomy entry.**
   Если два места описывают один и тот же тип поведения, у них должен быть один action с разными
   полями, а не два почти одинаковых action.
10. **Таксономия строится от operational use-case, а не от полного ECS catalog.**
    `fields.csv` — это библиотека доступных полей, а не обязательный список к внедрению. Мы
    формируем собственный `nexus-etl` ECS profile.
11. **Таксономия должна быть пригодна для постепенной миграции.**
    Сначала фиксируем vocabulary и field profile, потом внедряем call-site-by-call-site. Нельзя
    требовать одномоментной переписи всех логов.
12. **Одна capability может иметь две observability-perspective: command и subsystem.**
    `cache`, `vault`, `target` и другие capability могут наблюдаться и как пользовательская
    CLI-команда, и как внутренняя подсистема, которую вызывает другой flow. Это не дублирование:
    command-zone отвечает на вопрос «какой сценарий запущен и чем завершился», subsystem-zone —
    «как вела себя capability внутри runtime/pipeline».
13. **Таксономия обязана описывать не только события и поля, но и уровень детализации.**
    Для каждой зоны нужно фиксировать не только `какие action существуют` и `какие поля они
    несут`, но и `на каком уровне детализации` они допустимы: `INFO milestone/summary`,
    `DEBUG record/decision`, `TRACE rule-by-rule / execution seam`. Иначе одна и та же зона
    начнёт логироваться с разной плотностью и без общего контракта.
14. **У taxonomy два источника истины: human и machine.**
    Этот документ — человекочитаемая семантика и правила. Кодовый модуль (`ecs.py` /
    `ecs_taxonomy.py`) — машинно-авторитетный реестр enum'ов, buckets и validation helpers.

---

## 🧭 Где живёт истина

| Что | Где | Почему там |
|---|---|---|
| Таблица соответствия (внутренний ключ → ECS) | `ecs.py` | Один процессор-источник, проверяется контрактным тестом |
| Словарь `event.action` (членство) | `EventAction` (StrEnum) в `ecs.py` | Машинно-валидируется; «добавить» = член enum |
| `event.outcome` / `event.kind` (членство) | `EventOutcome` / `EventKind` в `ecs.py` | То же |
| `ECS_VERSION` | константа в `ecs.py` | Декларируется в `ecs.version`, апгрейд — ревью |
| Описания действий, правила уровней, каталог полей | **этот документ** | Людям нужны описания, которых enum не несёт |

Правило против дрейфа: **членство** — авторитетно в коде (enum + тест); **описания** — здесь.
Добавление действия правит оба места (контрактный тест сверяет, что enum и используемые значения согласованы).

---

## 🗂️ Каталог ECS-полей

Поля, которые эмитит `ecs_transform`. Источник значения — contextvars, runtime-meta или kwargs call-site.

### Базовые
| Поле | Тип | Когда | Описание |
|---|---|---|---|
| `@timestamp` | date | всегда | Время события, UTC (ISO-8601) |
| `message` | text | всегда | Человекочитаемое сообщение (бывший structlog `event`) |
| `ecs.version` | keyword | всегда | Версия ECS, на которую мы маппим (= `ECS_VERSION`) |

### `log.*`
| Поле | Когда | Описание |
|---|---|---|
| `log.level` | всегда | `debug`/`info`/`warning`/`error`/`critical` (lowercase) |
| `log.logger` | всегда | Имя логгера, напр. `nexus.normalizer` |

### `event.*`
| Поле | Когда | Описание |
|---|---|---|
| `event.action` | всегда желательно | Verb-noun из словаря (см. ниже) |
| `event.dataset` | когда известен датасет | Canonical business dataset name: `employees`, `organizations` |
| `event.outcome` | на завершении | `success`/`failure`/`unknown` |
| `event.duration` | на завершении | Длительность в **наносекундах** (ECS-тип long) |
| `event.kind` | опц. | `event` (default)/`metric`/`state` |

### `trace.*`
| Поле | Когда | Описание |
|---|---|---|
| `trace.id` | всегда | UUID одного command/pipeline run; canonical correlation key для всех событий данного запуска |

### `error.*` (только ERROR/CRITICAL) — **два источника**
`error.*` собирается ИЛИ из ручных kwargs на call-site (`error_type`/`error`/`diag_code` — так уже
пишет, напр., [orchestrator.py:494](../../../../connector/delivery/cli/runtime/orchestrator.py)),
ИЛИ из структурного `exception`-словаря (`logger.exception(...)` → `ExceptionDictTransformer`). `ecs_transform`
поддерживает оба. Детали схлопывания цепочки исключений — Тема 4 worknote.

| Поле | Источник: ручные kwargs | Источник: `exception`-словарь |
|---|---|---|
| `error.type` | `error_type` | класс верхнего (всплывшего) исключения |
| `error.message` | `error` | `str(exc)` |
| `error.code` | `diag_code` | — |
| `error.stack_trace` | — | развёрнутый трейс всей цепочки (после redaction) |

### `service.*` / `process.*` / `host.*`
| Поле | Источник |
|---|---|
| `service.name` | константа `nexus-etl` |
| `service.type` | `ServiceComponent`: `planner`, `applier`, `cache`, `vault`, `observability`, … |
| `service.version` | `app_version` runtime-meta |
| `process.pid` | `pid` runtime-meta |
| `host.name` | `host` runtime-meta |

### `nexus.*` (project-specific operational context)
| Поле | Когда | Описание |
|---|---|---|
| `nexus.subsystem` | ситуативно | Внутренняя функциональная зона: `core`, `config`, `dsl`, `report`, `log`, `observability`, `cache`, `vault`, … |
| `nexus.stage.name` | внутри pipeline stage events | Canonical internal pipeline stage name из `StageContract.stage_name`: `map`, `normalize`, `enrich`, `match`, `resolve_context`, `resolve` |
| `nexus.stage.items_count` | stage completion/error, когда есть hook stats | Количество элементов, вышедших из stage stream (`PipelineHooks` `stats["items"]`) |
| `nexus.stage.rows_total` | stage completion, reporter-derived | Row counter из `StageResultReporter.snapshot()` / `publish_context()` |
| `nexus.stage.ok_rows` | stage completion, reporter-derived | Canonical generic ok counter; в report context дополнительно есть stage-specific ok label |
| `nexus.stage.failed_rows` | stage completion, reporter-derived | Canonical generic failed counter; в report context дополнительно есть stage-specific failed label |
| `nexus.stage.warnings_rows` | stage completion, reporter-derived | Число rows с warnings по reporter policy |
| `nexus.stage.vault_candidates_rows` | stage completion, reporter-derived | Rows с secret/vault candidate fields |
| `nexus.stage.vault_candidates_fields_total` | stage completion, reporter-derived | Суммарное число secret/vault candidate fields |
| `nexus.*` | по необходимости | Project-specific поля, для которых нет подходящего ECS canonical field |

### `labels.*` (лёгкая корреляция и простые keyword-теги)
| Поле | Когда | Описание |
|---|---|---|
| `labels.pipeline_run_id` | когда нужен более широкий execution-correlation | Correlation id pipeline execution, который может объединять несколько command run / artifact chain и потому не совпадать по смыслу с `trace.id` |
| `labels.<любой kwarg>` | — | **catch-all**: всё неучтённое уходит сюда (`record_count`, `row_ref`, …) |

> **Catch-all**: любой бизнес-kwarg без явного ECS-таргета попадает в `labels.*`. Это санкционированный
> ECS «мешок» keyword-полей — ничего не теряем и не плодим корневые не-ECS ключи (см. тест №3 в DEC-003).

### Canonical mapping для correlation/pipeline осей

| Внутренний смысл | Canonical field | Почему |
|---|---|---|
| Один command/pipeline run | `trace.id` | ближайший ECS-native correlation field для одного запуска |
| Более широкий pipeline execution | `labels.pipeline_run_id` | это плоский correlation id между связанными command run / artifacts, но не trace/span/transaction в ECS-смысле |
| Исполняющий компонент | `service.type` | компонентная идентичность процесса/команды |
| Внутренняя функциональная зона | `nexus.subsystem` | для неё нет точного ECS canonical field |
| Business dataset | `event.dataset` | лучший ECS-fit для имени обрабатываемого датасета |
| Pipeline stage | `nexus.stage.name` | у внутренней стадии нет устойчивого ECS canonical field; это project-specific execution axis |

### Разграничение `trace.id` и `labels.pipeline_run_id`

- `trace.id` — **обязательный** идентификатор одного конкретного command/pipeline run. Это
  базовый correlation key, по которому собирается полный лог одного запуска.
- `labels.pipeline_run_id` — **опциональный более широкий** идентификатор execution-цепочки,
  если нужно связать несколько запусков, артефактов или runtime phases в один business flow.
- Если более широкая execution-цепочка в конкретном сценарии отсутствует, `labels.pipeline_run_id`
  можно не эмитить или при текущей runtime-модели приравнивать к `trace.id`. Семантически эти
  поля всё равно считаются разными и не должны смешиваться в taxonomy.

### Разграничение `event.dataset` и `nexus.stage.*`

- `event.dataset` отвечает на вопрос **что обрабатываем**. Это business axis (`employees`,
  `organizations`) и потому он живёт в ECS `event.*`.
- `nexus.stage.name` отвечает на вопрос **на каком внутреннем этапе пайплайна находится событие**.
  Это execution axis (`map`, `normalize`, `resolve_context`, `resolve`), а не business entity.
- `nexus.stage.*` — object namespace для stage execution telemetry. Не использовать одновременно
  leaf-поле `nexus.stage`, иначе будет конфликт mapping object vs keyword.
- Runtime/CLI lifecycle события могут вообще не иметь `nexus.stage.*`, если событие произошло
  вне конкретной pipeline stage.

---

## 🔬 Анатомия лог-строки (worked examples)

Каждая строка = **общая шапка** (всегда, из contextvars + runtime-meta) + **поля конкретного вызова**.
Шапка: `@timestamp, message, log.level, log.logger, trace.id, labels.pipeline_run_id,
service.name, service.type, service.version, host.name, process.pid, ecs.version`.

Ниже — реальные call-sites «как сейчас» → «ECS после `ecs_transform`».

### A. INFO — старт refresh кэша
Call-site ([cache_refresh_service.py:87](../../../../connector/usecases/cache_refresh_service.py)):
`logger.info("Cache refresh started", scope="cache", page_size=…, max_pages=…, dataset=…)`
(команда `cache refresh` → контекст `component=cache`)
```json
{"@timestamp":"2026-06-10T08:00:01Z","message":"Cache refresh started","log.level":"info",
 "log.logger":"nexus.cache","event.action":"cache-refresh-started","event.dataset":"employees",
 "trace.id":"01J…","labels.pipeline_run_id":"01J…","service.name":"nexus-etl","service.type":"cache",
 "nexus.subsystem":"cache","labels.page_size":500,"labels.max_pages":20,"service.version":"1.4.0",
 "host.name":"etl-01","process.pid":4123,"ecs.version":"8.11"}
```

### B. DEBUG — lookup словаря (внутри enrich → `component=enricher`, `scope=dictionary`)
Call-site ([dictionaries/telemetry.py:133](../../../../connector/infra/dictionaries/telemetry.py)):
сейчас `message` = код `"lookup_hit"`; в ECS код уходит в `event.action`, а `message` становится человеческим (см. правило Темы 3).
```json
{"@timestamp":"…","message":"Dictionary lookup hit","log.level":"debug","log.logger":"nexus.enricher",
 "event.action":"dictionary-lookup","trace.id":"01J…","service.type":"enricher",
 "nexus.subsystem":"dictionary","labels.dict_name":"departments","labels.op":"lookup","labels.backend":"polars",
 "labels.result_count":1,"ecs.version":"8.11"}
```

### C. ERROR — ошибка загрузки DSL-спеки (ручные error-kwargs, без `exc_info`)
Call-site ([orchestrator.py:494](../../../../connector/delivery/cli/runtime/orchestrator.py)):
`logger.error("DSL load error", scope="dsl", diag_code=exc.code, error=str(exc), error_type=exc.__class__.__name__)`
```json
{"@timestamp":"…","message":"DSL load error","log.level":"error","log.logger":"nexus.planner",
 "event.action":"spec-load-failed","event.outcome":"failure","error.type":"DslLoadError",
 "error.message":"…","error.code":"DSL_SPEC_INVALID","trace.id":"01J…","service.type":"planner",
 "nexus.subsystem":"dsl","ecs.version":"8.11"}
```

> Примеры A–C — целевой вид (Фаза 2, с `event.action`). В Фазе 1 ECS-форма уже валидна, но `event.action`
> ещё пуст для не-наполненных call-sites — действия проставляются по [карте ниже](#-карта-call-site--eventaction-по-всему-коду).

---

## 🎚️ Правила уровней

| Уровень | Когда | Обязательные поля |
|---|---|---|
| **CRITICAL** | Процесс не может продолжаться, аварийная остановка (DI/конфиг/необработанное на верхнем уровне) | `message`, `log.level`, `event.action`, `event.outcome=failure`, `error.*`, `trace.id` |
| **ERROR** | Прогон/значимая суб-операция упали (исключение или явный fail). Процесс может продолжиться, но этот прогон неуспешен | `message`, `event.action`, `event.outcome=failure`, `event.dataset`, `trace.id`, `nexus.stage.name`, `error.*` |
| **WARNING** | Неожиданное, но восстановимое; degraded-решение. Исключение не требуется | `message`, `event.action`, `event.dataset`, `trace.id`. **Без** `error.stack_trace`, если он не несёт диагностики |
| **INFO** | Значимое операционное событие. База в проде | `message`, `event.action`, `event.outcome` (на завершении), `event.dataset`, `event.duration` (на завершении), `trace.id`, `nexus.stage.name` (в стадии) |
| **DEBUG** | Подробная трассировка для разработчика (выкл. в проде) | `message`, `event.action`, `trace.id` + контекст, чтобы запись была самодостаточной |

**Минимум на прогон (INFO):** одно событие на старте прогона; старт+финиш каждой стадии (с `event.duration`
и счётчиком записей в `labels`); финиш прогона с `event.outcome`.

**Что НЕ логировать:** секреты/токены/пароли (их маскирует redaction, но и не передавать осознанно);
целые DataFrame'ы (только форму — высоту/колонки); одно и то же событие на двух уровнях; трейсбэки на WARNING.

---

## 🧱 Зона 1: Runtime orchestrator / CLI lifecycle

Первая рабочая зона taxonomy — общий lifecycle CLI-команды и runtime-обвязки в
`connector/delivery/cli/runtime/orchestrator.py`. Это **не** бизнес-события отдельных подсистем
(`cache`, `vault`, `target`, `topology`), а общий каркас исполнения команды:
bootstrap → validation → init → handler → finalize → pointers/ledger → shutdown.

### Принципы именно для этой зоны

- События зоны описывают **общий lifecycle команды**, а не детали конкретного use case.
- Если событие одинаково важно для `mapping`, `import plan`, `import apply`, `check-api`, оно
  фиксируется здесь как runtime-milestone, а не дублируется в taxonomy по подсистемам.
- Различия между командами выражаются через `service.type`, `event.dataset`,
  `nexus.subsystem`, а не через отдельный action на каждую команду.
- Best-effort observability события (`ledger`, `pointer`, `retention`) остаются в runtime-зоне,
  потому что они относятся к orchestration/finalization, а не к бизнес-логике.

### Canonical taxonomy для зоны

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `command-started` | INFO milestone | `info` | — | `event.action`, `trace.id`, `service.type` | `nexus.subsystem=core` | runtime enters command execution |
| `command-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.type`, `error.message`, `trace.id` | `nexus.subsystem=core` | unhandled command-level exception |
| `config-load-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=config` | `SettingsLoadError` path |
| `spec-load-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=dsl`, `error.code` | `DslLoadError` path |
| `runtime-validation-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=config`, `nexus.runtime.exit_code` | invalid CLI/runtime requirements |
| `resource-init-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=core`, `nexus.resource.phase=init` | generic DI/runtime init failure |
| `cache-init-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=cache` | sqlite/cache init failure |
| `vault-startup-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=vault`, `error.code` | vault startup / key validation failure |
| `resource-shutdown-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=core`, `nexus.resource.phase=shutdown`, `nexus.resource.subcontainer` | one subcontainer shutdown failed |
| `resource-shutdown-completed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id` | `nexus.subsystem=core`, `nexus.resource.failed_subcontainers` | shutdown finished with one or more failures |
| `report-written` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id` | `nexus.subsystem=report`, `file.path` | report JSON persisted successfully |
| `report-finalize-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=report` | final report assembly or write failed |
| `log-written` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id` | `nexus.subsystem=log`, `file.path` | non-report path finalized active log |
| `ledger-record-failed` | DEBUG decision | `warning` | `failure` | `event.action`, `event.outcome`, `trace.id` | `nexus.subsystem=observability`, `nexus.observability.phase=ledger-build` | report/non-report ledger record build failed |
| `ledger-append-failed` | DEBUG decision | `warning` | `failure` | `event.action`, `event.outcome`, `trace.id` | `nexus.subsystem=observability`, `nexus.observability.phase=ledger-append` | backend append failed |
| `pointer-publish-failed` | DEBUG decision | `warning` | `failure` | `event.action`, `event.outcome`, `trace.id` | `nexus.subsystem=observability`, `nexus.observability.phase=pointer-publish` | latest pointer update failed |
| `retention-sweep-failed` | DEBUG decision | `warning` | `failure` | `event.action`, `event.outcome`, `trace.id` | `nexus.subsystem=observability`, `nexus.observability.phase=retention-sweep` | startup sweeper failed |

### Нормализация и анти-дублирование

- Не плодить action по имени конкретной CLI-команды (`mapping-started`, `check-api-started`,
  `import-plan-started`) на уровне runtime. Для этого уже есть `service.type`.
- Не плодить отдельные action для каждой вторичной observability-операции (`report-pointer-failed`,
  `plan-pointer-failed`, `log-pointer-failed`), если различие можно выразить через
  `nexus.observability.phase` или `nexus.artifact.kind`.
- Не использовать runtime-зону для событий бизнес-подсистем (`cache-refresh-started`,
  `target-write-failed`, `dictionary-lookup`). Они будут жить в своих зонах taxonomy.

### Минимальный field profile для зоны

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | всегда из canonical словаря зоны |
| `event.outcome` | required on completion/failure | `success`/`failure`; не нужен на `command-started` |
| `trace.id` | required | основной correlation key одного command/pipeline run |
| `labels.pipeline_run_id` | optional | только если нужен correlation шире одного `trace.id` |
| `service.type` | required | идентичность исполняющего компонента/команды |
| `event.dataset` | optional | только для dataset-aware runtime events; не обязателен для общего bootstrap/shutdown lifecycle |
| `nexus.stage.*` | not used by default | runtime zone не должна искусственно притягивать stage, если событие вне pipeline stage |
| `nexus.subsystem` | recommended | `core`, `config`, `dsl`, `report`, `log`, `observability`, `cache`, `vault` |
| `error.type`, `error.message` | required on error/warning-failure events | оба источника (`exception` dict и manual kwargs) поддерживаются |
| `error.code` | optional | когда есть domain/diag code |
| `file.path` | optional | `report-written`, `log-written`, позднее `plan-written` |
| `nexus.resource.phase` | optional | `init` / `shutdown` |
| `nexus.resource.subcontainer` | optional | имя subcontainer при shutdown/init failure |
| `nexus.observability.phase` | optional | `retention-sweep`, `ledger-build`, `ledger-append`, `pointer-publish` |

### Что останется на следующие зоны

- `plan-written`, `plan-build-failed`, `apply-failed`, `api-check-completed` — это уже зона
  command-specific delivery lifecycle, не общий runtime orchestration.
- `target-write-*` — зона target/apply.
- `cache-refresh-*` — зона cache.
- `vault-init-*`, `admin-gate-*` — зона vault management.

---

## 🧱 Зона 2: Command-specific delivery lifecycle

Вторая рабочая зона taxonomy — lifecycle **конкретных CLI-сценариев доставки**, которые уже
выходят за рамки общего runtime orchestration, но ещё не являются глубокой телеметрией
внутренних подсистем. Это слой между `orchestrator` и `usecase/stage subsystem` taxonomy.

Сюда относятся:

- `import plan`
- `import apply`
- `check-api`
- debug-команды `mapping`, `normalize`, `enrich`, `match`, `resolve`

Эта зона отвечает на вопрос: **какой пользовательский сценарий выполнялся и чем он закончился**.
Она не должна описывать внутренние cache/dictionary/target действия построчно: такие события
живут в последующих subsystem-зонах.

### Принципы именно для этой зоны

- Runtime-события (`command-started`, `report-written`, `resource-init-failed`) не дублируются
  здесь. Зона 2 описывает только специфический outcome конкретной команды.
- Различия между командами выражаются прежде всего через `service.type`, а не через искусственное
  размножение почти одинаковых action для каждого шага одной и той же команды.
- Capability-команды (`cache refresh`, `cache clear`, `vault-management rotate`) допустимо
  фиксировать здесь как command lifecycle. При этом operational telemetry тех же capability
  (`cache lookup`, `secret read`, `provider fallback`) должна жить в отдельных subsystem-зонах.
- Если событие уже относится к конкретной pipeline stage или к cache/target/vault subsystem,
  оно не должно оставаться в command-zone только потому, что было залогировано из delivery слоя.
- Для dataset-aware команд canonical business context передаётся через `event.dataset`; для
  dataset-agnostic команд поле может отсутствовать.

### Canonical taxonomy для зоны

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `plan-written` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `service.type` | `event.dataset`, `file.path`, `nexus.subsystem=report` or `nexus.subsystem=core` | plan command persisted resulting artifact |
| `plan-build-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `error.*` | `event.dataset`, `nexus.stage.name`, `nexus.subsystem=core` | import plan command failed semantically |
| `apply-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `error.*` | `event.dataset`, `nexus.stage.name`, `nexus.subsystem=core` | import apply command failed semantically |
| `identity-init-failed` | DEBUG decision | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `error.*` | `event.dataset`, `nexus.subsystem=identity` | apply-specific identity bootstrap failed |
| `api-check-completed` | INFO milestone | `info`/`error` | `success` or `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type` | `nexus.subsystem=target`, `url.full` or target endpoint metadata | check-api command completed |
| `debug-stage-completed` | INFO milestone | `info`/`error` | `success` or `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `nexus.stage.name` | `event.dataset`, `nexus.stage.rows_total` or `nexus.stage.items_count`, `event.duration` | debug stage command completed with stage artifact/result |

### Нормализация и анти-дублирование

- Не вводить отдельные action вида `mapping-command-completed`, `normalize-command-completed`,
  `enrich-command-completed`, если различие уже выражается через `nexus.stage.name` и `service.type`.
- Не смешивать `plan-written` с runtime `report-written` / `log-written`. Первое — outcome
  command use case, вторые — observability finalization.
- Не поднимать внутрь command-zone subsystem-события вроде `cache-refresh-started`,
  `target-write-failed`, `dictionary-lookup`; даже если их инициировала конкретная команда.
- Если debug-команда завершилась на границе stage и не создаёт отдельной бизнес-семантики,
  допустим один обобщённый action `debug-stage-completed` с обязательным `nexus.stage.name`.

### Минимальный field profile для зоны

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | всегда из canonical словаря зоны |
| `event.outcome` | required | команда или command-specific subflow должны иметь явный outcome |
| `trace.id` | required | основной correlation key одного запуска |
| `service.type` | required | `planner`, `applier`, `topology`, `normalizer`, `matcher`, … |
| `event.dataset` | optional but expected for dataset-aware commands | отсутствует у dataset-agnostic команд |
| `nexus.stage.name` | required only for stage-bound debug commands and stage-aware failures | не нужен для `check-api` |
| `labels.pipeline_run_id` | optional | только если нужно связать несколько command runs/artifacts |
| `error.type`, `error.message` | required on failure events | stack trace — по общим правилам уровня |
| `file.path` | optional | артефакт команды (`plan.json`, debug output, etc.) |
| `event.duration` | recommended on completion | особенно для debug/stage commands и API check |
| `nexus.subsystem` | recommended | `core`, `identity`, `target`, `report` |

### Что останется на следующие зоны

- `stage-started`, `stage-completed`, `stage-failed` — отдельная зона pipeline stage lifecycle.
- `cache-refresh-*`, `cache-status-*`, `cache-open-failed` — зона cache.
- `apply-item`, `apply-completed`, `target-write-*` — зона target/apply execution.
- `dictionary-lookup`, `lookup-hit/miss`, candidate telemetry — зона enrich/dictionary.

---

## 🧱 Зона 3: Pipeline stage lifecycle

Третья рабочая зона taxonomy — общий lifecycle pipeline stage вне зависимости от конкретной
подсистемы. В текущей реализации это stages, которые проходят через
`PipelineOrchestrator` и имеют `StageContract.stage_name`: `map`, `normalize`, `enrich`,
`match`, `resolve_context`, `resolve` (и дополнительные stage adapters вроде
`source_topology_filter`, если они включены в pipeline). Это **универсальный stage-level каркас**,
на который потом навешиваются subsystem-специфичные record/rule/lookup события.

Эта зона отвечает на вопрос: **когда стадия началась, как завершилась, сколько длилась и какой
объём работы выполнила**. Она не должна описывать внутреннюю механику правил, lookup-ов,
candidate filtering или post-row decisions.

### Принципы именно для этой зоны

- Все pipeline stages должны иметь один и тот же lifecycle vocabulary, независимо от реализации.
- Stage lifecycle описывает только milestone-уровень стадии: start, completion, failure.
- Внутренние record/rule/lookup события не подменяют stage events и не заменяют их.
- `nexus.stage.name` здесь обязателен: без него stage lifecycle теряет смысл как общая execution-axis.
- Stage zone допустима и для full pipeline run, и для debug-команд, которые останавливаются на
  конкретной стадии.
- `extract` сейчас является source/adapter перед `PipelineOrchestrator`, а не stage с
  `stage_name`; для него нужна отдельная input/source taxonomy или отдельное wiring-решение.
- `plan` и `apply` не являются transform stage lifecycle в текущей модели: `plan` относится к
  PlanBuilder/command zone, `apply` — к target/apply subsystem.

### Сверка с текущей моделью кода

- `PipelineHooks.on_stage_start(stage_name)` даёт только имя стадии.
- `PipelineHooks.on_stage_complete(stage_name, duration_ms, stats)` сейчас отдаёт duration в
  миллисекундах и `stats={"items": N}` — количество элементов, вышедших из stage stream.
- `PipelineHooks.on_stage_error(stage_name, exc, duration_ms)` отдаёт stage name, exception и
  duration в миллисекундах.
- `StageResultReporter` даёт row-level counters только там, где use case прогоняет результаты
  через reporter: `rows_total`, stage-specific ok label (`mapped_ok`, `normalized_ok`,
  `enriched_ok`, `matched_ok`, `resolved_ok`), stage-specific failed label
  (`mapping_failed`, `normalize_failed`, `enrich_failed`, `match_failed`, `resolve_failed`),
  `warnings_rows`, `vault_candidates_rows`, `vault_candidates_fields_total`.
- `ReportSummary.by_stage` сейчас агрегирует только diagnostic counters:
  `errors_total` и `warnings_total` по `DiagnosticStage`, а не полные stage throughput counters.
- `TransformResult` содержит устойчивый row context: `record`, `row`, `row_ref`, `match_key`,
  `meta`, `secret_candidates`, `errors`, `warnings`. В нём нет встроенных duration/rule counters.

### Canonical taxonomy для зоны

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `stage-started` | INFO milestone | `info` | — | `event.action`, `trace.id`, `service.type`, `nexus.stage.name` | `event.dataset`, `nexus.subsystem` | `PipelineHooks.on_stage_start` |
| `stage-completed` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `nexus.stage.name`, `event.duration` | `event.dataset`, `nexus.stage.items_count`, reporter-derived counters when available, `nexus.subsystem` | `PipelineHooks.on_stage_complete` or reporter finalization |
| `stage-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `nexus.stage.name`, `error.*` | `event.dataset`, `event.duration`, `nexus.stage.items_count`, `nexus.subsystem` | `PipelineHooks.on_stage_error` or stage-level fatal failure |

### Нормализация и анти-дублирование

- Не плодить отдельные stage actions по имени стадии (`enrich-started`, `match-completed`,
  `resolve-failed`), если различие уже выражается через `nexus.stage.name`.
- Не заменять `stage-completed` на subsystem summary-события. Даже если `enrich` имеет свой
  собственный summary, общий lifecycle стадии должен остаться отдельным.
- Не тащить в stage zone rule-level контекст (`field`, `rule`, `lookup_key`, `candidate_count`).
  Эти поля принадлежат subsystem/event-detail зонам.
- Если debug-команда завершилась на конкретной стадии, она может эмитить и command-level event,
  и `stage-completed`: это разные observability perspectives, не дубликаты.

### Минимальный field profile для зоны

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | `stage-started`, `stage-completed`, `stage-failed` |
| `event.outcome` | required on completion/failure | `success` / `failure` |
| `trace.id` | required | основной correlation key запуска |
| `service.type` | required | кто исполняет стадию в текущем flow |
| `nexus.stage.name` | required | canonical execution stage axis |
| `event.dataset` | expected for dataset-aware stages | может отсутствовать у dataset-agnostic flows |
| `event.duration` | required on completion, recommended on failure | длительность стадии в наносекундах; текущий hook даёт `duration_ms`, перед emission нужна конвертация |
| `nexus.stage.items_count` | recommended on completion/failure when hook stats exist | текущее `stats["items"]`: сколько элементов вышло из stage stream |
| `nexus.stage.rows_total` | optional, reporter-derived | доступно из `StageResultReporter.snapshot()` / `publish_context()` |
| `nexus.stage.ok_rows` | optional, reporter-derived | canonical generic counter; в report context дополнительно есть stage-specific ok label |
| `nexus.stage.failed_rows` | optional, reporter-derived | canonical generic counter; в report context дополнительно есть stage-specific failed label |
| `nexus.stage.warnings_rows` | optional, reporter-derived | число rows с warnings по reporter policy |
| `nexus.stage.vault_candidates_rows` | optional, reporter-derived | актуально для stage/report flows, где reporter видит secret fields |
| `nexus.stage.vault_candidates_fields_total` | optional, reporter-derived | суммарное число secret candidate fields |
| `nexus.subsystem` | recommended | обычно совпадает с dominant subsystem стадии |
| `error.type`, `error.message` | required on failure | по общим ECS/error правилам |

### Detail policy для зоны

- `INFO` — всегда: stage lifecycle должен быть полностью восстанавливаем по INFO-потоку.
- `DEBUG` — допустим только для дополнительных stage-level counters/decisions, если они не
  являются row/rule деталями.
- `TRACE` — обычно не нужен на чистом stage lifecycle уровне; TRACE уходит в subsystem
  execution events внутри стадии.

### Что останется на следующие зоны

- `record-*` и `rule-*` enrich events — зона enrich subsystem.
- `lookup-*`, `candidate-*`, `provider-*` telemetry — зоны enrich/cache/vault/dictionary.
- `match-decision-*` и identity-resolution telemetry — зона match subsystem.
- `apply-item` и target request lifecycle — зона target/apply subsystem.

---

## 📖 Словарь `event.action`

Канонический список — `EventAction` (StrEnum) в `ecs.py`. Значения — `verb-noun`, kebab-case. Описания:

| Действие | Уровень | Контекст |
|---|---|---|
| `run-started` | INFO | Старт прогуна команды/пайплайна |
| `run-completed` | INFO | Завершение прогона с `event.outcome` |
| `stage-started` | INFO | Старт стадии пайплайна |
| `stage-completed` | INFO | Завершение стадии с `event.outcome`+`event.duration` |
| `stage-failed` | ERROR | Стадия упала с необработанным исключением |
| `spec-loaded` | DEBUG | Загружен один spec-файл |
| `spec-registry-built` | INFO | Реестр спеков собран |
| `spec-validation-failed` | ERROR | Ошибка валидации spec |
| `cache-hit` / `cache-miss` | DEBUG | Результат кэш-лукапа |
| `cache-refreshed` / `cache-cleared` | INFO | Обновление/очистка кэша |
| `cache-drift-detected` | WARNING | Несовпадение content-hash кэша |
| `target-write-started` / `target-write-completed` | INFO | Запись в целевую систему (apply) |
| `target-write-failed` | ERROR | Запись в цель провалилась после retry |
| `retry-attempt` | WARNING | Транзиентная ошибка, повтор |
| `record-skipped` | WARNING | Запись отброшена (с причиной) |
| `secret-read` / `secret-written` | INFO | Доступ к vault (без значений) |
| `config-loaded` | INFO | `AppConfig` валидирован и загружен |
| `container-initialised` | INFO | DI-контейнер собран |

> Список выше — **целевой lifecycle-словарь**. Фактический `EventAction` (StrEnum) строится из
> [карты ниже](#-карта-call-site--eventaction-по-всему-коду), выведенной из реального кода.

---

## 📋 Карта call-site → event.action (по всему коду)

Выведено из всех 92 логирующих call-sites (`pytest`/README исключены). Это источник, из которого
наполняется `EventAction` в Фазе 2. **Курсивный `message`** — сейчас это event-код; по правилу Темы 3
он станет человекочитаемым, а код переедет в `event.action`. `outcome`: `—` = не завершающее событие.

### Run / orchestrator lifecycle (`component` = команда)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| orchestrator.py:403,743 | info | Command started | `run-started` | — |
| orchestrator.py:539,831 | error | Command failed | `run-failed` | failure |
| orchestrator.py:468,784 | error | Settings error | `config-load-failed` | failure |
| orchestrator.py:494,802 | error | DSL load error | `spec-load-failed` | failure |
| orchestrator.py:514,814 | error | Runtime validation error | `runtime-validation-failed` | failure |
| orchestrator.py:857 | info | Log written | `log-written` | success |
| orchestrator.py:1056 | info | Report written | `report-written` | success |
| orchestrator.py:1058 | error | Report finalization failed | `report-finalize-failed` | failure |
| orchestrator.py:929,950 | error | Container *init failed | `container-init-failed` | failure |
| orchestrator.py:940 | error | Vault startup error | `vault-startup-failed` | failure |
| orchestrator.py:983 | error | Container shutdown failed | `container-shutdown-failed` | failure |
| orchestrator.py:992 | error | Container shutdown completed with errors | `container-shutdown-completed` | failure |

### Observability best-effort (`component` = observability/команда)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| orchestrator.py:252 | warning | Observability sweep failed | `retention-sweep-failed` | failure |
| orchestrator.py:1133,1182 | warning | Ledger record assembly failed | `ledger-record-failed` | failure |
| orchestrator.py:1206 | warning | Ledger append failed | `ledger-append-failed` | failure |
| orchestrator.py:1247,1282 | warning | Latest pointer update failed | `pointer-publish-failed` | failure |
| maintenance_prune.py:98 | info | Manual prune completed | `retention-prune-completed` | success |
| maintenance_prune.py:106 | error | Manual prune failed | `retention-prune-failed` | failure |
| obs_artifacts.py:87 | info | Displayed latest artifact | `artifact-view` | success |
| obs_artifacts.py:96 | error | Observability latest failed | `artifact-view` | failure |
| obs_artifacts.py:147 | info | Displayed artifact tail | `artifact-tail` | success |
| obs_artifacts.py:157 | error | Observability tail failed | `artifact-tail` | failure |

### Commands: plan / apply / api (`component` = planner/applier/topology)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| import_plan.py:223 | info | Plan written | `plan-written` | success |
| import_plan.py:240 | error | Import plan failed | `plan-build-failed` | failure |
| import_apply.py:110 | error | Import apply failed | `apply-failed` | failure |
| import_apply.py:180 | error | Failed to init identity index | `identity-init-failed` | failure |
| check_api.py:43 | info | API check succeeded | `api-check-completed` | success |
| check_api.py:61 | error | API check failed | `api-check-completed` | failure |
| cache_refresh.py:126 | error | Cache refresh failed | `cache-refresh-completed` | failure |
| common.py:29,45 | error | Failed to open cache DB | `cache-open-failed` | failure |
| common.py:60 | error | Vault startup error | `vault-startup-failed` | failure |

### Apply per-item (`component` = applier; `delivery/telemetry/apply_logging_sink.py`)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| :30 | debug | Apply item succeeded | `apply-item` | success |
| :39 | warning | Apply item warning | `apply-item` | unknown |
| :49 | error | Apply item failed | `apply-item` | failure |
| :64 | info | Apply summary | `apply-completed` | success |

### Cache usecases (`component` = cache)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| cache_refresh_service.py:87 | info | Cache refresh started | `cache-refresh-started` | — |
| cache_refresh_service.py:154 | debug | Target page fetched | `cache-page-fetched` | success |
| cache_refresh_service.py:229 | error | Failed to upsert cache item | `cache-upsert-failed` | failure |
| cache_refresh_service.py:298 | error | Cache refresh failed | `cache-refresh-completed` | failure |
| cache_refresh_service.py:338 | info | Cache refresh completed | `cache-refresh-completed` | success |
| cache_command_service.py:94 | error | Cache status failed | `cache-status-failed` | failure |
| cache_command_service.py:120 | info | Cache clear completed | `cache-clear-completed` | success |
| cache_command_service.py:134 | error | Cache clear failed | `cache-clear-failed` | failure |

### Vault management (`component` = vault; messages — коды → станут человеческими)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| management/vault/usecase.py:85 | info | *vault_mgmt_init* (op=start) | `vault-init-started` | — |
| management/vault/usecase.py:118 | info | *vault_mgmt_init* (op=success) | `vault-init-completed` | success |
| management/vault/usecase.py:169 | info | *vault_mgmt_rotate* (op=start) | `vault-rotate-started` | — |
| management/vault/usecase.py:198 | info | *vault_mgmt_rotate* (op=success) | `vault-rotate-completed` | success |
| management/vault/usecase.py:222 | info | *vault_mgmt_rewrap* | `vault-rewrap-started` | — |

### Vault admin gate (`infra/secrets/admin_password_gate.py`; `component` = vault)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| :124 | info | *vault_admin_password_gate_skipped* | `admin-gate-skipped` | — |
| :140 | info | *vault_admin_password_gate_passed* | `admin-gate-passed` | success |
| :152–402 (14×) | warn/error | *vault_admin_password_gate_failed* | `admin-gate-failed` | failure |

### Dictionary (`component` = enricher, `scope` = dictionary; `infra/dictionaries/telemetry.py`)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| :133 | debug | *lookup_hit* / *lookup_miss* (динам.) | `dictionary-lookup` | success (hit/miss → `labels`) |
| :186 | warning | *source_empty* | `dictionary-source-empty` | unknown |
| :216 | warning | *lookup_error* | `dictionary-lookup` | failure |
| record_runtime_initialized | info | (runtime init) | `dictionary-initialized` | success |

### Target driver (`component` = applier; `infra/target/core/engines/safe_logging.py`)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| :87 | warning | target request failed | `target-request-failed` | failure |
| :102 | debug | запланирован повтор target-операции | `retry-attempt` | — |

### Прочие (domain/usecases)
| Call-site | Lvl | message сейчас | event.action | outcome |
|---|---|---|---|---|
| resolve_core.py:200 | warning | merge_policy tried to overwrite… (`%s`-стиль!) | `merge-conflict` | unknown |
| resolve_usecase.py:83 | warning | *pending_codec_skipped_invalid* | `pending-decode-skipped` | unknown |
| infra/cache/dsl_adapter.py:129 | warning | cache sync value expr issue (`%s`-стиль!) | `cache-sync-issue` | unknown |

### Форвардеры логов (динамический уровень — `event.action` от вызывающего, не фикс.)
| Call-site | Назначение | Примечание |
|---|---|---|
| infra/logging/topology.py:47–55 | `StructlogTopologyEventSink._dispatch_log` | топология эмитит свой `event`/`level`; action — у вызывающего |
| delivery/cli/stream_capture.py:120–128 | перехват stdout/stderr | `event.action`=`captured-stream`, `event.kind`=`event` |

> Найдено попутно (вне ECS-скоупа, в worknote): `resolve_core.py:200` и `dsl_adapter.py:129` используют
> **stdlib `%s`-форматирование** вместо structlog kwargs — их надо привести к structlog при наполнении.

---

## 🔖 `event.outcome` и `event.kind`

- **`event.outcome`** (`EventOutcome`): `success` | `failure` | `unknown`. Ставится на событиях
  завершения (`*-completed`, `run-completed`, любые `*-failed` → `failure`).
- **`event.kind`** (`EventKind`): `event` (default) | `metric` (числовые замеры — длительности, счётчики
  как самостоятельное событие) | `state` (снимок состояния). Если не указан — `event`.

---

## 🛠️ Как пополнять

**Добавить ECS-поле:**
1. Добавить строку в таблицу маппинга в `ecs.py` (внутренний ключ → ECS-таргет) либо осознанно оставить
   в `labels.*`.
2. Добавить строку в [Каталог ECS-полей](#️-каталог-ecs-полей) этого документа.
3. Обновить вендоренный срез ECS-полей в тесте, если поле новое для схемы.

**Добавить `event.action`:**
1. Добавить член в `EventAction` (StrEnum) в `ecs.py`.
2. Добавить строку в [Словарь `event.action`](#-словарь-eventaction) с уровнем и контекстом.
3. Использовать на call-site: `logger.info("…", action=EventAction.MY_ACTION, …)`.

**Нельзя:** изобретать корневые не-ECS ключи на call-site — всё неучтённое обязано уходить в `labels.*`
(контрактный тест «нет неизвестных корневых ключей» это ловит).

---

## 🔗 Связанные документы

- [observability-logging.md](./observability-logging.md) — runtime, процессоры, redaction surface, sinks
- [OBSERVABILITY-DEC-003](../../../adr/observability/OBSERVABILITY-DEC-003-ecs-renderer-and-field-mapping.md) — решение, маппинг, поддержание совместимости
- [OBSERVABILITY-PROBLEM-003](../../../adr/observability/OBSERVABILITY-PROBLEM-003-non-ecs-log-shape.md) — проблема (не-ECS форма)
- `connector/infra/logging/ecs.py` — машинно-авторитетный источник (маппинг + enum'ы)
- [ECS Field Reference](https://www.elastic.co/docs/reference/ecs/ecs-field-reference) — внешний канон ECS
