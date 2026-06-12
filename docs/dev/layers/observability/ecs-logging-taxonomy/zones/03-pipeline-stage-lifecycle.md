# Zone 3: Pipeline Stage Lifecycle

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
- `apply-item` и target request lifecycle — зона target/apply subsystem (Zone 10).

---
