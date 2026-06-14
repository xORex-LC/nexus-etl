# Zone 14: Normalize / Data Quality Stage

Четырнадцатая зона описывает runtime-события стадии Normalize: применение DSL operation chains к
mapped row, безопасную фиксацию data-quality результата, sink validation и propagation upstream
failures.

Normalize находится между Map и Enrich:

```text
Map -> Normalize -> Enrich
```

Стадия не делает I/O, не обращается к cache/vault/dictionaries/target и не принимает решений по
identity. Её observability должна отвечать на вопрос: **какие поля и правила были применены к записи,
что изменилось на уровне shape/type/nullability, и почему запись стала failed или warning**.

### Границы зоны

- `stage-started` / `stage-completed` остаются в Zone 3. Эта зона описывает normalize-specific
  record/rule/validation telemetry.
- DSL load/parse/compile failures (`dsl-*`, `NORMALIZE_DSL_*`) остаются в Zone 7. Здесь речь про
  runtime execution уже скомпилированных правил.
- Mapping failures не переописываются как normalize failures. Если запись пришла с upstream errors,
  Normalize только forwarding/skipping.
- Sink schema validation errors относятся к Normalize только если они возникли при validation
  результата Normalize.
- Raw row values, before/after values, emails, phone numbers, names, personnel ids и full payload
  не логируются. Допустимы только имена полей, типы, counters, fingerprints where explicitly needed.

### Реальная модель, на которую опираемся

| Code model | Logging meaning |
|---|---|
| `NormalizeStage.stage_name = "normalize"` | `nexus.stage.name=normalize` |
| `NormalizeStage.run()` upstream error guard | `normalize-record-skipped` with `nexus.normalize.skip.reason=upstream_failed` |
| `diagnostic_boundary(DiagnosticStage.NORMALIZE)` | `normalize-record-failed` for unexpected boundary diagnostics |
| `NormalizerEngine` | DSL-aware wrapper; owns compiled runtime normalize core |
| `CompiledNormalizeRules.rules` | `nexus.normalize.rules_total`, rule index/field/op counters |
| `NormalizeRule.field`, `NormalizeRule.ops`, `NormalizeRule.on_error` | rule-level safe context |
| `apply_ops(self.engine, value, rule.ops)` | `normalize-rule-applied` / `normalize-rule-failed` |
| `touched_fields` | `nexus.normalize.fields_touched_count`, validation scope |
| `NormalizeDslBuildOptions.validate_only_touched_fields` | `nexus.normalize.validation.scope=touched_fields|full_row` |
| `validate_sink_fields()` / `validate_sink_row()` | `normalize-validation-completed` / `normalize-validation-failed` |
| `DslIssue.code` from op/validation failures | `nexus.diagnostic.code`, `error.code` on failure-path |
| `StageResultReporter` for normalize command | stage counters: `normalized_ok`, `normalize_failed` mapped to generic `nexus.stage.*` |

