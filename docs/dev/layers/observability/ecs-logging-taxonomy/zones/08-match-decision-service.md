# Zone 8: Match Decision Service

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
