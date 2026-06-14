# Zone 16: Map / Mapping Stage

Шестнадцатая зона описывает Map stage: первый transform-step после Extract, где raw
`SourceRecord.values` превращается в named output row по `MappingSpec`.

Эта зона отвечает на вопрос: **какие source fields были спроецированы в target fields, какие
mapping rules/ops/validation gates сработали и почему запись стала failed до Normalize**.

### Границы зоны

- Generic stage lifecycle (`stage-started`, `stage-completed`, `stage-failed`) остаётся в Zone 3.
- Physical source read/header/stream failures остаются в Zone 13. Mapping работает уже с
  `SourceRecord.values`.
- DSL load/parse/compile failures (`MAP_DSL_*`, `DSL_OP_UNKNOWN`) остаются в Zone 7. Здесь речь про
  runtime application already compiled mapping rules.
- Normalize data quality/type coercion остаётся в Zone 14. Mapping фиксирует field projection и первый
  schema gate.
- Enrich secret writes/vault lifecycle остаются в Zone 5/11. Mapping может логировать только
  `secret_candidates_count`, но не значения и не vault operations.
- Raw source values, mapped values, secret candidates values, full row dict and full meta dict are
  never logged.

### Сверка с текущей моделью кода

| Code model | Logging meaning |
|---|---|
| `MapStage.run()` upstream failure branch | `mapping-record-skipped` |
| `MapStage.run()` `diagnostic_boundary` branch | `mapping-record-failed` for boundary errors |
| `MapperCore._apply_rules()` | per-record mapping summary and rule iteration |
| `MapperCore._resolve_rule_value()` | source field resolution and DSL op chain |
| `MapperCore._assign_targets()` | target assignment and required target check |
| `MapperCore._validate_schema()` | mapping schema required-field gate |
| `MapperCore._validate_sink()` | sink schema gate after Map |
| `MapperCore._resolve_meta_value()` / `_set_meta()` | meta rule execution |
| `StageResultReporter` in `MappingUseCase` | aggregate `mapped_ok` / `mapping_failed` report counters |

Current implementation detail: `MapperCore.map_record()` returns `row_ref=None`, while diagnostics use
`_row_ref_from_record(record)` for `line_no`/`row_id`. Target taxonomy still assumes record context via
`nexus.record.*`; implementation migration should either assign `TransformResult.row_ref` at Map or bind
record fields from `SourceRecord` directly in mapping log instrumentation.

### Canonical taxonomy для record/rule lifecycle

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `mapping-record-skipped` | DEBUG decision | `debug` | `unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.*` | `nexus.subsystem=mapping`, `nexus.stage.name=map`, `nexus.mapping.skip.reason=upstream_failed`, `nexus.mapping.upstream.errors_count`, `nexus.mapping.upstream.warnings_count` | `MapStage.run()` forwards upstream failed result |
| `mapping-record-completed` | DEBUG/WARNING decision | `debug`/`warning` | `success`/`unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.*` | `nexus.subsystem=mapping`, `nexus.stage.name=map`, `nexus.mapping.rules_total`, `nexus.mapping.rules_applied`, `nexus.mapping.fields_touched_count`, `nexus.mapping.targets_assigned_count`, `nexus.mapping.secret_candidates_count`, `nexus.mapping.meta.rules_applied`, `nexus.mapping.warnings_count` | after `_apply_rules()` returns row without fatal errors |
| `mapping-record-failed` | DEBUG/ERROR decision | `debug`/`error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.*`, `error.code` | `nexus.subsystem=mapping`, `nexus.stage.name=map`, `nexus.mapping.failure.reason`, `nexus.mapping.errors_count`, `nexus.mapping.rules_failed`, `nexus.mapping.source.missing_count`, `nexus.diagnostic.code` | after `_apply_rules()` returns fatal errors or boundary diagnostics |
| `mapping-rule-applied` | TRACE diagnostic | `trace` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.*` | `nexus.subsystem=mapping`, `nexus.stage.name=map`, `nexus.mapping.rule.index`, `nexus.mapping.source.fields_count`, `nexus.mapping.targets_assigned_count`, `nexus.mapping.rule.ops_count`, `nexus.mapping.rule.required`, `nexus.mapping.rule.on_error`, `nexus.mapping.meta.path` (when meta rule) | one mapping/meta rule read source, applied ops and assigned targets |
| `mapping-rule-failed` | DEBUG/WARNING/ERROR decision | `debug`/`warning`/`error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.*`, `error.code` | `nexus.subsystem=mapping`, `nexus.stage.name=map`, `nexus.mapping.rule.index`, `nexus.mapping.source.field`, `nexus.mapping.target.field`, `nexus.mapping.meta.path` (when meta rule), `nexus.mapping.rule.on_error`, `nexus.mapping.failure.reason`, `nexus.diagnostic.code` | source missing, op failed, required target missing, meta DSL issue |

### Canonical taxonomy для validation

> Meta-rule lifecycle свёрнут в `mapping-rule-applied` / `mapping-rule-failed` (meta-контекст —
> через `nexus.mapping.meta.path`). Schema- и sink-validation объединены в одну пару с областью
> `nexus.mapping.validation.scope` (`mapping_schema` | `sink_full_row`).

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `mapping-validation-completed` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.*` | `nexus.subsystem=mapping`, `nexus.stage.name=map`, `nexus.mapping.validation.scope`, `nexus.mapping.validation.fields_checked_count` | `_validate_schema()` (scope=mapping_schema) / `_validate_sink()` (scope=sink_full_row) produced no issues |
| `mapping-validation-failed` | DEBUG/WARNING/ERROR decision | `debug`/`warning`/`error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.*`, `error.code` | `nexus.subsystem=mapping`, `nexus.stage.name=map`, `nexus.mapping.validation.scope`, `nexus.mapping.validation.required_missing_count`, `nexus.mapping.validation.type_invalid_count`, `nexus.mapping.validation.issues_count`, `nexus.diagnostic.code` | schema/sink validation produced issues |

