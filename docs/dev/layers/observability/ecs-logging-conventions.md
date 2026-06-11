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
- [🧱 Зона 4: Record Context](#-зона-4-record-context)
- [🧱 Зона 5: Enrich Subsystem](#-зона-5-enrich-subsystem)
- [🧱 Зона 6: State Stores / Provider Subsystems](#-зона-6-state-stores--provider-subsystems)
- [🧱 Зона 7: DSL Artifact Lifecycle](#-зона-7-dsl-artifact-lifecycle)
- [🧱 Зона 8: Match Decision Service](#-зона-8-match-decision-service)
- [🧱 Зона 9: Resolve / Plan Decision & Artifact Lifecycle](#-зона-9-resolve--plan-decision--artifact-lifecycle)
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
| `nexus.record.id` | record-level events | Opaque row id из `RowRef.row_id` / `RecordRef.row_id`; не обязан совпадать с business identity |
| `nexus.record.line_no` | record-level events from line-based source | Номер строки исходного файла, если источник поддерживает line number |
| `nexus.record.ordinal` | record-level stream/batch events | Порядковый номер записи внутри текущего stream/batch, если отличается от `line_no` |
| `nexus.record.identity.primary` | record-level identity-aware events | Имя primary identity field, например `employee_id`, `login`, `external_id` |
| `nexus.record.identity.value_fingerprint` | record-level identity-aware events | Safe fingerprint identity value; raw identity value не логируется |
| `nexus.record.source.kind` | source/record provenance events | Тип origin: `csv`, `plan`, `pending`, `api`, ... |
| `nexus.record.source.path` | source lifecycle / sparse record diagnostics | Относительный путь источника; не эмитить на каждую запись без необходимости |
| `nexus.enrich.operation.name` | enrich record/rule events | Имя compiled enrich operation / DSL rule (`EnrichmentOperation.name`) |
| `nexus.enrich.operation.type` | enrich rule events | `COMPUTE`, `LOOKUP`, `GENERATE`, `MEMBERSHIP`, ... |
| `nexus.enrich.operation.outcome` | enrich rule/record events | `APPLIED`, `SKIPPED`, `WARNED`, `FAILED`, `NEEDS_RESOLVE` |
| `nexus.enrich.field.name` | enrich rule events | Target field / mutated field name; secret values не логируются |
| `nexus.enrich.decision` | enrich rule events | Решение применения: `applied`, `policy_skip`, `conflict_skipped`, ... |
| `nexus.enrich.source` | enrich rule events | Источник выбранного candidate: `computed`, `generated`, provider name |
| `nexus.enrich.operations_total` | enrich record summary | Количество enrich operations, реально учтённых для записи |
| `nexus.enrich.updated_fields` | enrich record summary | Количество полей, обновлённых enrich operation events |
| `nexus.enrich.resolve_requests_count` | enrich record summary | Количество resolve hints, созданных из неоднозначностей |
| `nexus.enrich.secret_fields_count` | enrich record summary | Количество secret fields, записанных в vault и очищенных из row |
| `nexus.lookup.provider.name` | lookup events | Runtime provider: `cache.by_field`, `cache.exists_by_field`, `dictionary.by_key`, ... |
| `nexus.lookup.operation` | lookup events | `lookup`, `exists`, `canonicalize`, provider-specific operation family |
| `nexus.lookup.key_fingerprint` | lookup events | Безопасный fingerprint lookup key; raw key не логируется |
| `nexus.lookup.result_count` | lookup completion | Количество найденных candidate rows |
| `nexus.lookup.hit` | lookup completion | Boolean hit/miss для lookup/exists |
| `nexus.cache.dataset` | cache provider/admin events | Cache dataset/snapshot owner: `employees`, `organizations`, ... |
| `nexus.cache.table` | cache schema/storage diagnostics | Logical/physical cache table name, если нужно диагностировать schema/SQL |
| `nexus.cache.role` | cache provider/admin events | Роль использования: `admin`, `refresh_sync`, `enrich_lookup`, `match_lookup`, `topology_read` |
| `nexus.cache.operation` | cache provider/admin events | `refresh`, `clear`, `status`, `rebuild`, `upsert`, `count`, `read_all`, `find`, `find_one` |
| `nexus.cache.refresh.scope` | cache refresh events | `dataset`, `all`, `with_dependencies` |
| `nexus.cache.refresh.pages` | cache refresh completion | Количество target pages, обработанных при refresh |
| `nexus.cache.refresh.items` | cache refresh completion | Количество source items, обработанных при refresh |
| `nexus.cache.include_deleted` | cache refresh/lookup events | Boolean include-deleted policy |
| `nexus.cache.rows.inserted` | cache refresh/upsert summary | Количество inserted snapshot rows |
| `nexus.cache.rows.updated` | cache refresh/upsert summary | Количество updated snapshot rows |
| `nexus.cache.rows.skipped` | cache refresh/upsert summary | Количество skipped source items |
| `nexus.cache.rows.failed` | cache refresh/upsert summary | Количество failed source items |
| `nexus.cache.rows.total` | cache status/refresh summary | Итоговое количество rows в cache dataset/table |
| `nexus.cache.drift.detected` | cache drift events | Boolean drift result |
| `nexus.cache.drift.reason` | cache drift events | Причина drift: `schema_version_mismatch`, `hash_mismatch`, ... |
| `nexus.cache.schema_hash.expected` | cache drift events | Ожидаемый schema/content hash, если не чувствителен |
| `nexus.cache.schema_hash.actual` | cache drift events | Фактический schema/content hash, если не чувствителен |
| `nexus.cache.rebuild.trigger` | cache rebuild events | `manual`, `drift_policy`, `clear`, ... |
| `nexus.identity.key_fingerprint` | identity lookup/upsert events | Safe fingerprint identity key; raw identity key не логируется |
| `nexus.identity.resolved_id_fingerprint` | identity resolved-id events | Safe fingerprint target/resolved id, если id чувствителен или внешний |
| `nexus.identity.candidates_count` | identity lookup completion | Количество resolved ids/candidates в identity index |
| `nexus.pending.id` | pending lifecycle events | Внутренний pending id; можно логировать, если он не раскрывает payload |
| `nexus.pending.lookup_key_fingerprint` | pending lifecycle events | Safe fingerprint lookup key unresolved link |
| `nexus.pending.status` | pending lifecycle events | `pending`, `resolved`, `expired`, `conflict` |
| `nexus.pending.attempts` | pending lifecycle events | Количество попыток разрешения pending link |
| `nexus.pending.ttl_seconds` | pending expiry events | TTL pending link, если применимо |
| `nexus.storage.backend` | storage operational events | Backend implementation: `sqlite`, `jsonl`, ... |
| `nexus.storage.database` | storage operational events | Logical DB/component: `cache`, `identity`, `vault`, `ledger`; не полный путь |
| `nexus.storage.operation` | storage operational events | `open`, `schema-init`, `transaction`, `commit`, `rollback`, `vacuum`, ... |
| `nexus.dsl.spec.kind` | DSL artifact lifecycle events | `registry`, `dataset`, `source`, `mapping`, `normalize`, `enrich`, `match`, `resolve`, `sink`, `cache`, `dictionary`, `target`, ... |
| `nexus.dsl.spec.name` | DSL artifact lifecycle events | Имя spec/rule/dataset, если оно есть в артефакте |
| `nexus.dsl.spec.path` | DSL load/parse/validate/compile events | Относительный путь YAML/spec artifact; absolute path только для локального debug |
| `nexus.dsl.phase` | DSL lifecycle events | `discover`, `load`, `parse`, `validate`, `compile`, `registry-build`, `default-resolve` |
| `nexus.dsl.yaml.path` | DSL validation/parse errors | YAML key path, например `datasets.employees.report` |
| `nexus.dsl.rule.name` | DSL rule validation/compile events | Имя rule внутри stage spec |
| `nexus.dsl.operation.name` | DSL operation validation/compile/runtime context | Имя DSL operation в operation chain; runtime execution errors остаются stage events |
| `nexus.dsl.error.count` | DSL validation/registry summary | Количество collected DSL errors |
| `nexus.dsl.spec.count` | DSL registry/compile summary | Количество specs/artifacts processed |
| `nexus.match.status` | match decision events | `matched`, `not_found`, `ambiguous`, `conflict_source` |
| `nexus.match.reason_code` | match decision events | `identity_exact`, `identity_not_found`, `fuzzy_accept`, `fuzzy_tie`, `topology_ambiguous`, ... |
| `nexus.match.mode` | match decision/fuzzy events | `exact`, `fuzzy`, topology match mode when selected via topology |
| `nexus.match.score` | fuzzy/topology decision events | Numeric score of selected/best candidate, if available |
| `nexus.match.identity.rule.name` | identity evaluation events | Compiled `IdentityRule.name` from match DSL |
| `nexus.match.identity.primary` | identity evaluation events | Identity primary field name only; no raw value |
| `nexus.match.identity.value_fingerprint` | identity evaluation/events | Safe fingerprint of identity primary value; raw identity value is forbidden |
| `nexus.match.candidates.count` | candidate lookup/ranking summary | Количество candidates considered/found/ranked |
| `nexus.match.candidates.returned` | fuzzy decision summary | Количество top candidates included in decision |
| `nexus.match.selected.target_id_fingerprint` | selected candidate events | Safe fingerprint of selected target id; raw target id is avoided |
| `nexus.match.topology.applied` | topology refinement events | Boolean, whether topology refinement was invoked/applied |
| `nexus.match.topology.mode` | topology refinement events | `exact_canonical_path`, `exact_leaf_parent_chain`, `ambiguous`, `no_match`, ... |
| `nexus.match.topology.reason` | topology refinement events | Topology result reason without raw evidence payload |
| `nexus.match.source_links.count` | match completion events | Количество source link hints built for resolve |
| `nexus.match.fingerprint.fields_count` | match completion events | Количество fields participating in desired-state fingerprint |
| `nexus.match.drop.reason` | source dedup/drop events | `duplicate_source`, `conflict_source` |
| `nexus.match.dedup.outcome` | source dedup events | `first`, `duplicate`, `conflict` |
| `nexus.match.include_deleted` | cache lookup policy context | Boolean include-deleted policy used by matcher |
| `nexus.match.batch.size` | match stage runtime events | Configured micro-batch size |
| `nexus.match.batch.flush_interval_ms` | match stage runtime events | Configured micro-batch flush interval |
| `nexus.resolve.op` | resolve decision / plan item events | `create`, `update`, `skip` |
| `nexus.resolve.status` | resolve decision events | `resolved`, `pending`, `failed`, `skipped` |
| `nexus.resolve.reason_code` | resolve decision events | `match_ambiguous`, `no_changes`, `changes_detected`, `link_pending`, `target_id_missing`, ... |
| `nexus.resolve.changes_count` | resolve decision / update plan events | Количество changed fields; values не логировать |
| `nexus.resolve.changed_fields` | DEBUG/TRACE resolve diagnostics | Имена изменённых полей только если безопасно; no values |
| `nexus.resolve.target_id_fingerprint` | resolve/plan item events | Safe fingerprint target id; raw target id не логировать |
| `nexus.resolve.source_ref.fields_count` | resolve completion events | Количество fields in `ResolvedRow.source_ref`; raw source_ref не логировать |
| `nexus.resolve.secret_fields_count` | resolve/plan item events | Количество secret fields referenced by resolved row / plan item |
| `nexus.resolve.secret_lifecycle.mode` | resolve/plan item events | `persistent`, `ephemeral` |
| `nexus.resolve.secret_lifecycle.delete_on_success` | resolve/plan item events | Boolean cleanup policy |
| `nexus.resolve.secret_lifecycle.ttl_seconds` | resolve/plan item events | Secret lifecycle TTL, если задан |
| `nexus.resolve.link.field` | link resolution events | Link field name |
| `nexus.resolve.link.target_dataset` | link resolution events | Target dataset of resolved link |
| `nexus.resolve.link.lookup_key_fingerprint` | link resolution / pending events | Safe fingerprint lookup key; raw key запрещён |
| `nexus.resolve.link.candidates_count` | link resolution events | Количество candidate ids found |
| `nexus.resolve.link.resolved_id_fingerprint` | link resolution events | Safe fingerprint resolved id |
| `nexus.resolve.link.outcome` | link resolution events | `resolved`, `pending`, `ambiguous`, `missing`, `failed` |
| `nexus.resolve.link.reason` | link resolution events | Safe reason: `no_candidates`, `multiple_candidates`, `topology_missing`, ... |
| `nexus.resolve.link.topology.applied` | topology-backed link events | Boolean topology link resolver applied |
| `nexus.resolve.link.topology.mode` | topology-backed link events | Topology link resolution mode |
| `nexus.resolve.link.topology.reason` | topology-backed link events | Safe topology reason without raw evidence |
| `nexus.resolve.batch_index.keys_count` | resolve_context completion events | Количество lookup keys in batch index |
| `nexus.resolve.batch_index.values_count` | resolve_context completion events | Суммарное количество resolved ids in batch index |
| `nexus.resolve.batch.size` | resolve runtime events | Configured micro-batch size |
| `nexus.resolve.batch.flush_interval_ms` | resolve runtime events | Configured micro-batch flush interval |
| `nexus.pending.replay.rows_count` | pending replay events | Количество pending rows loaded for replay |
| `nexus.pending.decode.skipped_count` | pending decode events | Количество invalid pending rows skipped |
| `nexus.pending.expired.count` | pending expiry events | Количество expired pending links drained/reported |
| `nexus.pending.purged.count` | pending retention events | Количество stale pending rows purged |
| `nexus.pending.retention_days` | pending retention events | Configured pending retention window |
| `nexus.plan.items_count` | plan build/write summary | Количество items in plan artifact |
| `nexus.plan.rows_total` | plan build/write summary | `PlanSummary.rows_total` |
| `nexus.plan.valid_rows` | plan build/write summary | `PlanSummary.valid_rows` |
| `nexus.plan.failed_rows` | plan build/write summary | `PlanSummary.failed_rows` |
| `nexus.plan.skipped_rows` | plan build/write summary | `PlanSummary.skipped` |
| `nexus.plan.planned_create` | plan build/write summary | `PlanSummary.planned_create` |
| `nexus.plan.planned_update` | plan build/write summary | `PlanSummary.planned_update` |
| `nexus.plan.item.op` | plan item events | `create`, `update`; per-item only |
| `nexus.plan.item.changes_count` | plan item events | Количество changes for update item |
| `nexus.plan.item.secret_fields_count` | plan item events | Количество secret field refs in plan item |
| `nexus.plan.item.target_id_fingerprint` | plan item events | Safe fingerprint target id; raw target id не логировать |
| `nexus.*` | по необходимости | Project-specific поля, для которых нет подходящего ECS canonical field |

### `labels.*` (лёгкая корреляция и простые keyword-теги)
| Поле | Когда | Описание |
|---|---|---|
| `labels.pipeline_run_id` | когда нужен более широкий execution-correlation | Correlation id pipeline execution, который может объединять несколько command run / artifact chain и потому не совпадать по смыслу с `trace.id` |
| `labels.<любой kwarg>` | — | **catch-all**: всё неучтённое уходит сюда; record identity предпочитать в `nexus.record.*` |

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
| Source/business record reference | `nexus.record.*` | у ECS нет точного canonical объекта для ETL source-row provenance |
| Persistent identity/pending state | `nexus.identity.*`, `nexus.pending.*` | это resolver/apply state, а не refreshable cache |
| Low-level backend/storage | `nexus.storage.*` | SQLite/JSONL operational layer, отдельно от business subsystem |
| External declarative artifacts | `nexus.dsl.*` | YAML/spec lifecycle до runtime execution |
| Match decision state | `nexus.match.*` | typed decision, fuzzy/topology/dedup context; not cache provider telemetry |
| Resolve decision / plan artifact | `nexus.resolve.*`, `nexus.plan.*` | operation decision and plan summary without payload/diff values |

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
 "event.action":"dsl-load-failed","event.outcome":"failure","error.type":"DslLoadError",
 "error.message":"…","error.code":"DSL_SPEC_INVALID","trace.id":"01J…","service.type":"planner",
 "nexus.subsystem":"dsl","nexus.dsl.phase":"load","ecs.version":"8.11"}
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
| `dsl-load-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=dsl`, `nexus.dsl.phase=load`, `error.code` | `DslLoadError` path |
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
| `file.path` | optional | `report-written`, `log-written`, `plan-written` |
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
| `plan-written` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `file.path` | `event.dataset`, `nexus.subsystem=plan`, `nexus.plan.items_count`, `nexus.plan.planned_create`, `nexus.plan.planned_update` | plan command persisted resulting artifact |
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

- record context для `record-*`, `rule-*`, diagnostics/reporting/apply — зона record context.
- `rule-*` enrich events — зона enrich subsystem.
- `lookup-*`, `candidate-*`, `provider-*` telemetry — зоны enrich/cache/vault/dictionary.
- match decision telemetry — зона match decision service.
- `apply-item` и target request lifecycle — зона target/apply subsystem.

---

## 🧱 Зона 4: Record context

Четвёртая рабочая зона taxonomy — общий контекст записи, который используется всеми
record-level событиями: diagnostics, reporting, enrich, match, resolve, plan/apply item telemetry.
Это не payload записи и не бизнес-сущность target system, а безопасная ссылка на исходную запись
и её путь через pipeline.

В текущей модели кода уже есть две близкие ссылки:

- `RowRef` в domain transform/diagnostics/reporting: `line_no`, `row_id`,
  `identity_primary`, `identity_value`.
- `RecordRef` в planning/apply: `row_id`, `line_no`.

Taxonomy объединяет их в один logging namespace `nexus.record.*`, чтобы apply, diagnostics и
pipeline stages не расходились в плоские `row_id`/`line_no`/`row_ref` labels.

### Принципы именно для этой зоны

- `nexus.record.*` отвечает только на вопрос **"о какой записи идёт речь?"**.
- `nexus.record.*` не содержит source row payload, raw field values, ФИО, email, login, табельный
  номер или secret evidence.
- Raw `RowRef.identity_value` не логируется. Если нужно связать события одной business identity,
  использовать `nexus.record.identity.value_fingerprint`.
- `nexus.record.id` — opaque pipeline/plan id. Он может быть `line:<n>`, UUID, source record id
  или id из plan item, но не должен трактоваться как business identity.
- `nexus.record.source.path` не является per-record обязательным полем. Его достаточно логировать
  на source lifecycle events или на редких диагностиках, где без пути невозможно разобраться.
- Если точной ссылки на запись нет, `nexus.record.*` не эмитится. Не надо подставлять фиктивные
  значения вроде `unknown`, кроме уже существующих domain sentinel values (`row_id="source"`).

### Canonical mapping из текущей модели

| Текущий источник | Logging field | Комментарий |
|---|---|---|
| `RowRef.row_id` | `nexus.record.id` | Основной record correlation key внутри transform/reporting/diagnostics |
| `RowRef.line_no` | `nexus.record.line_no` | Только для line-based источников |
| `RowRef.identity_primary` | `nexus.record.identity.primary` | Имя identity field безопасно логировать |
| `RowRef.identity_value` | `nexus.record.identity.value_fingerprint` | Только fingerprint; raw value запрещён |
| `RecordRef.row_id` | `nexus.record.id` | Apply/plan item использует тот же namespace |
| `RecordRef.line_no` | `nexus.record.line_no` | Apply/plan item сохраняет source line |
| `PlanItem.source_ref` | не маппить целиком | Может содержать source-specific data; нужны явные safe поля при необходимости |

### Минимальный field profile для record-level событий

| Поле | Статус | Примечание |
|---|---|---|
| `trace.id` | required | связывает record event с запуском |
| `event.dataset` | required when dataset-aware | business dataset |
| `nexus.stage.name` | expected inside pipeline stages | stage, где событие произошло |
| `nexus.subsystem` | recommended | subsystem, который принял решение |
| `nexus.record.id` | recommended | основной opaque record id |
| `nexus.record.line_no` | recommended when available | CSV/source line number |
| `nexus.record.identity.primary` | optional | только имя identity field |
| `nexus.record.identity.value_fingerprint` | optional | только safe fingerprint |
| `nexus.record.source.kind` | optional | `csv`, `plan`, `pending`, `api`, ... |
| `nexus.record.source.path` | sparse optional | source lifecycle / редкие diagnostics, не dense per-record stream |

### Detail policy для зоны

- `INFO` — не использовать для per-record context, кроме редких user-facing summary events.
- `DEBUG` — основной уровень для record-level decisions: skipped row, failed row, apply item,
  match decision, resolve decision, enrich record summary.
- `TRACE` — rule/field/provider детализация для конкретной записи; всегда дополняется
  `nexus.record.*`, если `RowRef`/`RecordRef` доступен.
- `WARNING`/`ERROR` — record context обязателен, если ошибка относится к конкретной записи и ссылка
  уже доступна в доменной модели.

### Что не логировать

- Raw `RowRef.identity_value`.
- Полный `row_ref` object без схемы.
- Source row payload, `SourceRecord.values`, `desired_state`, `changes`, full `PlanItem`.
- PII-поля: ФИО, email, login, phone, personnel number, document ids.
- Secret fields, generated passwords, vault key material.
- Raw lookup keys; для lookup использовать `nexus.lookup.key_fingerprint`.

### Связь с соседними зонами

- Enrich использует `nexus.record.*` как общий record context, а детали операции кладёт в
  `nexus.enrich.*`.
- Match использует `nexus.record.*` для source row, а candidate/target identity будет описывать
  отдельными match/cache fields.
- Resolve/plan/apply используют `nexus.record.*` для связи plan item с исходной записью.
- Reporting/diagnostics могут строить `nexus.record.*` из `DiagnosticItem.record_ref` и
  `ReportItem.row_ref`.

---

## 🧱 Зона 5: Enrich subsystem

Пятая рабочая зона taxonomy — внутренняя телеметрия enrich stage: выполнение compiled
operations, применение candidates, создание resolve hints, работа с secret fields и lookup/exists
provider calls. Это **subsystem perspective** внутри `nexus.stage.name=enrich`, а не общий stage
lifecycle.

Enrich сейчас не логирует эти события напрямую. Реальная модель уже есть в domain result:
`OperationReport`, `EnrichEvent`, `ResolveHint`, `EnricherReport`, `TransformResult.meta` и
`secret_candidates`. Внедрение логирования должно идти через порт/адаптер по примеру topology
(`TopologyEventSink` → `StructlogTopologyEventSink`), а не через прямой logger внутри
`EnricherCore`.

### Принципы именно для этой зоны

- `INFO` остаётся на stage/summary уровне. Enrich не должен писать rule/lookup события в INFO.
- `DEBUG` — record decisions и значимые lookup outcomes: miss, ambiguous, provider error,
  slow lookup, sampled hit, exists conflict.
- `TRACE` — rule-by-rule execution: operation start/complete, provider call, candidate count,
  decision reason, per-operation duration.
- Raw `before`, `after`, lookup key values, candidate values, secret values и plaintext evidence
  не логируются. Использовать field names, counts, safe fingerprints, diagnostic codes и redacted
  previews только после явного sanitization.
- `nexus.lookup.*` описывает механизм lookup/exists/canonicalize, а владелец решения задаётся
  через `nexus.stage.name=enrich`, `nexus.subsystem=enrich` и `nexus.enrich.operation.*`.

### Сверка с текущей моделью кода

- `EnricherCore.enrich()` создаёт `EnrichContext(dataset, run_id)`, проходит по
  `self.spec.operations`, получает `OperationReport`, складывает events в
  `meta["enrich_events"]`, resolve hints в `meta["resolve_requests"]` и summary в
  `meta["enrich_summary"]`.
- `EnrichEvent` уже содержит `op`, `field`, `source`, `decision`, `outcome`, но также содержит
  `before`/`after`; эти два поля не являются безопасными для логов в raw виде.
- `EnricherReport` уже даёт per-record summary: `operations_total`, `outcomes`,
  `updated_fields`.
- `EnrichmentOperation` уже даёт stable rule context: `name`, `op_type`, `targets`,
  `required_keys`, `providers`, `merge_policy`, `strictness`, `run_when_errors`.
- `ResolveHint` содержит `field`, `lookup_key`, `reason`, `candidates`, `suggested_policy`;
  в логи можно выводить count/reason, но не raw `lookup_key` и не полный candidates payload.
- `DictionaryTelemetry` уже логирует sampled dictionary lookup hit/miss/error с
  `key_fingerprint`, `result_count`, `limit`, `fields`, `backend`. Эти события относятся к
  dictionary subsystem; enrich-связь появится только если дополнительно передавать operation
  context через enrich telemetry.

### Canonical taxonomy для зоны

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `enrich-record-completed` | DEBUG decision | `debug` | `success`/`failure`/`unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.stage.name` | `nexus.enrich.operations_total`, `nexus.enrich.updated_fields`, `nexus.enrich.resolve_requests_count`, `nexus.enrich.secret_fields_count` | after `EnricherCore.enrich()` result is available |
| `enrich-operation-completed` | TRACE diagnostic | `trace` | `success`/`failure`/`unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.stage.name`, `nexus.enrich.operation.name`, `nexus.enrich.operation.type` | `nexus.enrich.operation.outcome`, `nexus.enrich.field.name`, `nexus.enrich.decision`, `nexus.enrich.source`, `event.duration` | after one `OperationReport` |
| `enrich-operation-skipped` | DEBUG decision | `debug` | `unknown` | `event.action`, `trace.id`, `event.dataset`, `nexus.stage.name`, `nexus.enrich.operation.name` | `nexus.enrich.operation.type`, `nexus.enrich.decision`, `error.code` when diagnostic exists | `run_when_errors` / policy skip path |
| `enrich-resolve-requested` | DEBUG decision | `debug` | `unknown` | `event.action`, `trace.id`, `event.dataset`, `nexus.stage.name`, `nexus.enrich.operation.name` | `nexus.enrich.field.name`, `nexus.enrich.resolve_requests_count`, `nexus.lookup.result_count` | ambiguous candidate path creates `ResolveHint` |
| `enrich-secret-fields-stored` | DEBUG decision | `debug` | `success`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.stage.name` | `nexus.enrich.secret_fields_count`, `error.code` | `_store_secrets()` success/failure boundary |
| `lookup-completed` | DEBUG decision | `debug` | `success`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.lookup.provider.name` | `nexus.stage.name=enrich`, `nexus.enrich.operation.name`, `nexus.lookup.operation`, `nexus.lookup.hit`, `nexus.lookup.result_count`, `nexus.lookup.key_fingerprint`, `event.duration` | provider call wrapper / dictionary telemetry adapter |
| `lookup-started` | TRACE diagnostic | `trace` | — | `event.action`, `trace.id`, `event.dataset`, `nexus.lookup.provider.name` | `nexus.stage.name=enrich`, `nexus.enrich.operation.name`, `nexus.lookup.operation` | immediately before provider call |

`lookup-completed` с `nexus.lookup.hit=false` — это `event.outcome=success`, если provider
корректно вернул пустой результат. `event.outcome=failure` использовать только для provider
exception / timeout / invalid response. Полный поток всех lookup completion допустим на `TRACE`;
на `DEBUG` оставлять miss/error/slow/sampled-hit.

### Минимальный field profile для зоны

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | из canonical словаря зоны |
| `event.outcome` | required on completion/failure | маппится из operation/report result, не из raw exception alone |
| `trace.id` | required | correlation одного запуска |
| `event.dataset` | required | enrich всегда dataset-aware |
| `nexus.stage.name` | required | всегда `enrich` |
| `nexus.subsystem` | required | `enrich`; lookup provider может дополнительно писать `cache`/`dictionary` в своей subsystem-zone |
| `nexus.record.id` | recommended for record/rule events | из общей record context taxonomy |
| `nexus.record.line_no` | recommended when available | из `RowRef.line_no` |
| `nexus.enrich.operation.name` | required for operation/lookup events | `EnrichmentOperation.name` / DSL `rule.name` |
| `nexus.enrich.operation.type` | required for operation events | `COMPUTE`, `LOOKUP`, `GENERATE`, ... |
| `nexus.enrich.operation.outcome` | required for operation completion | `APPLIED`, `SKIPPED`, `WARNED`, `FAILED`, `NEEDS_RESOLVE` |
| `nexus.enrich.field.name` | recommended | target/mutated field name only, no value |
| `nexus.enrich.decision` | recommended | `applied`, `policy_skip`, `conflict_skipped`, ... |
| `nexus.lookup.provider.name` | required for lookup events | `cache.by_field`, `cache.exists_by_field`, `dictionary.by_key`, ... |
| `nexus.lookup.key_fingerprint` | recommended for lookup events | never raw key |
| `nexus.lookup.result_count` | recommended on lookup completion | candidate count / returned rows |
| `event.duration` | recommended for operation/lookup completion | not available today; easy to add around operation/provider call |
| `error.code`, `error.type`, `error.message` | required on failed lookup/operation | values only, no raw input/candidate payload |

### Что уже можно заменить без новой domain-модели

- Per-record summary из `result.meta["enrich_summary"]` → `enrich-record-completed`.
- Existing `meta["enrich_events"]` → source for TRACE `enrich-operation-completed`, после
  redaction/drop of `before` and `after`.
- Existing `meta["resolve_requests"]` → source for DEBUG `enrich-resolve-requested`, только
  counts/reason/field.
- Existing `meta["secret_fields"]` → source for `enrich-secret-fields-stored` count.
- Existing dictionary telemetry → `lookup-completed` for dictionary subsystem, with current
  sampling and safe `key_fingerprint`.

### Что легко добавить при внедрении порта/адаптера

- `EnrichTelemetrySink` Protocol рядом с domain ports, no-op implementation для тестов.
- `StructlogEnrichTelemetrySink` в infra/delivery logging layer по модели topology adapter.
- Per-operation duration вокруг `_execute_operation()`.
- Per-provider duration/result around `_collect_candidates()` provider loop.
- Safe lookup key fingerprint helper for cache lookup, analogous to dictionary telemetry.
- Optional sampling policy for lookup hits, with misses/errors always emitted at DEBUG.

### Что не логировать

- `EnrichEvent.before` / `EnrichEvent.after` raw.
- Raw lookup keys, source field values, candidate values.
- Secret candidate values and generated passwords.
- Full `ResolveHint.lookup_key` and raw `ResolveHint.candidates`.
- Full row payload or DataFrame snapshots.

---

## 🧱 Зона 6: State stores / provider subsystems

Шестая рабочая зона taxonomy фиксирует границы между refreshable cache, identity index,
pending lifecycle и низкоуровневым storage backend. Эти вещи не должны автоматически называться
`cache` только потому, что физически лежат в SQLite или исторически проходят через cache-порт.

### Семантические корзины

| Корзина | Namespace | Что означает | Примеры текущей модели |
|---|---|---|---|
| Refreshable cache snapshot | `nexus.cache.*` | Производные reference/target данные, которые можно refresh/clear/status | `cache.sqlite3`, cache refresh/status/clear, enrich/match lookup по snapshot |
| Identity index | `nexus.identity.*` | Persistent correlation source identity → target/resolved id между прогонами | `identity_index`, `upsert_identity`, `find_candidates`, `mark_resolved_for_source` |
| Pending lifecycle | `nexus.pending.*` | State unresolved links, которые ожидают будущего разрешения | `pending_links`, `add_pending`, `touch_attempt`, `mark_resolved`, `mark_conflict`, expiry |
| Storage backend | `nexus.storage.*` | Технический backend I/O, schema, transaction, commit/rollback | SQLite open/schema-init/transaction errors для cache/identity/vault/ledger |

`nexus.lookup.*` остаётся общим механизмом provider lookup. Владелец смысла задаётся
`nexus.subsystem` и специализированным namespace: `cache`, `identity`, `pending`, `dictionary`,
`vault` и т.д.

### Принципы именно для этой зоны

- Не называть identity/pending события `cache-*`, даже если текущий порт называется
  `ResolveRuntimePort` и расположен рядом с cache roles.
- `cache` — это refreshable/read-through snapshot. `identity` и `pending` — durable runtime state.
- Storage failures (`sqlite locked`, schema init, transaction rollback) логируются как
  `nexus.storage.*` плюс `error.*`; business decision при этом остаётся в `nexus.identity.*` /
  `nexus.pending.*`.
- Raw identity keys, lookup keys, pending payload, desired state, source links и target payload
  не логируются. Использовать fingerprints, counts, status, attempts, diagnostic codes.
- `identity`/`pending` events обычно принадлежат `nexus.subsystem=resolve` или
  `nexus.subsystem=apply`, а не `nexus.subsystem=cache`.

### Cache provider taxonomy

Cache provider покрывает только refreshable snapshot/reference data: cache admin commands,
refresh/rebuild internals и runtime lookup/read operations поверх cache snapshot. Он не покрывает
identity index, pending links, vault secrets или low-level SQLite mechanics.

#### Cache boundaries

- `nexus.subsystem=cache` — command/admin lifecycle: refresh, clear, status, rebuild.
- `nexus.cache.role=refresh_sync` — sync target data → cache snapshot during refresh.
- `nexus.cache.role=enrich_lookup` / `match_lookup` / `topology_read` — runtime consumer role,
  когда cache используется другой подсистемой.
- `nexus.storage.*` использовать только для backend failures/schema/transaction. Успешные cache
  business operations не должны превращаться в storage events.
- `identity_syncer.sync()` внутри refresh не является cache event: это
  `identity-upsert-completed`, даже если вызвано после cache upsert.

#### Canonical cache actions

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `cache-refresh-started` | INFO milestone | `info` | — | `event.action`, `trace.id`, `nexus.subsystem=cache` | `event.dataset`, `nexus.cache.refresh.scope`, `nexus.cache.include_deleted` | before refresh plan execution |
| `cache-refresh-completed` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `event.duration`, `trace.id`, `nexus.subsystem=cache` | `nexus.cache.rows.inserted`, `nexus.cache.rows.updated`, `nexus.cache.rows.skipped`, `nexus.cache.rows.failed`, `nexus.cache.refresh.pages`, `nexus.cache.refresh.items` | after refresh summary |
| `cache-refresh-failed` | ERROR milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem=cache`, `error.*` | `event.dataset`, `nexus.cache.refresh.scope` | refresh exception boundary |
| `cache-refresh-dataset-completed` | DEBUG decision | `debug` | `success`/`failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.cache.dataset` | per-dataset rows/pages/items counters | after one dataset in refresh plan |
| `cache-page-fetched` | DEBUG/TRACE diagnostic | `debug`/`trace` | `success`/`failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.cache.dataset` | `nexus.cache.role=refresh_sync`, page number/count via explicit fields or `labels.*` until promoted | target page boundary during refresh |
| `cache-item-upserted` | TRACE diagnostic | `trace` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.cache.dataset` | `nexus.cache.operation=upsert`, `nexus.cache.rows.inserted=1` or `nexus.cache.rows.updated=1` | per source item, only TRACE |
| `cache-item-upsert-failed` | ERROR/DEBUG decision | `error`/`debug` | `failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.cache.dataset`, `error.*` | safe item key fingerprint if available, no raw item payload | per source item failure |
| `cache-clear-completed` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem=cache` | `event.dataset`, `nexus.cache.rows.total`, cascade flag | cache clear command |
| `cache-clear-failed` | ERROR milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem=cache`, `error.*` | `event.dataset`, cascade flag | cache clear exception |
| `cache-status-completed` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem=cache` | `event.dataset`, `nexus.cache.rows.total`, meta/count fields | cache status command |
| `cache-status-failed` | ERROR milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem=cache`, `error.*` | `event.dataset` | cache status exception |
| `cache-drift-detected` | DEBUG/WARNING decision | `debug`/`warning` | `unknown`/`failure` | `event.action`, `trace.id`, `nexus.subsystem=cache` | `nexus.cache.drift.detected=true`, `nexus.cache.drift.reason`, `nexus.cache.schema_hash.expected`, `nexus.cache.schema_hash.actual` | drift policy evaluation |
| `cache-rebuild-completed` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem=cache` | `event.dataset`, `nexus.cache.rebuild.trigger`, `nexus.cache.rows.total` | rebuild after manual/drift policy |
| `cache-rebuild-failed` | ERROR milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem=cache`, `error.*` | `event.dataset`, `nexus.cache.rebuild.trigger` | rebuild exception |

Provider lookup through cache should normally use the common `lookup-started` /
`lookup-completed` actions rather than `cache-hit` / `cache-miss`:

| Context | Action | Required cache fields | Required lookup fields |
|---|---|---|---|
| Enrich cache lookup | `lookup-completed` | `nexus.cache.role=enrich_lookup`, `nexus.cache.dataset` | `nexus.lookup.provider.name=cache.by_field`, `nexus.lookup.hit`, `nexus.lookup.result_count`, `nexus.lookup.key_fingerprint` |
| Enrich cache exists | `lookup-completed` | `nexus.cache.role=enrich_lookup`, `nexus.cache.dataset` | `nexus.lookup.provider.name=cache.exists_by_field`, `nexus.lookup.hit`, `nexus.lookup.key_fingerprint` |
| Match cache lookup | `lookup-completed` | `nexus.cache.role=match_lookup`, `nexus.cache.dataset` | `nexus.lookup.provider.name=cache.match`, `nexus.lookup.hit`, `nexus.lookup.result_count`, `nexus.lookup.key_fingerprint` |
| Topology cache read | `lookup-completed` | `nexus.cache.role=topology_read`, `nexus.cache.dataset` | `nexus.lookup.provider.name=cache.read_all`, `nexus.lookup.result_count` |

Cache lookup miss is `event.outcome=success` with `nexus.lookup.hit=false` when the provider
correctly returned no rows. `event.outcome=failure` means exception, invalid response, storage
failure, or violated provider contract.

#### Cache field profile

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | cache command action or common `lookup-completed` |
| `event.outcome` | required on completion/failure | `success` for correct empty lookup result |
| `trace.id` | required | correlation запуска |
| `event.dataset` | expected when single dataset is known | business/cache dataset name |
| `nexus.subsystem` | required | `cache` for command/admin; caller subsystem for runtime lookup |
| `nexus.cache.dataset` | required for cache dataset-scoped events | may equal `event.dataset`, but describes cache snapshot owner |
| `nexus.cache.role` | required for runtime provider events | `enrich_lookup`, `match_lookup`, `topology_read`, `refresh_sync` |
| `nexus.cache.operation` | recommended | `refresh`, `clear`, `status`, `rebuild`, `upsert`, `find`, ... |
| `nexus.lookup.*` | required for runtime lookup | common lookup mechanism fields |
| `nexus.cache.rows.*` | recommended for refresh/status/clear/rebuild summaries | aggregate counters only |
| `nexus.cache.drift.*` | required for drift events | no raw payload |
| `nexus.storage.*` | required only for backend failure events | do not use for normal cache decisions |

#### Detail policy для cache

- `INFO` — command/admin lifecycle: refresh started/completed, clear completed, status completed,
  rebuild completed.
- `DEBUG` — per-dataset refresh summary, drift decision, lookup miss/error/slow/sampled-hit.
- `TRACE` — per-page, per-item, per-upsert, every lookup completion.
- `WARNING` — drift/policy condition that changes behavior but run can continue.
- `ERROR` — refresh/clear/status/rebuild/upsert/storage failure.

#### Что уже важно учесть при миграции текущего cache-кода

- `CacheRefreshUseCase.refresh()` already has `page_size`, `max_pages`, `include_deleted`,
  `include_dependencies`, `stats_by_dataset`, `error_stats`, `duration_ms`: these map directly to
  `cache-refresh-*` and `nexus.cache.rows.*` / `nexus.cache.refresh.*`.
- Current `Target page fetched` maps to `cache-page-fetched` only from cache refresh perspective;
  if promoted to target transport taxonomy later, do not duplicate it as a second INFO event.
- Current `Failed to upsert cache item` maps to `cache-item-upsert-failed`; raw `key` should become
  a safe key fingerprint before ECS migration.
- `CacheCommandService.clear()` maps to `cache-clear-completed` / `cache-clear-failed`.
- `CacheCommandService.status()` maps to `cache-status-completed` / `cache-status-failed`.
- Drift policy in `_apply_drift_policy_for_scope()` maps to `cache-drift-detected`; if policy
  triggers rebuild, add `cache-rebuild-*` with `nexus.cache.rebuild.trigger=drift_policy`.

#### Что не логировать

- Raw cache item payload, target API item, mapped cache row.
- Raw cache lookup key / filter values; use `nexus.lookup.key_fingerprint`.
- Full SQL queries or absolute SQLite file paths.
- Identity sync details as cache fields; use `nexus.identity.*`.
- Per-item success at DEBUG in normal runs; use TRACE or aggregate counters.

### Canonical taxonomy для зоны

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `identity-lookup-completed` | DEBUG decision | `debug` | `success`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.subsystem` | `nexus.lookup.provider.name=identity.index`, `nexus.lookup.hit`, `nexus.identity.key_fingerprint`, `nexus.identity.candidates_count`, `event.duration` | identity candidate lookup |
| `identity-upsert-completed` | DEBUG decision | `debug` | `success`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.subsystem` | `nexus.identity.key_fingerprint`, `nexus.identity.resolved_id_fingerprint`, `nexus.record.id` | apply post-write sync / identity index update |
| `identity-source-resolved` | DEBUG decision | `debug` | `success`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.subsystem` | `nexus.record.id`, `nexus.identity.key_fingerprint`, `nexus.identity.resolved_id_fingerprint` | resolver/apply marks source identity resolved |
| `pending-link-created` | DEBUG decision | `debug` | `unknown` | `event.action`, `trace.id`, `event.dataset`, `nexus.stage.name`, `nexus.subsystem` | `nexus.record.id`, `nexus.pending.lookup_key_fingerprint`, `nexus.pending.status=pending`, `nexus.pending.attempts` | resolve creates unresolved link |
| `pending-link-touched` | TRACE diagnostic | `trace` | `unknown` | `event.action`, `trace.id`, `event.dataset`, `nexus.subsystem` | `nexus.pending.id`, `nexus.pending.attempts`, `nexus.pending.status` | retry/attempt counter update |
| `pending-link-resolved` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.subsystem` | `nexus.pending.id`, `nexus.pending.lookup_key_fingerprint`, `nexus.identity.resolved_id_fingerprint` | apply/resolve resolves pending link |
| `pending-link-expired` | DEBUG decision | `debug`/`warning` | `unknown`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.subsystem` | `nexus.pending.id`, `nexus.pending.status=expired`, `nexus.pending.attempts`, `nexus.pending.ttl_seconds` | pending expiry sweep |
| `pending-link-conflicted` | DEBUG decision | `debug`/`warning` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.subsystem` | `nexus.pending.id`, `nexus.pending.status=conflict`, `error.code` | max attempts / conflict policy |
| `storage-operation-failed` | ERROR/WARNING | `warning`/`error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.storage.backend`, `nexus.storage.database`, `nexus.storage.operation`, `error.*` | `event.dataset`, `nexus.subsystem` | SQLite/schema/transaction boundary |

`pending-link-expired` на `warning` использовать только если expiry влияет на outcome текущего
run или требует операторского внимания. Регулярная очистка старых pending links остаётся `debug`.

### Минимальный field profile для identity/pending events

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | из canonical словаря зоны |
| `event.outcome` | required on completion/failure | `success` для корректного miss/empty result, `failure` для exception/policy failure |
| `trace.id` | required | correlation запуска |
| `event.dataset` | required when dataset-aware | identity/pending всегда dataset-scoped в текущей модели |
| `nexus.subsystem` | required | обычно `resolve` или `apply`; не `cache` для identity/pending |
| `nexus.stage.name` | expected inside pipeline stages | `resolve_context` или `resolve`, если событие происходит в stage |
| `nexus.record.id` | recommended when record-scoped | из общей record context taxonomy |
| `nexus.identity.key_fingerprint` | required for identity key events | raw key запрещён |
| `nexus.pending.lookup_key_fingerprint` | required for pending link events | raw lookup key запрещён |
| `nexus.pending.status` | required for pending lifecycle events | `pending`, `resolved`, `expired`, `conflict` |
| `nexus.storage.*` | required for backend failures | только logical backend/db/operation, без absolute paths и payload |

### Что уже важно учесть при миграции текущего кода

- `ResolveRuntimePort` сейчас расположен в `domain/ports/cache/roles.py`, но его методы
  `add_pending`, `list_pending_rows`, `mark_resolved`, `touch_attempt`, `mark_conflict` логировать
  как `pending`/`identity`, а не как `cache`.
- `identity.sqlite3` — это storage backend для identity/pending state. Файл может лежать в
  `var/cache/`, но taxonomy не наследует имя директории.
- `ResolveCore` создаёт pending links при link-resolution miss; это `pending-link-created`, а не
  `cache-miss`.
- `ImportApplyService` после успешной записи синхронизирует identity/pending; это
  `identity-upsert-completed` / `pending-link-resolved`, а не cache refresh.

### Что не логировать

- Raw `identity_key`, raw `lookup_key`, pending payload JSON.
- `desired_state`, `changes`, source link values, target payload.
- Absolute SQLite paths, если достаточно `nexus.storage.database`.
- Raw target id, если он считается внешним идентификатором; использовать
  `nexus.identity.resolved_id_fingerprint`.

## 🧱 Зона 7: DSL artifact lifecycle

Седьмая зона описывает lifecycle внешних декларативных артефактов: discovery, load, parse,
validation, hydration/compile и сборку registry. DSL здесь рассматривается как **input boundary**,
а не как runtime-исполнение стадии.

### Границы зоны

- DSL taxonomy покрывает YAML/spec artifacts из `datasets/registry.yaml`, dataset specs, source
  specs, transform specs, cache specs, dictionary specs и target specs.
- Зона заканчивается там, где из внешнего артефакта получен типизированный runtime/stage объект.
- Runtime-ошибки выполнения операции относятся к taxonomy соответствующей стадии (`map`,
  `normalize`, `enrich`, `match`, `resolve`), но могут нести `nexus.dsl.rule.name` или
  `nexus.dsl.operation.name` как контекст.
- DSL-события не должны описывать network/DB side effects. Если событие говорит про внешний I/O,
  это taxonomy cache/dictionary/target/storage, а не DSL.
- В `nexus.dsl.spec.path` используем относительные пути; raw YAML body не логируем.

### Фазы DSL lifecycle

| Phase | Смысл |
|---|---|
| `discover` | Найден внешний spec artifact или ссылка на него |
| `load` | YAML/spec файл прочитан с диска |
| `parse` | YAML преобразован в intermediate dict/model input |
| `validate` | Pydantic/semantic validation прошла или вернула errors |
| `compile` | Spec преобразован в runtime object: rule, operation, stage config, provider config |
| `registry-build` | Собран общий registry datasets/targets/dictionaries/cache policies |
| `default-resolve` | Применены defaults, implicit links, fallback policy |

### Canonical taxonomy для зоны

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `dsl-registry-loaded` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem` | `nexus.dsl.phase=load`, `nexus.dsl.spec.kind=registry`, `nexus.dsl.spec.path` | registry YAML loaded |
| `dsl-registry-built` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem` | `nexus.dsl.phase=registry-build`, `nexus.dsl.spec.count`, `event.dataset` optional | effective registry ready |
| `dsl-registry-build-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem`, `error.*` | `nexus.dsl.phase=registry-build`, `nexus.dsl.error.count`, `nexus.dsl.spec.path` | registry assembly failed |
| `dsl-spec-discovered` | TRACE diagnostic | `trace` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem` | `nexus.dsl.phase=discover`, `nexus.dsl.spec.kind`, `nexus.dsl.spec.path` | spec discovery/link traversal |
| `dsl-spec-loaded` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem` | `nexus.dsl.phase=load`, `nexus.dsl.spec.kind`, `nexus.dsl.spec.name`, `nexus.dsl.spec.path` | one spec file loaded |
| `dsl-spec-parsed` | TRACE diagnostic | `trace`/`debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem` | `nexus.dsl.phase=parse`, `nexus.dsl.spec.kind`, `nexus.dsl.spec.path` | YAML parse completed |
| `dsl-spec-validated` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem` | `nexus.dsl.phase=validate`, `nexus.dsl.spec.kind`, `nexus.dsl.spec.name`, `nexus.dsl.spec.path` | Pydantic/semantic validation completed |
| `dsl-spec-compiled` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem` | `nexus.dsl.phase=compile`, `nexus.dsl.spec.kind`, `nexus.dsl.spec.name`, `nexus.dsl.rule.name`, `nexus.dsl.operation.name` | compiler produced runtime object |
| `dsl-load-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem`, `error.*` | `nexus.dsl.phase=load`, `nexus.dsl.spec.kind`, `nexus.dsl.spec.path`, `error.code` | file read/YAML parse failure |
| `dsl-validation-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem`, `error.*` | `nexus.dsl.phase=validate`, `nexus.dsl.spec.kind`, `nexus.dsl.spec.path`, `nexus.dsl.yaml.path`, `nexus.dsl.error.count` | structural/semantic validation failure |
| `dsl-compile-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem`, `error.*` | `nexus.dsl.phase=compile`, `nexus.dsl.spec.kind`, `nexus.dsl.rule.name`, `nexus.dsl.operation.name` | valid spec cannot compile to runtime object |

### Минимальный field profile для DSL events

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | из DSL action-словаря |
| `event.outcome` | required on completion/failure | `success`/`failure`; discovery может быть non-terminal |
| `trace.id` | required | correlation запуска |
| `nexus.subsystem` | required | всегда `dsl` для lifecycle spec events |
| `nexus.dsl.phase` | required | одна из phase lifecycle выше |
| `nexus.dsl.spec.kind` | required when spec-scoped | тип артефакта, а не Python class name |
| `nexus.dsl.spec.path` | required when file-scoped | относительный путь, absolute path только для local debug |
| `event.dataset` | required when dataset-aware | если spec относится к конкретному dataset |
| `nexus.dsl.yaml.path` | recommended for validation errors | помогает найти проблемный ключ без raw YAML |
| `nexus.dsl.rule.name` | recommended for rule-scoped compile/validation | имя правила, если есть |
| `nexus.dsl.operation.name` | recommended for operation-chain context | имя DSL operation, если ошибка привязана к operation |
| `nexus.dsl.error.count` | recommended for aggregate failures | summary validation/registry errors |
| `error.*` | required for failures | `error.code` должен брать diagnostic/catalog code, когда он есть |

### Detail policy для DSL

- `INFO` — только registry ready/failure и blocking DSL failures, влияющие на запуск команды.
- `DEBUG` — per-spec load/validate/compile summary.
- `TRACE` — discovery traversal, default resolution, YAML path traversal, operation-chain детали.
- `WARNING` — deprecated spec shape, fallback/default, optional artifact skipped, если команда продолжает работу.
- `ERROR` — blocking load/validation/compile/registry build failures.

### Что не логировать

- Raw YAML body, source CSV snippets, target payload, generated payload.
- Секреты, default passwords, token values, vault material.
- Every YAML key на INFO/DEBUG; для глубокой диагностики использовать TRACE и `nexus.dsl.yaml.path`.
- Absolute paths в обычном режиме, если достаточно `nexus.dsl.spec.path`.
- Runtime execution result как DSL-событие: lookup/cache/target/stage actions должны жить в своих зонах.

### Что важно учесть при миграции текущего кода

- Текущий `DSL load error` в orchestrator целево маппится в `dsl-load-failed`,
  `dsl-validation-failed` или `dsl-compile-failed` по деталям `DslLoadError`. Пока такого
  classifier нет, допустим общий `dsl-load-failed` с `error.code`.
- Старые generic actions `spec-loaded`, `spec-registry-built`, `spec-validation-failed` считаются
  legacy/compat. Новые call-sites должны использовать `dsl-*`.
- Dictionary/cache/target loaders используют DSL taxonomy только для lifecycle spec artifact.
  Runtime lookup/refresh/request события этих подсистем остаются в provider taxonomy.

## 🧱 Зона 8: Match decision service

Восьмая зона описывает match как **decision service**: enriched row превращается в typed
`MatchDecision` и `MatchedRow`. Это не просто cache lookup: matcher строит identity, ищет target
candidates, применяет fuzzy scoring, опционально уточняет решение через topology, проверяет
source-dedup и передаёт результат в resolve.

### Границы зоны

- Match taxonomy отвечает за `matched`, `not_found`, `ambiguous`, `conflict_source` и reason-коды
  решения.
- Cache/provider calls внутри match логируются через общую lookup taxonomy:
  `lookup-started` / `lookup-completed` с `nexus.lookup.provider.name=cache.match_runtime`.
- CREATE/UPDATE/SKIP не относятся к match. Это зона Resolve/Plan.
- HTTP/write/retry не относятся к match. Это зона Apply/Target.
- DSL validation/compile match-spec относится к DSL artifact lifecycle, а не к runtime match.
- Domain `MatchCore` не должен импортировать logger. При внедрении нужен порт событий
  (`MatchEventSink`) и infra adapter по аналогии с topology sink.

### Реальная модель, на которую опираемся

| Code model | Logging meaning |
|---|---|
| `MatchDecision.status` | `nexus.match.status` |
| `MatchDecision.reason_code` | `nexus.match.reason_code` |
| `MatchDecision.score` | `nexus.match.score` |
| `MatchDecision.selected` | selected candidate summary; raw target id не логировать |
| `MatchDecision.candidates` | candidate count/top-k summary only |
| `MatchDecision.topology_match_mode` | `nexus.match.topology.mode` |
| `MatchDecision.topology_reason` | `nexus.match.topology.reason` |
| `MatchDecision.meta["match_mode"]` | `nexus.match.mode` |
| `MatchedRow.identity` | identity field + safe fingerprint only |
| `MatchedRow.fingerprint_fields` | `nexus.match.fingerprint.fields_count`; raw `desired_state` не логировать |
| `MatchedRow.source_links` | `nexus.match.source_links.count`; raw links не логировать |
| `TransformResult.meta["match_drop_reason"]` | `nexus.match.drop.reason` |

### Canonical taxonomy для зоны

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `match-record-completed` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.stage.name`, `nexus.record.id` | `nexus.match.status`, `nexus.match.reason_code`, `nexus.match.mode`, `nexus.match.score`, `nexus.match.candidates.returned`, `nexus.match.source_links.count`, `nexus.match.fingerprint.fields_count` | after `MatchedRow` is built |
| `match-record-failed` | DEBUG/ERROR decision | `debug`/`error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.stage.name`, `error.*` | `nexus.record.id`, `nexus.match.identity.primary`, `nexus.match.reason_code` | missing identity, target conflict, topology hard error |
| `match-identity-resolved` | TRACE diagnostic | `trace` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.match.identity.rule.name`, `nexus.match.identity.primary`, `nexus.match.identity.value_fingerprint` | identity rule produced usable identity |
| `match-fuzzy-ranked` | TRACE diagnostic | `trace` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.match.candidates.count`, `nexus.match.candidates.returned`, `nexus.match.score`, `nexus.match.reason_code` | after fuzzy ranking |
| `match-topology-refined` | DEBUG/TRACE decision | `debug`/`trace` | `success`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.match.topology.applied`, `nexus.match.topology.mode`, `nexus.match.topology.reason`, `nexus.match.status`, `nexus.match.reason_code` | after topology refinement |
| `match-source-dedup-checked` | TRACE diagnostic | `trace` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.match.dedup.outcome`, `nexus.match.identity.value_fingerprint` | source dedup check returned first/duplicate/conflict |
| `match-source-dedup-dropped` | DEBUG/WARNING/ERROR decision | `debug`/`warning`/`error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.match.drop.reason`, `nexus.match.dedup.outcome`, `error.code` | duplicate/conflict policy drops row |
| `match-scope-cleared` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset` | `nexus.subsystem=match`, `nexus.match.batch.size` optional | runtime scope cleanup after match stage |
| `match-scope-clear-failed` | DEBUG decision | `warning` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `error.*` | `nexus.subsystem=match` | best-effort runtime scope cleanup failed |

`not_found` и `ambiguous` — это валидные match decisions, поэтому
`match-record-completed(event.outcome=success)` допустим. `event.outcome=failure` использовать,
когда matcher не смог вернуть корректный row-level result: `MATCH_IDENTITY_MISSING`,
`MATCH_CONFLICT_TARGET`, `TOPOLOGY_SOURCE_PATH_EMPTY`, source conflict с `on_conflict=error`.

### Минимальный field profile для match events

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | из match action-словаря |
| `event.outcome` | required on completion/failure | decision success не равен business match found |
| `trace.id` | required | correlation запуска |
| `event.dataset` | required | match всегда dataset-scoped |
| `nexus.stage.name` | required inside pipeline | `match` |
| `nexus.subsystem` | recommended | `match` для subsystem events; `cache` не использовать для decision events |
| `nexus.record.*` | recommended for record-scoped events | общий record context |
| `nexus.match.status` | required for decision completion | typed status из `MatchDecisionStatus` |
| `nexus.match.reason_code` | required for decision completion | canonical reason из `MatchDecisionReason` |
| `nexus.match.identity.primary` | recommended | field name only |
| `nexus.match.identity.value_fingerprint` | recommended | raw identity value запрещён |
| `nexus.match.candidates.count` | recommended for fuzzy/topology | aggregate count only |
| `nexus.match.selected.target_id_fingerprint` | optional | только safe fingerprint selected target |
| `nexus.match.topology.*` | recommended when topology configured/applied | evidence не логировать целиком |
| `nexus.lookup.*` | required for provider lookup telemetry | common lookup namespace, not match-specific |
| `error.*` | required for failures | diagnostic code in `error.code` when available |

### Detail policy для match

- `INFO` — не использовать для per-record match decisions. INFO уже покрывается stage lifecycle.
- `DEBUG` — итоговое решение по записи, topology refinement summary, source-dedup drop.
- `TRACE` — identity rule evaluation, lookup details, fuzzy ranking, dedup check, top-k candidate
  counts.
- `WARNING` — degraded but continued policy: duplicate source row dropped as warning, topology
  missing with non-hard policy if operator attention is needed.
- `ERROR` — row-level hard failures and stage-level unexpected exceptions.

### Что не логировать

- Raw `Identity.primary_value`, `match_key`, lookup key, source dedup key.
- `MatchedRow.desired_state`, `MatchedRow.existing`, candidate rows, source link payload.
- Raw selected `target_id`; use `nexus.match.selected.target_id_fingerprint`.
- `MatchDecision.topology_evidence` целиком. Разрешены только mode/reason/counts/safe fingerprints.
- `MatchedRow.fingerprint` по умолчанию. Это hash desired-state; использовать только при явном
  TRACE-решении и после security review.

### Что уже важно учесть при миграции текущего кода

- `MatchCore` сейчас не логирует напрямую, и это правильная boundary. Для внедрения нужен
  transport-neutral sink, например `MatchEventSink`, и adapter в `infra/logging`.
- `MatchRuntimePort.find()` внутри matcher логируется как provider lookup через `nexus.lookup.*`.
- `ScopedSourceDedupStore` использует runtime state через cache gateway, но taxonomy события
  остаются match/dedup decisions, а не cache admin events.
- `MatchUseCase` уже собирает `match_status`, topology mode/reason и topology counters для report.
  Logging taxonomy должна брать из этого safe summary, а не переносить `topology_evidence` целиком.
- `MatchScopeService.clear_scope()` — lifecycle cleanup match runtime scope; логировать как
  `match-scope-cleared` / `match-scope-clear-failed`, не как storage/cache clear.

## 🧱 Зона 9: Resolve / Plan decision & artifact lifecycle

Девятая зона делит финальную planning-часть на две ответственности:

- **Resolve**: `MatchedRow` превращается в `ResolvedRow` через operation decision
  (`create`/`update`/`skip`), link resolution, pending lifecycle и sink mutation validation.
- **Plan**: поток `ResolvedRow` агрегируется в `PlanSummary` и `PlanItem[]`, затем пишется
  `plan.json` artifact.

### Границы зоны

- Resolve taxonomy отвечает за per-record решение операции и link/pending outcomes.
- Plan taxonomy отвечает за build/write summary и plan artifact lifecycle.
- Identity match status и fuzzy/topology candidate matching остаются в match taxonomy.
- Target HTTP/write/retry остаётся в apply/target taxonomy.
- Pending lifecycle использует общий `nexus.pending.*`, но owner action может быть resolve-specific,
  когда pending создаётся или переигрывается внутри resolve flow.
- Raw payload, diff values, source_ref values, pending payload и target ids не логируются.

### Реальная модель, на которую опираемся

| Code model | Logging meaning |
|---|---|
| `ResolveContextStage.stage_name="resolve_context"` | `nexus.stage.name=resolve_context` |
| `ResolveCore.build_batch_index()` | `resolve-context-index-built`, `nexus.resolve.batch_index.*` |
| `ResolvedRow.op` | `nexus.resolve.op` |
| `ResolvedRow.changes` | `nexus.resolve.changes_count`; values не логировать |
| `ResolvedRow.target_id` | `nexus.resolve.target_id_fingerprint` |
| `ResolvedRow.source_ref` | `nexus.resolve.source_ref.fields_count`; raw source_ref не логировать |
| `ResolvedRow.secret_fields` | `nexus.resolve.secret_fields_count` |
| `ResolvedRow.secret_lifecycle` | `nexus.resolve.secret_lifecycle.*` |
| `LinkFieldRule.field` | `nexus.resolve.link.field` |
| `LinkFieldRule.target_dataset` | `nexus.resolve.link.target_dataset` |
| `_LinkLookupOutcome.candidate_ids` | `nexus.resolve.link.candidates_count` |
| `PendingExpiryService.drain_expired()` | `nexus.pending.expired.count` |
| `PlanSummary` | `nexus.plan.rows_total`, `nexus.plan.planned_create`, ... |
| `PlanItem` | `nexus.plan.item.*`; payload fields/counts only |
| `write_plan_file_with_layout()` | `plan-written`, `file.path`, `nexus.plan.*` summary |

### Canonical taxonomy для Resolve

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `resolve-context-index-built` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.stage.name` | `nexus.resolve.batch_index.keys_count`, `nexus.resolve.batch_index.values_count` | after `ResolveContextStage` builds batch index |
| `resolve-record-completed` | DEBUG decision | `debug` | `success`/`unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.stage.name`, `nexus.record.id` | `nexus.resolve.op`, `nexus.resolve.status`, `nexus.resolve.reason_code`, `nexus.resolve.changes_count`, `nexus.resolve.secret_fields_count` | after `ResolvedRow` is built |
| `resolve-record-failed` | DEBUG/ERROR decision | `debug`/`error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.stage.name`, `nexus.record.id`, `error.*` | `nexus.resolve.reason_code`, `nexus.resolve.link.field` optional | `RESOLVE_AMBIGUOUS`, `RESOLVE_CONFLICT`, `RESOLVE_TARGET_ID_MISSING`, `RESOLVE_CONFIG_MISSING`, sink validation issues |
| `resolve-op-selected` | TRACE diagnostic | `trace` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.resolve.op`, `nexus.resolve.reason_code`, `nexus.resolve.changes_count` | operation decision branch |
| `resolve-link-completed` | DEBUG/TRACE decision | `debug`/`trace` | `success`/`failure`/`unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.resolve.link.field`, `nexus.resolve.link.target_dataset`, `nexus.resolve.link.outcome`, `nexus.resolve.link.candidates_count`, `nexus.resolve.link.reason` | each link field resolution |
| `resolve-link-pending-created` | DEBUG/WARNING decision | `debug`/`warning` | `unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.resolve.link.field`, `nexus.resolve.link.lookup_key_fingerprint`, `nexus.pending.id`, `nexus.pending.attempts`, `nexus.pending.ttl_seconds` | `_create_pending_link()` |
| `resolve-link-max-attempts-reached` | WARNING/ERROR decision | `warning`/`error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id`, `error.code` | `nexus.resolve.link.field`, `nexus.pending.id`, `nexus.pending.attempts` | pending max attempts policy |
| `resolve-pending-replayed` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset` | `nexus.pending.replay.rows_count` | pending rows appended before resolve |
| `pending-decode-skipped` | WARNING decision | `warning` | `unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset` | `nexus.pending.decode.skipped_count` | invalid pending rows skipped during replay |
| `resolve-pending-expired` | DEBUG/WARNING/ERROR decision | `debug`/`warning`/`error` | `success`/`failure`/`unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset` | `nexus.pending.expired.count`, `nexus.pending.id`, `error.code` | expired pending drained/reported by policy |
| `resolve-pending-purged` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset` | `nexus.pending.purged.count`, `nexus.pending.retention_days` | pending retention purge |
| `resolve-merge-overwrite-blocked` | WARNING decision | `warning` | `unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.resolve.changed_fields` | merge policy tried to overwrite source values |

`RESOLVE_PENDING` обычно не является failure всего resolve: это degraded/continuation state.
`event.outcome=failure` использовать для hard errors: `RESOLVE_AMBIGUOUS`,
`RESOLVE_CONFLICT`, `RESOLVE_TARGET_ID_MISSING`, `RESOLVE_CONFIG_MISSING`,
`RESOLVE_MAX_ATTEMPTS` и hard topology/link policy failures.

### Canonical taxonomy для Plan

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `plan-build-started` | INFO/DEBUG milestone | `info`/`debug` | — | `event.action`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=plan` | before consuming resolved stream |
| `plan-item-created` | TRACE/DEBUG diagnostic | `trace`/`debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.plan.item.op`, `nexus.plan.item.changes_count`, `nexus.plan.item.secret_fields_count` | create/update item appended |
| `plan-item-skipped` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.resolve.op=skip` | resolved row skipped, no plan item written |
| `plan-item-failed` | DEBUG decision | `debug` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id`, `error.*` | `nexus.resolve.reason_code` | resolved result excluded from plan because of errors |
| `plan-build-completed` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type` | `nexus.plan.rows_total`, `nexus.plan.items_count`, `nexus.plan.planned_create`, `nexus.plan.planned_update`, `nexus.plan.skipped_rows`, `nexus.plan.failed_rows` | after `PlanBuilder.build_from_stream()` |
| `plan-build-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `error.*` | `event.dataset`, `nexus.subsystem=plan` | semantic plan command failure |
| `plan-written` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `file.path` | `event.dataset`, `nexus.plan.items_count`, `nexus.plan.planned_create`, `nexus.plan.planned_update` | plan artifact persisted |
| `plan-write-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `file.path`, `error.*` | `event.dataset`, `nexus.subsystem=plan` | artifact write failed specifically |

### Минимальный field profile

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | resolve/plan action dictionary |
| `event.outcome` | required on completion/failure | pending can be `unknown`; hard error is `failure` |
| `trace.id` | required | correlation запуска |
| `event.dataset` | required | resolve/plan are dataset-scoped |
| `nexus.stage.name` | required inside stages | `resolve_context` or `resolve` |
| `nexus.record.*` | recommended for record-scoped events | common record context |
| `nexus.resolve.op` | required for completed resolve decisions | `create`, `update`, `skip` |
| `nexus.resolve.status` | required for completed resolve decisions | `resolved`, `pending`, `failed`, `skipped` |
| `nexus.resolve.link.*` | required for link events | field/dataset/outcome/counts/fingerprints only |
| `nexus.pending.*` | required for pending lifecycle events | no pending payload / raw lookup key |
| `nexus.plan.*` | required for plan build/write summary | aggregate counters only |
| `file.path` | required for `plan-written`/`plan-write-failed` | plan artifact path from layout |
| `error.*` | required for failures | diagnostic code in `error.code` when available |

### Detail policy для Resolve / Plan

- `INFO` — plan build/write summary and command-level plan failures.
- `DEBUG` — per-record resolve decision, pending created, link unresolved, plan item skipped/failed.
- `TRACE` — op branch reasoning, link key candidate counts, batch index internals, per-plan-item
  append details.
- `WARNING` — pending/degraded states that require attention: invalid pending decode, merge overwrite
  blocked, max attempts nearing/hit depending policy.
- `ERROR` — hard row failures, artifact write failures, unexpected stage exceptions.

### Что не логировать

- `ResolvedRow.desired_state`, `ResolvedRow.changes` values, `PlanItem.desired_state`,
  `PlanItem.changes`.
- Raw `source_ref`, raw link lookup key, raw `target_id`, raw resolved id.
- Pending payload serialized by `PendingCodec`.
- Topology link evidence/details with raw source segments or candidate ids.
- Full plan item JSON. Log counts/fingerprints only.

### Что уже важно учесть при миграции текущего кода

- `ResolveCore` сейчас содержит direct stdlib logger warning for merge overwrite. При ECS-migration
  его лучше заменить на `resolve-merge-overwrite-blocked` через transport-neutral event sink.
- `ResolveUseCase.iter_resolved()` уже emits `pending_codec_skipped_invalid`; целевой action —
  `pending-decode-skipped`, field — `nexus.pending.decode.skipped_count`.
- `PlanBuilder` не знает о file system/reporting, и это правильно. Plan artifact events должны
  жить в delivery/infra artifact boundary, а plan item decisions — в плановом usecase/adapter seam.
- `Plan written` уже маппится в `plan-written`; добавить `file.path` и `nexus.plan.*` summary.
- `mark_resolved_for_source()` в ResolveCore относится к identity/pending state. Для отдельного
  события использовать уже существующий `identity-source-resolved`, не cache clear/status actions.

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
| `spec-loaded` / `spec-registry-built` / `spec-validation-failed` | DEBUG/INFO/ERROR | Legacy/compat generic spec actions; новый путь использует `dsl-*` |
| `dsl-registry-loaded` / `dsl-registry-built` | DEBUG/INFO | DSL registry загружен/собран |
| `dsl-registry-build-failed` | ERROR | Сборка DSL registry завершилась ошибкой |
| `dsl-spec-discovered` | TRACE | DSL spec artifact найден |
| `dsl-spec-loaded` | DEBUG | DSL spec YAML загружен |
| `dsl-spec-parsed` | TRACE/DEBUG | DSL spec разобран из YAML |
| `dsl-spec-validated` | DEBUG | DSL spec прошёл validation |
| `dsl-spec-compiled` | DEBUG | DSL spec скомпилирован в runtime object |
| `dsl-load-failed` | ERROR | Чтение DSL файла или YAML parse завершились ошибкой |
| `dsl-validation-failed` | ERROR | Structural/semantic validation DSL spec завершилась ошибкой |
| `dsl-compile-failed` | ERROR | Валидный DSL spec не удалось скомпилировать в runtime object |
| `match-record-completed` | DEBUG | Match сформировал typed decision для записи |
| `match-record-failed` | DEBUG/ERROR | Match не смог сформировать корректный row-level result |
| `match-identity-resolved` | TRACE | Identity rule дала usable identity |
| `match-fuzzy-ranked` | TRACE | Fuzzy candidates были ranked/scored |
| `match-topology-refined` | DEBUG/TRACE | Topology уточнила match decision |
| `match-source-dedup-checked` | TRACE | Source dedup check завершён |
| `match-source-dedup-dropped` | DEBUG/WARNING/ERROR | Source dedup policy дропнула запись |
| `match-scope-cleared` / `match-scope-clear-failed` | DEBUG/WARNING | Runtime scope matcher очищен/не очищен |
| `resolve-context-index-built` | DEBUG | ResolveContext построил batch index |
| `resolve-record-completed` | DEBUG | Resolve сформировал operation decision для записи |
| `resolve-record-failed` | DEBUG/ERROR | Resolve не смог сформировать корректный row-level result |
| `resolve-op-selected` | TRACE/DEBUG | Выбрана операция `create`/`update`/`skip` |
| `resolve-link-completed` | DEBUG/TRACE | Link field resolved/pending/ambiguous/missing |
| `resolve-link-pending-created` | DEBUG/WARNING | Создан pending link для unresolved link field |
| `resolve-link-max-attempts-reached` | WARNING/ERROR | Pending link достиг max attempts |
| `resolve-pending-replayed` | DEBUG | Pending rows загружены для replay |
| `pending-decode-skipped` | WARNING | Invalid pending rows skipped during replay |
| `resolve-pending-expired` | DEBUG/WARNING/ERROR | Expired pending обработан по policy |
| `resolve-pending-purged` | DEBUG | Stale pending rows удалены retention purge |
| `resolve-merge-overwrite-blocked` | WARNING | Merge policy tried to overwrite source values |
| `plan-build-started` / `plan-build-completed` | INFO/DEBUG | Сборка plan началась/завершилась |
| `plan-build-failed` | ERROR | Сборка plan завершилась ошибкой |
| `plan-item-created` | TRACE/DEBUG | Plan item добавлен в artifact payload |
| `plan-item-skipped` | DEBUG | Resolved row skipped, plan item не создан |
| `plan-item-failed` | DEBUG | Resolved result excluded from plan due to errors |
| `plan-written` / `plan-write-failed` | INFO/ERROR | Plan artifact записан/не записан |
| `cache-hit` / `cache-miss` | DEBUG | Legacy/compat результат кэш-лукапа; новый provider path — `lookup-completed` |
| `cache-refresh-started` / `cache-refresh-completed` | INFO | Старт/завершение cache refresh |
| `cache-refresh-failed` | ERROR | Cache refresh завершился ошибкой |
| `cache-refresh-dataset-completed` | DEBUG | Refresh одного cache dataset завершён |
| `cache-page-fetched` | DEBUG/TRACE | Target page получена во время cache refresh |
| `cache-item-upserted` | TRACE | Один source item записан в cache snapshot |
| `cache-item-upsert-failed` | ERROR/DEBUG | Ошибка записи одного source item в cache snapshot |
| `cache-clear-completed` / `cache-clear-failed` | INFO/ERROR | Очистка cache завершена/провалена |
| `cache-status-completed` / `cache-status-failed` | INFO/ERROR | Получение cache status завершено/провалено |
| `cache-drift-detected` | WARNING | Несовпадение content-hash кэша |
| `cache-rebuild-completed` / `cache-rebuild-failed` | INFO/ERROR | Cache rebuild завершён/провален |
| `target-write-started` / `target-write-completed` | INFO | Запись в целевую систему (apply) |
| `target-write-failed` | ERROR | Запись в цель провалилась после retry |
| `retry-attempt` | WARNING | Транзиентная ошибка, повтор |
| `record-skipped` | WARNING | Запись отброшена (с причиной) |
| `enrich-record-completed` | DEBUG | Enrich обработал одну запись и сформировал summary |
| `enrich-operation-completed` | TRACE | Enrich operation/rule выполнена для записи |
| `enrich-operation-skipped` | DEBUG | Enrich operation/rule пропущена по policy/condition |
| `enrich-resolve-requested` | DEBUG | Enrich создал resolve hint из неоднозначных candidates |
| `enrich-secret-fields-stored` | DEBUG | Enrich записал secret fields в vault и очистил row values |
| `lookup-started` / `lookup-completed` | TRACE/DEBUG | Provider lookup/exists/canonicalize в cache/dictionary/vault context |
| `identity-lookup-completed` | DEBUG | Identity index lookup завершён |
| `identity-upsert-completed` | DEBUG | Identity index обновлён после resolve/apply |
| `identity-source-resolved` | DEBUG | Source record помечена как resolved |
| `pending-link-created` | DEBUG | Resolve создал pending link |
| `pending-link-touched` | TRACE | Pending link получил новую попытку обработки |
| `pending-link-resolved` | DEBUG | Pending link разрешён |
| `pending-link-expired` | DEBUG/WARNING | Pending link истёк по TTL/policy |
| `pending-link-conflicted` | DEBUG/WARNING | Pending link переведён в conflict |
| `storage-operation-failed` | WARNING/ERROR | Storage backend operation завершилась ошибкой |
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
| orchestrator.py:494,802 | error | DSL load error | `dsl-load-failed` | failure |
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
| cache_refresh.py:126 | error | Cache refresh failed | `cache-refresh-failed` | failure |
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
| cache_refresh_service.py:298 | error | Cache refresh failed | `cache-refresh-failed` | failure |
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
