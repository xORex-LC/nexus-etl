# Zone 5: Enrich Subsystem

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
- `enrich-secret-fields-stored` фиксирует stage-level факт capture/store boundary, но actual vault
  runtime write lifecycle (`secret-written`, rollout/startup policy) живёт в Zone 11.

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