### Нормализация и анти-дублирование

- Не плодить `map-started` / `map-completed`: это `stage-*` с `nexus.stage.name=map`.
- Не логировать `SourceRecord.values`, output row, before/after values, operation args or full meta.
- Rule-level events are TRACE by default. Production INFO baseline should rely on Zone 3 aggregate
  `stage-completed` plus report counters.
- `mapping-rule-failed` should be emitted only for mapping-local issues. Upstream Extract failures are
  `mapping-record-skipped`, not rule failures.
- `mapping-validation-*` (scope=sink_full_row) is Map-owned first schema gate. Normalize has its own
  validation events because it validates post-normalized values.
- Field names are generally acceptable operational metadata. If a dataset treats source/target field
  names as sensitive, omit raw field names and log counts only.

### Минимальный field profile

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | mapping action dictionary |
| `event.outcome` | required on completion/decision | `success`, `failure`, `unknown` |
| `trace.id` | required | command/pipeline run correlation |
| `event.dataset` | required | business dataset |
| `nexus.subsystem` | required | `mapping` |
| `nexus.stage.name` | required | `map` |
| `nexus.record.id`, `nexus.record.line_no` | recommended | from `RowRef` or `SourceRecord`; no business values |
| `nexus.mapping.rules_total`, `nexus.mapping.rules_applied`, `nexus.mapping.rules_failed` | recommended | per-record summary counters |
| `nexus.mapping.fields_touched_count`, `nexus.mapping.targets_assigned_count` | recommended | output shape counters |
| `nexus.mapping.source.missing_count` | required on missing source failures | count only |
| `nexus.mapping.source.field`, `nexus.mapping.target.field` | optional on rule events | names only, values forbidden |
| `nexus.mapping.rule.index`, `nexus.mapping.rule.ops_count` | recommended on rule events | stable low-cardinality context |
| `nexus.mapping.rule.required`, `nexus.mapping.rule.on_error` | recommended on rule failures | explains fatal vs warning behavior |
| `nexus.mapping.validation.scope` | required on validation events | `mapping_schema`, `sink_full_row` |
| `nexus.mapping.validation.issues_count` | required on validation failures | total issue count |
| `nexus.mapping.validation.required_missing_count` | recommended on validation failures | split by issue kind |
| `nexus.mapping.secret_candidates_count` | recommended on record summary | count only |
| `nexus.mapping.failure.reason` | required on failures | stable reason, usually diagnostic code normalized to lower/kebab |
| `nexus.diagnostic.code`, `error.code` | required on failures | domain diagnostic code |

### Detail policy

- `INFO` — не использовать для per-record Mapping. Stage lifecycle already covers operational INFO.
- `DEBUG` — per-record completed/failed/skipped summaries when diagnostics profile asks for detail.
- `WARNING` — non-fatal mapping degradation when `on_error=warn` keeps row alive but operator attention
  is useful.
- `ERROR` — boundary errors or fatal mapping diagnostics when the row cannot continue.
- `TRACE` — rule-level source/target/meta events, sampled or disabled by default.

### Что потребует небольшой доработки instrumentation

- Preserve rule index while iterating `compiled.rules` and `compiled.meta`.
- Count assigned targets, touched fields, missing source fields and validation issues by code.
- Decide where to bind record context while `TransformResult.row_ref` remains `None` after Map.
- If secret candidate tracking is restored/expanded, expose only `secret_candidates_count`.
- Keep `validate_sink_row(..., check_types=False)` semantics explicit: Map sink validation currently
  catches required/nullability issues, not type mismatches.

---
