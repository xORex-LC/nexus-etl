# Zone 15: Topology Subsystem

Пятнадцатая зона описывает topology subsystem: pre-handler bootstrap, target/source graph build,
readiness/freshness, source anchoring validation, row-level filtering и topology-aware consumers в
Match/Resolve.

Это единственная подсистема, где уже есть явный logging seam:

- `TopologyEventSink` в `connector/domain/ports/topology/observability.py`;
- `StructlogTopologyEventSink` в `connector/infra/logging/topology.py`;
- runtime events в `TopologyBootstrapUseCase` и `TopologyBootstrapStep`.

Текущие event names (`bootstrap.start`, `readiness.stale`, `target.build.finish`, ...) должны быть
нормализованы в ECS `event.action` (`topology-bootstrap-started`, `topology-readiness-evaluated`,
`topology-target-build-completed`, ...), а текущий payload должен лечь в `nexus.topology.*`.

### Границы зоны

- Generic DSL load/parse/validation остаётся в Zone 7. Здесь фиксируется topology runtime bootstrap
  и shape уже загруженной topology spec.
- `stage-started` / `stage-completed` остаются в Zone 3. Source topology filter — обычная pipeline
  stage с `nexus.stage.name=source_topology_filter`, но её row-level decisions относятся к этой зоне.
- Match final decision остаётся в Zone 8. Topology zone описывает topology refinement signal; Match
  zone решает, как это влияет на `MatchDecision`.
- Resolve link/pending lifecycle остаётся в Zone 9. Topology zone описывает topology disambiguation
  signal для link candidates.
- Cache read/storage events остаются в Zone 6. Topology events могут ссылаться на
  `nexus.cache.dataset`, `nexus.cache.role=topology_read`, но не должны подменять cache telemetry.
- Raw node ids, parent ids, target ids, source path segments, canonical names, candidate ids и
  `TopologyComparisonResult.evidence` целиком не логируются. Использовать counts, modes, reasons,
  safe fingerprints.

### Реальная модель, на которую опираемся

| Code model | Logging meaning |
|---|---|
| `TopologyRequirementResolver.resolve()` | `topology-activation-evaluated` |
| `TopologyBootstrapStep.run()` inactive path | `topology-bootstrap-skipped` |
| `TopologyBootstrapStep.run()` config/capability failure | `topology-bootstrap-short-circuited` |
| `TopologyBootstrapUseCase.run()` | `topology-bootstrap-started` / `topology-bootstrap-completed` |
| current `bootstrap.start` | maps to `topology-bootstrap-started` |
| current `spec.loaded` | maps to `topology-spec-loaded` |
| current `canonicalizer.compiled` | maps to `topology-canonicalizer-compiled` |
| current `target.build.start` | maps to `topology-target-build-started` |
| current `readiness.evaluated`, `readiness.empty`, `readiness.stale` | maps to `topology-readiness-evaluated` |
| current `target.build.finish` | maps to `topology-target-build-completed` |
| current `source.validation.finish` | maps to `topology-source-validation-completed` |
| current `bootstrap.finish` | maps to `topology-bootstrap-completed` |
| `TraceToSink.node_ingested()` / `.path_ingested()` / `.cycle_checked()` | debug graph build diagnostics |
| `SourceTopologyFilterStage.run()` | `topology-source-row-filtered` |
| `compare_topology_candidates()` | shared comparison signal for match/resolve consumers |
| `MatchDecision.topology_*` | match consumer result; summarized in `match-topology-refined` or `topology-comparison-completed` |
| `TopologyLinkResolutionResult` | resolve link consumer result; summarized in `resolve-link-completed` or `topology-link-resolution-completed` |

