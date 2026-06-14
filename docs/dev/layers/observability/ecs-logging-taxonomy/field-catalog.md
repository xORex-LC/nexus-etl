# Field Catalog

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

### `http.*` / `url.*`
| Поле | Когда | Описание |
|---|---|---|
| `http.request.method` | HTTP target/cache/check events | HTTP method: `GET`, `POST`, `PUT`, `PATCH`, ... |
| `http.request.body.bytes` | когда transport умеет оценить размер request body | Размер request body в байтах; без содержимого |
| `http.response.status_code` | HTTP target/cache/check completion/failure events | Числовой HTTP status code |
| `http.response.body.bytes` | когда transport умеет оценить размер response body | Размер response body в байтах; без содержимого |
| `url.full` | endpoint-level runtime/check events | Полный endpoint URL, если он не содержит секретов и query-sensitive данных |
| `url.path` | request/operation events | Path или path-template без чувствительных query/ids |

### `error.*` (только ERROR/CRITICAL) — **два источника**
`error.*` собирается ИЛИ из ручных kwargs на call-site (`error_type`/`error`/`diag_code` — так уже
пишет, напр., [orchestrator.py:494](../../../../../connector/delivery/cli/runtime/orchestrator.py)),
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
| `nexus.source.type` | source ingestion events | Runtime source type: `file`, `db`, `api`; current supported ingest path is `file` |
| `nexus.source.format` | source ingestion events | Physical source format: `csv`, ... |
| `nexus.source.location` | source resolution events | Logical `source.location` from `SourceSpec`, not per-record |
| `nexus.source.path_kind` | source resolution events | `relative`, `absolute`, `logical`, `unknown` |
| `nexus.source.encoding` | CSV source events | Encoding used to open CSV |
| `nexus.source.delimiter` | CSV source events | Single-character CSV delimiter, escaped if needed |
| `nexus.source.has_header` | CSV source events | Boolean source config |
| `nexus.source.header.present` | header/contract events | Boolean observed header state |
| `nexus.source.columns.count` | header/contract/read summary | Observed physical or synthetic column count |
| `nexus.source.columns.fingerprint` | header/contract/read summary | Safe hash of ordered column names; do not log raw header list by default |
| `nexus.source.declared_fields_count` | source contract events | Number of fields declared in `SourceSpec.fields` |
| `nexus.source.missing_columns_count` | source contract events | Count of declared fields missing in observed header/columns |
| `nexus.source.extra_columns_count` | source contract events | Count of observed header/columns absent from declared fields |
| `nexus.source.records_total` | source read completion/failure | Records yielded before completion/failure |
| `nexus.source.blank_rows_skipped` | source read summary | Blank CSV rows skipped by reader |
| `nexus.source.rows_with_nulls` | source read summary | Rows containing at least one null-normalized value |
| `nexus.source.null_values_total` | source read summary | Total values normalized to null by `parse_null()` |
| `nexus.source.record.fields_count` | source per-record/sampled events | Number of fields in one `SourceRecord.values` |
| `nexus.source.record.null_fields_count` | source per-record/sampled events | Number of null fields in one `SourceRecord.values` |
| `nexus.source.record.empty_fields_count` | source per-record/sampled events | Number of empty raw fields if tracked before null normalization |
| `nexus.source.failure.line_no` | source failure events | CSV line where structural failure happened, when known |
| `nexus.source.failure.expected_columns` | source column-count failures | Expected column count |
| `nexus.source.failure.actual_columns` | source column-count failures | Actual column count |
| `nexus.source.failure.layer` | source failure events | `dsl`, `resolver`, `reader`, `extractor` |
| `nexus.source.reason` | source failures/degraded events | Stable reason: `file_not_found`, `missing_header`, `column_count_mismatch`, `decode_error`, ... |
| `nexus.diagnostic.code` | diagnostics bridge events | Domain diagnostic code when keeping it separate from normalized `error.code` |
| `nexus.mapping.rules_total` | mapping record summary | Количество compiled mapping rules |
| `nexus.mapping.rules_applied` | mapping record summary | Количество rules that assigned at least one target |
| `nexus.mapping.rules_failed` | mapping record/rule failure events | Количество rules that emitted mapping-local issues |
| `nexus.mapping.fields_touched_count` | mapping record summary / validation | Количество output fields touched by mapping rules |
| `nexus.mapping.targets_assigned_count` | mapping record/rule summary | Количество target assignments performed |
| `nexus.mapping.warnings_count` | mapping record summary | Mapping-local warning count for one record |
| `nexus.mapping.errors_count` | mapping record summary | Mapping-local error count for one record |
| `nexus.mapping.source_fields_count` | mapping spec/runtime summary | Количество declared source columns in `MappingSpec.source_columns` |
| `nexus.mapping.source.fields_count` | mapping rule events | Number of source fields read by one rule |
| `nexus.mapping.source.missing_count` | mapping record/rule failure events | Count of missing source fields for a record/rule |
| `nexus.mapping.source.field` | mapping rule events | Source field name only; value forbidden |
| `nexus.mapping.target.field` | mapping rule/target events | Target field name only; value forbidden |
| `nexus.mapping.rule.index` | mapping rule events | Rule ordinal inside compiled mapping rules |
| `nexus.mapping.rule.ops_count` | mapping rule events | Number of operations in the rule chain |
| `nexus.mapping.rule.required` | mapping rule events | Mapping rule `required` flag |
| `nexus.mapping.rule.on_error` | mapping rule events | Rule error policy: `error` or `warn` |
| `nexus.mapping.secret_candidates_count` | mapping record summary | Count of fields marked as secret candidates; no secret values |
| `nexus.mapping.meta.rules_total` | mapping meta events | Number of compiled meta rules |
| `nexus.mapping.meta.rules_applied` | mapping record summary | Number of meta rules that produced non-null meta values |
| `nexus.mapping.meta.rules_failed` | mapping record/rule failure events | Number of meta rules with issues |
| `nexus.mapping.meta.path` | mapping meta rule events | Meta target path only; value forbidden |
| `nexus.mapping.validation.scope` | mapping schema/sink validation events | `mapping_schema`, `sink_full_row`, future `sink_touched_fields` |
| `nexus.mapping.validation.fields_checked_count` | mapping validation events | Number of schema/sink fields checked |
| `nexus.mapping.validation.issues_count` | mapping validation failure events | Total mapping schema/sink validation issues |
| `nexus.mapping.validation.required_missing_count` | mapping validation failure events | Count of required/nullability failures |
| `nexus.mapping.validation.type_invalid_count` | mapping validation failure events | Count of type mismatch failures when type checks are enabled |
| `nexus.mapping.skip.reason` | mapping skipped events | `upstream_failed` or future policy reason |
| `nexus.mapping.failure.reason` | mapping failed/degraded events | `missing_source_column`, `required_field_missing`, `dsl_op_failed`, `sink_required_missing`, `boundary_error`, ... |
| `nexus.mapping.upstream.errors_count` | mapping upstream skip events | Count of upstream errors carried from Extract |
| `nexus.mapping.upstream.warnings_count` | mapping upstream skip events | Count of upstream warnings carried from Extract |
| `nexus.normalize.rules_total` | normalize record summary | Количество compiled normalize rules for current dataset/spec |
| `nexus.normalize.rules_applied` | normalize record summary | Количество rules with non-empty op chain applied to the row |
| `nexus.normalize.rules_skipped` | normalize record/rule events | Количество skipped rules; reason in `nexus.normalize.skip.reason` |
| `nexus.normalize.rules_failed` | normalize record/rule failure events | Количество rules that emitted normalize-local issues |
| `nexus.normalize.fields_touched_count` | normalize record summary / validation | Количество fields touched by normalize rules |
| `nexus.normalize.changed_fields_count` | normalize record summary | Количество fields whose normalized value differs from input; no values |
| `nexus.normalize.null_fields_count` | normalize record summary | Количество null fields after normalize, if computed |
| `nexus.normalize.warnings_count` | normalize record summary | Normalize-local warning count for one record |
| `nexus.normalize.errors_count` | normalize record summary | Normalize-local error count for one record |
| `nexus.normalize.rule.field` | normalize rule events | Field name affected by normalize rule; value forbidden |
| `nexus.normalize.rule.index` | normalize rule events | Rule ordinal inside compiled normalize rules |
| `nexus.normalize.rule.ops_count` | normalize rule events | Number of operations in the rule chain |
| `nexus.normalize.rule.on_error` | normalize rule events | Rule error policy: `error` or `warn` |
| `nexus.normalize.value.changed` | normalize rule events | Boolean value-change signal without before/after values |
| `nexus.normalize.validation.scope` | normalize validation events | `touched_fields` or `full_row` from build options |
| `nexus.normalize.validation.fields_checked_count` | normalize validation events | Number of sink fields checked |
| `nexus.normalize.validation.issues_count` | normalize validation failure events | Total sink validation issues |
| `nexus.normalize.validation.required_missing_count` | normalize validation failure events | Count of required/nullability failures |
| `nexus.normalize.validation.type_invalid_count` | normalize validation failure events | Count of type mismatch failures |
| `nexus.normalize.skip.reason` | normalize skipped events | `upstream_failed`, `no_ops`, future policy reason |
| `nexus.normalize.failure.reason` | normalize failed/degraded events | `dsl_op_failed`, `sink_required_missing`, `sink_type_invalid`, `boundary_error`, ... |
| `nexus.normalize.upstream.errors_count` | normalize upstream skip events | Count of upstream errors carried into Normalize |
| `nexus.normalize.upstream.warnings_count` | normalize upstream skip events | Count of upstream warnings carried into Normalize |
| `nexus.topology.pipeline_dataset` | topology activation/bootstrap events | Dataset currently processed by command |
| `nexus.topology.dataset` | topology runtime events | Dataset that owns topology spec/snapshot |
| `nexus.topology.side` | topology build/readiness events | `source` or `target` |
| `nexus.topology.consumer` | topology comparison events | Consumer path: `match`, `resolve`, `source_validation` |
| `nexus.topology.activation.sources` | topology activation/bootstrap events | Activation sources: `match`, `resolve`, `source_validation` |
| `nexus.topology.activation.capability_enabled` | topology activation events | Whether dataset topology capability is enabled |
| `nexus.topology.activation.requires_source` | topology activation/bootstrap events | Whether source topology validation is required |
| `nexus.topology.activation.requires_target` | topology activation/bootstrap events | Whether target topology snapshot is required |
| `nexus.topology.activation.target_failure_is_hard` | topology activation events | Whether target readiness failure short-circuits command |
| `nexus.topology.activation.skipped_reason` | topology skip events | `command_not_supported`, `checkpoint_before_topology_consumer`, `capability_disabled`, ... |
| `nexus.topology.activation.error` | topology activation failure events | Safe activation error summary |
| `nexus.topology.source.mode` | topology spec/runtime summary | `path_columns` or `adjacency_list` |
| `nexus.topology.source.path_columns_count` | topology spec/runtime summary | Number of source path columns; names optional elsewhere |
| `nexus.topology.source.node_id_field` | source validation/filter events | Source node id field name only |
| `nexus.topology.source.node_id_fingerprint` | source validation/filter events | Safe fingerprint of source node id |
| `nexus.topology.source.nodes_count` | source validation summary | Number of source adjacency nodes |
| `nexus.topology.source.anchored_count` | source validation summary | Number of source nodes anchored to target/root |
| `nexus.topology.source.dropped_count` | source validation/filter summary | Number of dropped/unanchored source nodes |
| `nexus.topology.source.drop.reason` | source filter events | `missing_parent`, `unanchored_subtree`, `cycle` |
| `nexus.topology.source.dropped_by_reason.*` | source validation summary | Count per drop reason |
| `nexus.topology.source.on_unanchored` | source validation/filter events | Policy: `skip`, `warn`, `hard_error` |
| `nexus.topology.target.mode` | topology spec/runtime summary | Currently `adjacency_list` |
| `nexus.topology.target.node_id_field` | target build start events | Target node id field name only |
| `nexus.topology.target.parent_id_field` | target build start events | Target parent id field name only |
| `nexus.topology.target.label_field` | target build start events | Target label field name only |
| `nexus.topology.target.membership_count` | source validation summary | Count of target membership ids read for anchoring |
| `nexus.topology.normalization.version` | topology canonicalizer/build events | Safe normalization version/fingerprint |
| `nexus.topology.canonicalizer.ops_count` | topology canonicalizer events | Number of canonicalization ops |
| `nexus.topology.nodes_count` | topology build/readiness events | Number of nodes in topology snapshot |
| `nexus.topology.roots_count` | topology build completion events | Number of roots in topology snapshot |
| `nexus.topology.max_depth` | topology build completion events | Maximum computed depth in topology snapshot |
| `nexus.topology.built_sides` | topology bootstrap completion events | Built artifacts: `source`, `source_validation`, `target` |
| `nexus.topology.bootstrap.status` | topology bootstrap completion events | `ok`, `warn`, `error`, `skipped` |
| `nexus.topology.errors_count` | topology bootstrap/source validation summary | Count of topology diagnostics with error severity |
| `nexus.topology.warnings_count` | topology bootstrap/source validation summary | Count of topology diagnostics with warning severity |
| `nexus.topology.cache_snapshot_revision` | topology readiness/build metadata | Safe cache revision/run id if non-sensitive |
| `nexus.topology.readiness.ready` | topology readiness events | Boolean readiness result |
| `nexus.topology.readiness.decision` | topology readiness events | `ready`, `required_failure`, `optional_skip` |
| `nexus.topology.readiness.reason` | topology readiness events | `ready`, `snapshot_empty`, `max_age_exceeded`, ... |
| `nexus.topology.freshness.present` | topology readiness events | Whether freshness metadata exists |
| `nexus.topology.freshness.age_seconds` | topology readiness events | Target snapshot age in seconds |
| `nexus.topology.freshness.max_age_seconds` | topology readiness events | Policy threshold |
| `nexus.topology.graph.algorithm` | topology graph diagnostics | Cycle/topological algorithm name, e.g. `graphlib` |
| `nexus.topology.graph.has_cycle` | topology graph diagnostics | Boolean cycle check result |
| `nexus.topology.node.id_fingerprint` | topology graph diagnostics | Safe fingerprint of topology node id |
| `nexus.topology.node.synthetic_id_fingerprint` | source path graph diagnostics | Safe fingerprint of generated source node id |
| `nexus.topology.node.canonical_name_fingerprint` | topology graph diagnostics | Safe fingerprint of canonical name/label |
| `nexus.topology.parent.id_fingerprint` | topology graph diagnostics | Safe fingerprint of parent topology node id |
| `nexus.topology.path.depth` | topology path/comparison events | Number of canonical path segments |
| `nexus.topology.path.fingerprint` | topology path/comparison events | Safe fingerprint of canonical path; no segments |
| `nexus.topology.comparison.mode` | topology consumer events | `exact_canonical_path`, `exact_leaf_parent_chain`, `exact_leaf_root_depth`, `ambiguous`, `no_match` |
| `nexus.topology.comparison.reason` | topology consumer events | Safe reason from comparison core |
| `nexus.topology.comparison.candidates_count` | topology consumer events | Number of target candidates considered |
| `nexus.topology.comparison.matched_count` | topology consumer events | Number of candidates matched by topology |
| `nexus.topology.comparison.ambiguous` | topology consumer events | Boolean ambiguity result |
| `nexus.topology.comparison.ladder` | topology consumer events | Ordered comparison mode names from policy |
| `nexus.topology.comparison.rungs_evaluated` | topology consumer events | Number of ladder rungs evaluated |
| `nexus.topology.failure.reason` | topology failure events | Stable failure reason |
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
| `nexus.apply.op` | apply item events | `create`, `update` |
| `nexus.apply.status` | apply item events | `ok`, `warning`, `failed` |
| `nexus.apply.target_id_fingerprint` | apply item events | Safe fingerprint target id during apply; raw target id forbidden |
| `nexus.apply.items_total` | apply summary | Количество реально обработанных plan items |
| `nexus.apply.created` | apply summary | Количество successful create actions |
| `nexus.apply.updated` | apply summary | Количество successful update actions |
| `nexus.apply.failed` | apply summary | Количество failed apply items |
| `nexus.apply.skipped` | apply summary | Количество skipped items/rows inherited from plan summary or apply policy |
| `nexus.apply.rows_with_warnings` | apply summary | Количество rows с warning outcome |
| `nexus.apply.fatal_error` | apply summary | Boolean summary bit: был ли fatal error по stop policy |
| `nexus.apply.max_actions` | apply start/summary | Runtime cap for processed items |
| `nexus.apply.stop_on_first_error` | apply start/summary | Boolean stop policy at use-case level |
| `nexus.apply.dry_run` | apply start/summary | Boolean dry-run mode |
| `nexus.vault.runtime.mode` | vault runtime decision events | Normalized runtime mode: `auto`, `on`, `off` |
| `nexus.vault.runtime.requested_vault` | vault runtime decision events | Boolean intent to use vault path after runtime mode evaluation |
| `nexus.vault.runtime.requires_vault` | vault runtime decision events | Boolean: dataset/plan actually requires secret path |
| `nexus.vault.runtime.explicit_mode` | vault runtime decision events | Boolean: mode was explicitly passed by operator |
| `nexus.vault.runtime.reason` | vault runtime decision events | Stable reason code from runtime mode policy |
| `nexus.vault.rollout.mode` | vault rollout decision events | `off`, `staging_dry_run`, `canary`, `full` |
| `nexus.vault.rollout.enabled` | vault rollout decision events | Boolean: vault path enabled after rollout gate |
| `nexus.vault.rollout.startup_guard_required` | vault rollout decision events | Boolean: startup guard must run |
| `nexus.vault.rollout.force_dry_run` | vault rollout decision events | Boolean: rollout policy forced dry-run mode |
| `nexus.vault.rollout.canary_bucket` | vault rollout decision events | Deterministic canary bucket `[0..99]` when applicable |
| `nexus.vault.rollout.canary_selected` | vault rollout decision events | Boolean selection result for canary rollout |
| `nexus.vault.rollout.reason` | vault rollout decision events | Stable reason code from rollout policy |
| `nexus.vault.startup.storage_mode` | vault startup events | `writable` or `readonly` storage mode |
| `nexus.vault.startup.probe_present` | vault startup events | Boolean: startup probe existed before guard ran |
| `nexus.vault.startup.probe_created` | vault startup events | Boolean: guard had to auto-create probe |
| `nexus.vault.startup.strict_readonly_policy` | vault startup events | Boolean strict-policy flag |
| `nexus.vault.startup.reason` | vault startup failure events | Stable startup failure reason without sensitive details |
| `nexus.vault.key.version` | vault startup/read/write events | Active wrap/master key version if safe to expose |
| `nexus.vault.dek.version` | vault startup/read/write events | Active DEK version if safe to expose |
| `nexus.secret.field.name` | secret read events | Secret field name only; no plaintext value |
| `nexus.secret.fields_count` | secret write/summary events | Number of secret fields in one store batch |
| `nexus.secret.hit` | secret read events | Boolean: secret record found and hydrated |
| `nexus.secret.reason` | secret read/write events | Safe reason: `not_found`, `locator_context_missing`, `crypto_error`, ... |
| `nexus.secret.locator.version` | secret read/write events | Locator contract version, currently `v1` |
| `nexus.secret.source_ref.fields_count` | secret boundary events | Number of source-ref fields used for locator context |
| `nexus.secret.match_key_fingerprint` | secret read/write events | Safe fingerprint of normalized `match_key` |
| `nexus.secret.run_scope` | secret read/write events | `exact`, `default`, `global_fallback`, `none` |
| `nexus.secret.lifecycle.mode` | secret retention events | `persistent` or `ephemeral` |
| `nexus.secret.lifecycle.delete_on_success` | secret retention events | Boolean cleanup policy |
| `nexus.secret.lifecycle.ttl_seconds` | secret retention events | TTL from normalized lifecycle policy |
| `nexus.secret.retention.deleted` | secret retention summary | Number of deleted secret records |
| `nexus.secret.retention.kept` | secret retention summary | Number of retained secret records |
| `nexus.secret.retention.skipped` | secret retention summary | Number of skipped cleanup attempts |
| `nexus.secret.retention.errors` | secret retention summary | Number of cleanup errors |
| `nexus.secret.maintenance.cleanup_expired` | secret maintenance summary | Count returned by cleanup-expired hook |
| `nexus.secret.maintenance.cleanup_orphans` | secret maintenance summary | Count returned by orphan cleanup hook |
| `nexus.secret.maintenance.rewrap_candidates` | secret maintenance summary | Count returned by rewrap-candidates hook |
| `nexus.vault.management.operation` | vault-management events | `init`, `status`, `rotate`, `rewrap` |
| `nexus.vault.management.operation_id` | vault-management mutation events | Internal `vault_mgmt_<uuid>` operation id, distinct from `trace.id` |
| `nexus.vault.management.dry_run` | vault-management events | CLI dry-run mode |
| `nexus.vault.management.force` | vault-management events | CLI force flag skipped confirm step |
| `nexus.vault.management.non_interactive` | vault-management/admin gate events | CLI/admin input mode |
| `nexus.vault.management.verify_requested` | vault-management events | Whether post-verify was requested |
| `nexus.vault.management.verified` | vault status events | Whether status included unseal/startup verify |
| `nexus.vault.management.can_apply` | vault dry-run events | Dry-run applicability decision |
| `nexus.vault.management.initialized` | vault status/dry-run events | Whether unseal metadata exists |
| `nexus.vault.management.active_key_version` | vault-management events | Safe active master key version identifier |
| `nexus.vault.management.key_versions_count` | vault status events | Number of available persisted key versions |
| `nexus.vault.management.dek_total` | vault status/rotate/rewrap events | Number of DEK records |
| `nexus.vault.management.dek_rewrap_required` | vault status/dry-run events | DEK records requiring rewrap to active key |
| `nexus.vault.management.dek_rewrapped_count` | vault rotate/rewrap events | Aggregate count of DEK records rewrapped |
| `nexus.vault.management.rotated_at` | vault init/rotate result events | UTC timestamp returned by lifecycle result |
| `nexus.vault.management.last_rotation_result` | vault status/result events | Last rotation state: `ok`, `failed`, `rotating`, ... |
| `nexus.vault.management.last_rotation_reason` | vault status/result events | Stable safe reason for last rotation state |
| `nexus.vault.management.last_rotation_run_id` | vault status events | Previous management operation id if available |
| `nexus.vault.management.reason` | vault-management failures/degraded decisions | Stable safe reason from domain details |
| `nexus.vault.admin_gate.required` | admin gate events | Boolean: admin password gate enforced by policy |
| `nexus.vault.admin_gate.mode` | admin gate events | `interactive` or `non_interactive` |
| `nexus.vault.admin_gate.reason` | admin gate failure/skip events | Stable safe reason |
| `nexus.vault.admin_gate.hash_source` | admin gate events | `file`, `env`, `none`; never hash value |
| `nexus.vault.admin_gate.hash_file_configured` | admin gate events | Boolean: hash file was configured |
| `nexus.vault.admin_gate.file_mode` | admin gate config failures | Safe POSIX mode string, e.g. `0o600` |
| `nexus.vault.unseal.kdf_algo` | unseal verify/init/rotate events | KDF algorithm, e.g. `argon2id` |
| `nexus.vault.unseal.kdf_time_cost` | unseal verify/init/rotate events | Argon2id time cost without salts |
| `nexus.vault.unseal.kdf_memory_cost_kib` | unseal verify/init/rotate events | Argon2id memory cost without salts |
| `nexus.vault.unseal.kdf_parallelism` | unseal verify/init/rotate events | Argon2id parallelism without salts |
| `nexus.vault.unseal.kdf_hash_len` | unseal verify/init/rotate events | Derived key length metadata |
| `nexus.vault.unseal.hmac_algo` | unseal verify/init/rotate events | HMAC algorithm name, never digest |
| `nexus.target.operation.alias` | target write events | Canonical RequestSpec operation alias |
| `nexus.target.transport` | target runtime/write events | Transport kind: `http`, ... |
| `nexus.target.request.kind` | target request events | `write`, `read`, `check` |
| `nexus.target.request.payload_fields_count` | target request events | Количество top-level полей в request payload object |
| `nexus.target.request.payload_items_count` | target request events | Количество элементов, если payload — list/collection |
| `nexus.target.request.payload_redacted_fields` | target request events | Количество полей, замаскированных redaction policy |
| `nexus.target.answer_code` | target write events | Non-HTTP or string-coded answer code |
| `nexus.target.response.format` | target write events | `json`, `text`, `none`, ... |
| `nexus.target.response.fields_count` | target response events | Количество top-level полей в response object |
| `nexus.target.response.items_count` | target response events | Количество items в response list/rows payload |
| `nexus.target.response.preview` | target failure events only | Sanitized + truncated preview body/response; только если redaction policy разрешает |
| `nexus.target.response.preview_present` | target response/failure events | Boolean: есть ли пригодный safe preview |
| `nexus.target.fault_kind` | target failed/retry events | `AUTH`, `DATA`, `THROTTLE`, `TRANSIENT`, ... |
| `nexus.target.error_reason` | target failed events | Provider/driver-specific normalized reason |
| `nexus.target.retry.attempt` | target retry/final events | Current retry ordinal for this write |
| `nexus.target.retry.max_attempts` | target retry/final events | Configured retry ceiling |
| `nexus.target.retry.directive` | target retry/failure events | `RETRY_BACKOFF`, `RETRY_AFTER`, `FAIL`, `ESCALATE` |
| `nexus.target.retry.delay_ms` | target retry events | Planned delay before next attempt |
| `nexus.target.retry.mutation` | target retry events | Optional retry mutation applied to RequestSpec |
| `nexus.target.stats.requests_total` | apply summary | Total target requests issued during apply run |
| `nexus.target.stats.retries_total` | apply summary | Total retries executed during apply run |
| `nexus.target.stats.failures_total` | apply summary | Total target operations ended in failure during apply run |
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
| Extract / source ingestion | `file.*`, `nexus.source.*`, sparse `nexus.record.source.*` | physical source location, CSV profile, stream counters and structural source failures |
| Map / field projection stage | `nexus.mapping.*` | source field projection, mapping rule execution, target assignment and first schema gate |
| Normalize / data quality stage | `nexus.normalize.*` | runtime rule application, touched fields, type/nullability validation and safe data-quality counters |
| Topology subsystem | `nexus.topology.*` | topology activation, graph build/readiness, source anchoring and match/resolve comparison signal |
| Persistent identity/pending state | `nexus.identity.*`, `nexus.pending.*` | это resolver/apply state, а не refreshable cache |
| Low-level backend/storage | `nexus.storage.*` | SQLite/JSONL operational layer, отдельно от business subsystem |
| External declarative artifacts | `nexus.dsl.*` | YAML/spec lifecycle до runtime execution |
| Match decision state | `nexus.match.*` | typed decision, fuzzy/topology/dedup context; not cache provider telemetry |
| Resolve decision / plan artifact | `nexus.resolve.*`, `nexus.plan.*` | operation decision and plan summary without payload/diff values |
| Vault / secrets runtime | `nexus.vault.runtime.*`, `nexus.vault.rollout.*`, `nexus.vault.startup.*`, `nexus.secret.*` | runtime mode, rollout gate, startup readiness, secret access and cleanup lifecycle |
| Vault management | `nexus.vault.management.*`, `nexus.vault.admin_gate.*`, `nexus.vault.unseal.*` | manual init/status/rotate/rewrap and admin access lifecycle |
| Apply execution / target write | `nexus.apply.*`, `nexus.target.*` | apply item outcomes, target operation metadata, retry/fault context |

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