### Canonical taxonomy для Normalize runtime

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `normalize-record-skipped` | DEBUG decision | `debug` | `unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.subsystem=normalize`, `nexus.stage.name=normalize`, `nexus.normalize.skip.reason=upstream_failed`, `nexus.normalize.upstream.errors_count`, `nexus.normalize.upstream.warnings_count` | `NormalizeStage.run()` / `NormalizerCore.normalize()` sees failed upstream result |
| `normalize-record-completed` | DEBUG decision | `debug` / `warning` | `success` / `unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.subsystem=normalize`, `nexus.stage.name=normalize`, `nexus.normalize.rules_total`, `nexus.normalize.rules_applied`, `nexus.normalize.rules_skipped`, `nexus.normalize.fields_touched_count`, `nexus.normalize.changed_fields_count`, `nexus.normalize.warnings_count`, `nexus.normalize.validation.scope` | after one row is normalized without fatal errors |
| `normalize-record-failed` | DEBUG/ERROR decision | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id`, `error.code`, `error.message` | `nexus.subsystem=normalize`, `nexus.stage.name=normalize`, `nexus.normalize.rules_total`, `nexus.normalize.rules_applied`, `nexus.normalize.rules_failed`, `nexus.normalize.fields_touched_count`, `nexus.normalize.failure.reason`, `nexus.diagnostic.code` | after one row ends with normalize-local fatal diagnostics or boundary error |
| `normalize-rule-applied` | TRACE diagnostic | `trace` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.subsystem=normalize`, `nexus.stage.name=normalize`, `nexus.normalize.rule.field`, `nexus.normalize.rule.index`, `nexus.normalize.rule.ops_count`, `nexus.normalize.rule.on_error`, `nexus.normalize.value.changed` | optional sampled event after one rule operation chain succeeds |
| `normalize-rule-failed` | DEBUG diagnostic | `debug` / `warning` / `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id`, `error.code` | `nexus.subsystem=normalize`, `nexus.stage.name=normalize`, `nexus.normalize.rule.field`, `nexus.normalize.rule.index`, `nexus.normalize.rule.ops_count`, `nexus.normalize.rule.on_error`, `nexus.normalize.failure.reason=dsl_op_failed`, `nexus.diagnostic.code` | `apply_ops()` returns one or more `DslIssue` for a rule |
| `normalize-validation-completed` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.subsystem=normalize`, `nexus.stage.name=normalize`, `nexus.normalize.validation.scope`, `nexus.normalize.validation.fields_checked_count`, `nexus.normalize.validation.issues_count=0` | sink validation completed without issues |
| `normalize-validation-failed` | DEBUG/WARNING decision | `warning` / `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id`, `error.code` | `nexus.subsystem=normalize`, `nexus.stage.name=normalize`, `nexus.normalize.validation.scope`, `nexus.normalize.validation.fields_checked_count`, `nexus.normalize.validation.issues_count`, `nexus.normalize.validation.required_missing_count`, `nexus.normalize.validation.type_invalid_count`, `nexus.diagnostic.code` | sink validation produced issues (`SINK_REQUIRED_MISSING`, `SINK_TYPE_INVALID`, etc.) |

### Нормализация и анти-дублирование

- `normalize-record-completed` не заменяет `stage-completed`. Первое описывает одну запись, второе
  агрегирует всю stage execution.
- `normalize-rule-applied` является TRACE/forensic event. Baseline ES
  мониторинг должен жить на `normalize-record-*` + `stage-completed`. Rule с пустым op-chain (`no_ops`)
  не эмитит отдельное событие — он отражается только в счётчике `nexus.normalize.rules_skipped`.
- `normalize-rule-failed` фиксирует проблему DSL operation chain на конкретном поле. Если эта
  проблема по `on_error=warn` не делает запись failed, итоговая запись всё равно получает
  `normalize-record-completed` с `event.outcome=unknown`.
- `normalize-validation-failed` описывает sink schema mismatch после normalize. Не смешивать с DSL
  compile-time validation и не относить к Enrich/Resolve.
- Имена полей (`nexus.normalize.rule.field`) допустимы, значения полей запрещены.
- `changed_fields_count` должен считаться без раскрытия before/after values. Список имён changed
  fields допустим только в sampled/debug mode и только если field names сами не раскрывают секрет.

### Минимальный field profile

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | из normalize action dictionary |
| `event.outcome` | required on record/rule/validation completion | `success` / `failure` / `unknown` |
| `trace.id` | required | command/pipeline run correlation |
| `event.dataset` | required | Normalize всегда dataset-scoped |
| `service.type` | recommended | `normalizer`, `planner`, либо component текущей команды |
| `nexus.subsystem` | required | `normalize` |
| `nexus.stage.name` | required | `normalize` |
| `nexus.record.id`, `nexus.record.line_no` | required/recommended for record-level events | row id required; line number if available |
| `nexus.record.identity.primary` | optional | only identity field name, no value |
| `nexus.record.identity.value_fingerprint` | optional | only if safe fingerprint is already available |
| `nexus.normalize.rules_total` | required on record summary | total compiled rules for current normalize spec |
| `nexus.normalize.rules_applied` | required on record summary | rules with non-empty ops executed |
| `nexus.normalize.rules_skipped` | recommended | no-op rules or future policy skips |
| `nexus.normalize.rules_failed` | recommended on failure/warning | number of rules that emitted issues |
| `nexus.normalize.fields_touched_count` | required on record summary | size of `touched_fields` |
| `nexus.normalize.changed_fields_count` | recommended | count only; no values |
| `nexus.normalize.null_fields_count` | optional | after-normalize null count if cheap to compute |
| `nexus.normalize.warnings_count` | recommended | normalize-local warnings for one record |
| `nexus.normalize.errors_count` | recommended | normalize-local errors for one record |
| `nexus.normalize.rule.field` | required on rule-level events | safe field name only |
| `nexus.normalize.rule.index` | recommended | ordinal in compiled rule list |
| `nexus.normalize.rule.ops_count` | required on rule-level events | length of op chain |
| `nexus.normalize.rule.on_error` | recommended | `error` / `warn` |
| `nexus.normalize.value.changed` | recommended on rule-level events | boolean; no before/after values |
| `nexus.normalize.validation.scope` | required when sink validation runs | `touched_fields` / `full_row` |
| `nexus.normalize.validation.fields_checked_count` | recommended | number of sink fields checked |
| `nexus.normalize.validation.issues_count` | required on validation failure | total validation issues |
| `nexus.normalize.validation.required_missing_count` | recommended | count `SINK_REQUIRED_MISSING` |
| `nexus.normalize.validation.type_invalid_count` | recommended | count `SINK_TYPE_INVALID` |
| `nexus.normalize.skip.reason` | required on skipped events | `upstream_failed`, `no_ops`, future policy reasons |
| `nexus.normalize.failure.reason` | required on failed events | `dsl_op_failed`, `sink_required_missing`, `sink_type_invalid`, `boundary_error`, ... |
| `nexus.normalize.upstream.errors_count`, `nexus.normalize.upstream.warnings_count` | recommended on upstream skip | counters only |
| `nexus.diagnostic.code` | recommended on diagnostics bridge | current/future domain diagnostic code |
| `error.code`, `error.message` | required on failure events | code from diagnostic/issue, message safe and redacted |

### Detail policy для Normalize

- `INFO` — не использовать для per-record Normalize. Aggregate lifecycle уже покрыт Zone 3.
- `DEBUG` — record summaries, failed/warning rules, validation failures.
- `WARNING` — only when `on_error=warn` creates data-quality degradation that should be visible in
  normal operations.
- `ERROR` — fatal row-level normalize failure or unexpected boundary exception.
- `TRACE` — rule-applied/no-op details and operation-level chain telemetry; disabled or sampled by
  default on large datasets.

### Что не логировать

- Raw input/output values before and after normalize.
- Full mapped/normalized row payload.
- Operation args if they can contain values, regexes with sensitive literals, defaults or masks.
- Field lists by default on high-volume logs; prefer counts. If field names are emitted, values remain
  forbidden.
- `SourceRecord.values`, sink payload, secret candidates or vault locator material.

### Что уже легко заполнить при внедрении

- `compiled.rules` gives `rules_total`, rule index, field name, `ops_count`, `on_error`.
- `touched_fields` already exists in `NormalizerCore`.
- `NormalizeDslBuildOptions.validate_only_touched_fields` directly maps to validation scope.
- `validate_sink_fields()` / `validate_sink_row()` return structured `DslIssue.code` and `field`.
- `TransformResult.row_ref` gives record id and line number via existing record context taxonomy.
- `StageResultReporter` already produces aggregate normalize counters for report context; Zone 3 can
  map those to `nexus.stage.*` on `stage-completed`.

### Что потребует небольшой доработки instrumentation

- Count `changed_fields_count` by comparing type/value equality before assignment, without logging
  values.
- Preserve rule index while iterating compiled rules.
- Split validation issue counters by code (`SINK_REQUIRED_MISSING`, `SINK_TYPE_INVALID`).
- Decide whether TRACE rule-level telemetry is sampled, globally disabled, or enabled by a
  diagnostics/detail profile.

### Что останется на будущие зоны

- Mapping field projection and missing source fields — mapping taxonomy.
- Enrich lookups, dictionaries, cache and vault writes — Zone 5/6/11.
- Match/Resolve identity decisions — Zone 8/9.
- Topology validation and source topology filtering — topology taxonomy.

---