### Canonical taxonomy для bootstrap/build/readiness

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `topology-activation-evaluated` | INFO/DEBUG decision | `debug` | `success`/`unknown`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=topology`, `nexus.topology.pipeline_dataset`, `nexus.topology.dataset`, `nexus.topology.activation.sources`, `nexus.topology.activation.capability_enabled`, `nexus.topology.activation.requires_source`, `nexus.topology.activation.requires_target`, `nexus.topology.activation.skipped_reason`, `nexus.topology.activation.error` | after `TopologyRequirementResolver.resolve()` |
| `topology-bootstrap-started` | INFO milestone | `info` | — | `event.action`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=topology`, `nexus.topology.pipeline_dataset`, `nexus.topology.dataset`, `nexus.topology.activation.requires_source`, `nexus.topology.activation.requires_target` | current `bootstrap.start` |
| `topology-bootstrap-skipped` | DEBUG decision | `debug` | `unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset` | `nexus.subsystem=topology`, `nexus.topology.activation.skipped_reason`, `nexus.topology.activation.sources` | current `bootstrap.skipped` |
| `topology-bootstrap-short-circuited` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `error.code`, `error.message` | `nexus.subsystem=topology`, `nexus.topology.failure.reason`, `nexus.topology.side`, `nexus.diagnostic.code` | current `bootstrap.short_circuit` |
| `topology-spec-loaded` | INFO/DEBUG milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset` | `nexus.subsystem=topology`, `nexus.topology.dataset`, `nexus.topology.source.mode`, `nexus.topology.target.mode`, `nexus.topology.source.path_columns_count` | current `spec.loaded` |
| `topology-canonicalizer-compiled` | INFO/DEBUG milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset` | `nexus.subsystem=topology`, `nexus.topology.normalization.version`, `nexus.topology.canonicalizer.ops_count` | current `canonicalizer.compiled` |
| `topology-target-build-started` | INFO milestone | `info` | — | `event.action`, `trace.id`, `event.dataset` | `nexus.subsystem=topology`, `nexus.topology.dataset`, `nexus.topology.target.node_id_field`, `nexus.topology.target.parent_id_field`, `nexus.topology.target.label_field` | current `target.build.start` |
| `topology-readiness-evaluated` | INFO/WARNING/ERROR decision | `info`/`warning`/`error` | `success`/`unknown`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset` | `nexus.subsystem=topology`, `nexus.topology.side=target`, `nexus.topology.readiness.ready`, `nexus.topology.readiness.decision`, `nexus.topology.readiness.reason`, `nexus.topology.freshness.present`, `nexus.topology.freshness.age_seconds`, `nexus.topology.freshness.max_age_seconds`, `nexus.cache.schema_hash.actual` or `nexus.topology.cache_snapshot_revision` | current `readiness.*` |
| `topology-target-build-completed` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset` | `nexus.subsystem=topology`, `nexus.topology.side=target`, `nexus.topology.nodes_count`, `nexus.topology.roots_count`, `nexus.topology.max_depth` | current `target.build.finish` |
| `topology-source-validation-completed` | INFO/WARNING/ERROR milestone | `info`/`warning`/`error` | `success`/`unknown`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset` | `nexus.subsystem=topology`, `nexus.topology.side=source`, `nexus.topology.source.nodes_count`, `nexus.topology.target.membership_count`, `nexus.topology.source.anchored_count`, `nexus.topology.source.dropped_count`, `nexus.topology.source.on_unanchored`, `nexus.topology.source.dropped_by_reason.*` | current `source.validation.finish` |
| `topology-bootstrap-completed` | INFO milestone | `info`/`warning`/`error` | `success`/`unknown`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `event.duration` | `nexus.subsystem=topology`, `nexus.topology.bootstrap.status`, `nexus.topology.built_sides`, `nexus.topology.errors_count`, `nexus.topology.warnings_count` | current `bootstrap.finish` |

### Canonical taxonomy для graph diagnostics

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `topology-node-ingested` | TRACE diagnostic | `trace` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset` | `nexus.subsystem=topology`, `nexus.topology.side=target`, `nexus.topology.node.id_fingerprint`, `nexus.topology.parent.id_fingerprint`, `nexus.topology.node.canonical_name_fingerprint` | current `target.node_ingested` |
| `topology-path-ingested` | TRACE diagnostic | `trace` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset` | `nexus.subsystem=topology`, `nexus.topology.side=source`, `nexus.topology.path.depth`, `nexus.topology.path.fingerprint`, `nexus.topology.node.synthetic_id_fingerprint` | current `source.path_ingested` |
| `topology-cycle-checked` | TRACE diagnostic | `trace` | `success`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset` | `nexus.subsystem=topology`, `nexus.topology.graph.algorithm=graphlib`, `nexus.topology.nodes_count`, `nexus.topology.graph.has_cycle` | current `target.cycle_check` |
| `topology-source-row-filtered` | DEBUG/WARNING decision | `debug`/`warning`/`error` | `unknown`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.subsystem=topology`, `nexus.stage.name=source_topology_filter`, `nexus.topology.source.node_id_field`, `nexus.topology.source.node_id_fingerprint`, `nexus.topology.source.on_unanchored`, `nexus.topology.source.drop.reason`, `error.code=TOPOLOGY_SOURCE_UNANCHORED` | `SourceTopologyFilterStage.run()` applies dropped verdict |

### Canonical taxonomy для topology consumers

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `topology-comparison-completed` | DEBUG/TRACE decision | `debug`/`trace` | `success`/`unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.subsystem=topology`, `nexus.topology.consumer=match|resolve`, `nexus.topology.comparison.mode`, `nexus.topology.comparison.reason`, `nexus.topology.comparison.candidates_count`, `nexus.topology.comparison.matched_count`, `nexus.topology.comparison.ambiguous`, `nexus.topology.comparison.ladder`, `nexus.topology.path.depth`, `nexus.topology.path.fingerprint` | after `compare_topology_candidates()` result is interpreted |
| `topology-match-refined` | DEBUG decision | `debug` | `success`/`unknown`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.subsystem=topology`, `nexus.stage.name=match`, `nexus.match.topology.applied`, `nexus.match.topology.mode`, `nexus.match.topology.reason`, `nexus.match.candidates.count`, `nexus.match.status`, `nexus.match.reason_code` | `MatchCore._refine_with_topology()` |
| `topology-link-resolution-completed` | DEBUG decision | `debug`/`warning`/`error` | `success`/`unknown`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.subsystem=topology`, `nexus.stage.name=resolve`, `nexus.resolve.link.field`, `nexus.resolve.link.topology.applied`, `nexus.resolve.link.topology.mode`, `nexus.resolve.link.topology.reason`, `nexus.resolve.link.candidates_count`, `nexus.resolve.link.outcome` | `ResolveCore._resolve_with_topology()` |

Zone 8/9 may still emit `match-topology-refined` and `resolve-link-completed` as stage-owned
events. The topology-specific actions above are useful if implementation keeps the owner at
`TopologyEventSink`. Do not emit both unless one is aggregate and the other is sampled/TRACE.

### Нормализация и анти-дублирование

- `topology-spec-loaded` is runtime topology summary, not a replacement for generic
  `dsl-spec-loaded`.
- `topology-readiness-evaluated` should collapse current `readiness.evaluated`, `readiness.empty`
  and `readiness.stale` into one action with `nexus.topology.readiness.reason`.
- `topology-bootstrap-short-circuited` is command-affecting and should be ERROR when it produces a
  `CommandResult` with diagnostics.
- `topology-node-ingested` / `topology-path-ingested` / `topology-cycle-checked` are TRACE only. Do not
  enable them as INFO/DEBUG baseline on large hierarchies.
- Match/Resolve topology evidence must be summarized, not logged as `evidence` dict. Current evidence
  includes source segments and candidate ids.
- If a graph id is operationally needed, log a fingerprint field. Raw graph ids are allowed only after
  explicit classification as non-sensitive for a dataset.

### Минимальный field profile

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | topology action dictionary |
| `event.outcome` | required on completion/decision | `success`, `failure`, `unknown` |
| `trace.id` | required | command/pipeline run correlation |
| `event.dataset` | required | pipeline dataset |
| `service.type` | recommended | usually `planner`, `matcher`, `resolver`, or `topology` command component |
| `nexus.subsystem` | required | `topology` |
| `nexus.topology.pipeline_dataset` | recommended | dataset being processed by current command |
| `nexus.topology.dataset` | recommended | topology dataset whose graph/spec is used |
| `nexus.topology.side` | recommended | `source` / `target` |
| `nexus.topology.activation.sources` | required on activation/bootstrap | `match`, `resolve`, `source_validation` |
| `nexus.topology.activation.requires_source`, `nexus.topology.activation.requires_target` | required on bootstrap | booleans |
| `nexus.topology.activation.skipped_reason` | required on skip | `command_not_supported`, `checkpoint_before_topology_consumer`, `capability_disabled`, ... |
| `nexus.topology.source.mode`, `nexus.topology.target.mode` | recommended on spec/runtime summary | currently `path_columns` or `adjacency_list` |
| `nexus.topology.normalization.version` | required after canonicalizer compile | safe version/fingerprint |
| `nexus.topology.canonicalizer.ops_count` | recommended | op count only |
| `nexus.topology.nodes_count`, `nexus.topology.roots_count`, `nexus.topology.max_depth` | required on build completion | aggregate graph shape |
| `nexus.topology.readiness.ready`, `nexus.topology.readiness.decision`, `nexus.topology.readiness.reason` | required on readiness | readiness/freshness outcome |
| `nexus.topology.freshness.present`, `nexus.topology.freshness.age_seconds`, `nexus.topology.freshness.max_age_seconds` | recommended on readiness | freshness policy facts |
| `nexus.topology.source.nodes_count`, `nexus.topology.target.membership_count` | required on source validation | source/target counts |
| `nexus.topology.source.anchored_count`, `nexus.topology.source.dropped_count` | required on source validation | anchoring summary |
| `nexus.topology.source.dropped_by_reason.*` | recommended | counts by `missing_parent`, `unanchored_subtree`, `cycle` |
| `nexus.topology.path.depth`, `nexus.topology.path.fingerprint` | optional debug/consumer events | no raw path segments |
| `nexus.topology.node.id_fingerprint`, `nexus.topology.parent.id_fingerprint` | optional debug events | no raw ids |
| `nexus.topology.comparison.mode`, `nexus.topology.comparison.reason` | required on consumer comparison | topology comparison mode/reason |
| `nexus.topology.comparison.candidates_count`, `nexus.topology.comparison.matched_count` | required on consumer comparison | aggregate counts only |
| `nexus.topology.comparison.ambiguous` | recommended | boolean |
| `nexus.topology.comparison.ladder` | optional | list of mode names from policy |
| `nexus.diagnostic.code`, `error.code`, `error.message` | required on failures | topology catalog codes |

### Detail policy

- `INFO` — bootstrap start/completion, spec/runtime topology summary, readiness, build completion,
  source validation completion.
- `DEBUG` — bootstrap skipped, graph build diagnostics, source row filtered, topology consumer
  comparison summary.
- `WARNING` — optional degraded topology: stale/empty optional target topology, source unanchored with
  warning policy, ambiguous topology with pending/skip policy when operator attention is useful.
- `ERROR` — hard topology activation/config failure, required target topology not ready, source
  unanchored hard error, topology hard policy in match/resolve.
- `TRACE` — per-node/per-path/per-comparison rung details, sampled or disabled by default.

### Что не логировать

- Raw node ids, parent ids, synthetic node ids, payload target ids.
- Raw source path segments, canonical names, labels, organization names.
- Full `TopologyComparisonResult.evidence`.
- Full candidate id lists or matched candidate id lists.
- Cache rows, source adjacency rows, Polars frames.
- Raw `details` from hard-error topology policy if it contains `source_segments` or `candidate_ids`.

### Что уже важно учесть при миграции

- `StructlogTopologyEventSink` can become the normalization point: map dotted topology event names to
  canonical `event.action` and prefix payload keys into `nexus.topology.*`.
- `TraceToSink` currently emits raw `node_id`, `parent_id`, `canonical_name`, `canonical_segments`,
  `synthetic_node_id`. These must be fingerprinted or reduced before ECS migration.
- `ResolveCore._apply_topology_policy()` currently embeds raw `source_segments` and `candidate_ids`
  into an error message. ECS migration should split this into safe counts/fingerprints and avoid raw
  details in `error.message`.
- `TopologyBootstrapStep` already emits report context. Logging should mirror the same safe aggregate
  shape, not duplicate raw artifacts.
- Source topology filtering currently has no log call-site; target taxonomy reserves
  `topology-source-row-filtered` for row-level diagnostics if needed.

---
