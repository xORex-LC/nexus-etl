# Zone 9: Resolve / Plan Decision & Artifact Lifecycle

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
