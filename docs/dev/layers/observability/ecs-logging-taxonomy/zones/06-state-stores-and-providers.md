# Zone 6: State Stores / Provider Subsystems

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
