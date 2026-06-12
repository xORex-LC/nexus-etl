# Zone 10: Apply Execution / Target Write Lifecycle

Десятая зона описывает execution-часть `import apply` после того, как `plan.json` уже прочитан и
валидирован:

- **Apply layer**: consumption `PlanItem[]`, per-item outcome, итоговый summary apply-цикла.
- **Target write layer**: фактическая запись в target через `RequestExecutorProtocol` /
  `TargetGateway`, включая fault classification, retry и нормализованный `ExecutionResult`.

Это уже **не** command-level outcome (`apply-failed`) и **не** planning taxonomy (`resolve` / `plan`).
Зона отвечает на вопрос: **как именно выполнялся apply и что происходило на границе с target**.

### Границы зоны

- `apply-failed`, `identity-init-failed` остаются в command-specific delivery lifecycle.
- `plan-written`, `plan-build-*`, `resolve-*` остаются в зоне 9.
- `cache refresh` / paged target read остаются в cache/state-store taxonomy.
- `identity sync` и `secret retention` после успешного apply не должны размывать target-write
  taxonomy: их лучше документировать отдельными зонами identity/vault, если появится отдельная
  observability-потребность.
- Raw request payload, raw response payload, raw `target_id`, auth headers и secret values
  не логируются.

### Реальная модель, на которую опираемся

| Code model | Logging meaning |
|---|---|
| `ImportApplyService.apply_plan()` | `apply-started`, `apply-completed` |
| `ApplyItemOutcome` | `apply-item`, `nexus.apply.status`, `nexus.apply.op` |
| `PlanItem.record_ref` | `nexus.record.id`, `nexus.record.line_no` |
| `PlanItem.op` | `nexus.apply.op` |
| `PlanItem.target_id` | `nexus.apply.target_id_fingerprint` |
| `ApplySummary` | `nexus.apply.items_total`, `nexus.apply.created`, `nexus.apply.updated`, `nexus.apply.failed`, `nexus.apply.skipped`, `nexus.apply.rows_with_warnings` |
| `RequestSpec.operation_alias` | `nexus.target.operation.alias` |
| compiled request / provider transport metadata | `http.request.method`, `url.path`, `nexus.target.transport` |
| `ExecutionResult.answer_code` | `http.response.status_code` or `nexus.target.answer_code` |
| `ExecutionResult.response_format` | `nexus.target.response.format` |
| `ExecutionResult.error_code` | `error.code` |
| `ExecutionResult.error_reason` | `nexus.target.error_reason` |
| `TargetGateway.get_stats()` | `nexus.target.stats.requests_total`, `nexus.target.stats.retries_total`, `nexus.target.stats.failures_total` |
| `NormalizedFault.fault_kind` | `nexus.target.fault_kind` |
| `ResolvedRetryAction.directive` | `nexus.target.retry.directive` |
| `ResolvedRetryAction.mutation` | `nexus.target.retry.mutation` |
| `TargetRetryEngine.max_retries` | `nexus.target.retry.max_attempts` |

### Canonical taxonomy для Apply layer

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `apply-started` | INFO milestone | `info` | — | `event.action`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=apply`, `file.path`, `nexus.apply.items_total`, `nexus.apply.max_actions`, `nexus.apply.stop_on_first_error`, `nexus.apply.dry_run` | before `ImportApplyService.apply_plan()` consumes plan items |
| `apply-item` | DEBUG decision | `debug` / `warning` / `error` | `success` / `unknown` / `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.apply.op`, `nexus.apply.status`, `nexus.record.line_no`, `nexus.apply.target_id_fingerprint`, `error.code` | per-item telemetry sink outcome |
| `apply-completed` | INFO milestone | `info` / `error` | `success` / `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=apply`, `nexus.apply.items_total`, `nexus.apply.created`, `nexus.apply.updated`, `nexus.apply.failed`, `nexus.apply.skipped`, `nexus.apply.rows_with_warnings`, `nexus.apply.fatal_error`, `nexus.target.stats.retries_total` | after apply summary is built |

### Canonical taxonomy для Target write layer

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `target-write-started` | TRACE/DEBUG diagnostic | `debug` | — | `event.action`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.subsystem=target`, `nexus.target.operation.alias`, `nexus.apply.op`, `nexus.target.transport`, `http.request.method`, `url.path`, `nexus.target.request.payload_fields_count`, `http.request.body.bytes` | before `executor.execute(request_spec)` |
| `target-request-failed` | DEBUG/WARNING diagnostic | `warning` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset` | `nexus.subsystem=target`, `nexus.target.operation.alias`, `nexus.target.fault_kind`, `http.response.status_code` or `nexus.target.answer_code`, `nexus.target.error_reason`, `nexus.target.retry.directive`, `nexus.target.response.format`, `nexus.target.response.preview_present`, `nexus.target.response.preview` | one failed target attempt before retry or final escalation |
| `retry-attempt` | DEBUG decision | `debug` | — | `event.action`, `trace.id`, `event.dataset` | `nexus.subsystem=target`, `nexus.target.operation.alias`, `nexus.target.fault_kind`, `nexus.target.retry.attempt`, `nexus.target.retry.max_attempts`, `nexus.target.retry.delay_ms`, `nexus.target.retry.directive`, `nexus.target.retry.mutation` | retry scheduled by `TargetGateway` |
| `target-write-completed` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id` | `nexus.subsystem=target`, `nexus.target.operation.alias`, `http.request.method`, `url.path`, `http.response.status_code` or `nexus.target.answer_code`, `nexus.target.response.format`, `nexus.target.response.fields_count`, `nexus.target.response.items_count`, `http.response.body.bytes`, `event.duration`, `nexus.target.retry.attempt` | successful normalized `ExecutionResult` returned from gateway |
| `target-write-failed` | WARNING/ERROR decision | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `nexus.record.id`, `error.code`, `error.message` | `nexus.subsystem=target`, `nexus.target.operation.alias`, `http.request.method`, `url.path`, `nexus.target.fault_kind`, `http.response.status_code` or `nexus.target.answer_code`, `nexus.target.error_reason`, `nexus.target.response.format`, `nexus.target.response.preview_present`, `nexus.target.response.preview`, `nexus.target.retry.attempt`, `nexus.target.retry.max_attempts`, `event.duration` | final failed normalized `ExecutionResult` after retries exhausted or retry not allowed |

### Нормализация и анти-дублирование

- `apply-completed` описывает **весь apply run**, а не один target request. Не смешивать его с
  `target-write-completed`.
- `apply-item` описывает business outcome plan-item после прохождения через adapter, target executor
  и post-success hooks. Это не транспортная attempt-level телеметрия.
- `target-request-failed` можно эмитить несколько раз на один `apply-item`, если gateway делает retry.
  `target-write-failed` должен быть максимум один раз на финальный failure.
- Если ответ target содержит HTTP status code, использовать ECS `http.response.status_code`.
  `nexus.target.answer_code` нужен только для non-HTTP или string-coded transport answers.
- Retry scheduling выражать через один `retry-attempt` action; не плодить `target-retry-after`,
  `target-retry-backoff`, `target-retry-mutation-applied`.
- `apply-failed` в command zone остаётся semantic failure всей команды; он не должен дублировать
  каждый `target-write-failed`.
- Тип запроса нужно различать на двух осях: business operation через `nexus.target.operation.alias`
  и transport request через `http.request.method` / `url.path`.
- Из request/response body в baseline logs попадает не содержимое целиком, а только безопасная
  metadata: size, field count, items count и, для failure-path, опциональный sanitized preview.

### Минимальный field profile

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | apply/target action dictionary |
| `event.outcome` | required on completion/failure | `apply-item` uses `success` / `unknown` / `failure` |
| `trace.id` | required | correlation ключ одного apply run |
| `event.dataset` | required | apply всегда dataset-scoped через plan meta |
| `service.type` | required on apply summary/milestones | обычно `applier` |
| `nexus.subsystem` | recommended | `apply` или `target` |
| `nexus.record.id` | required for per-item/per-write events | opaque row id from plan item |
| `nexus.record.line_no` | recommended for per-item events | if source line number exists |
| `nexus.apply.op` | required for per-item events | `create` / `update` |
| `nexus.apply.status` | recommended for `apply-item` | `ok`, `warning`, `failed` |
| `nexus.apply.target_id_fingerprint` | recommended | safe fingerprint only; raw target id forbidden |
| `nexus.apply.items_total`, `nexus.apply.created`, `nexus.apply.updated`, `nexus.apply.failed`, `nexus.apply.skipped` | required on `apply-completed` | summary counters |
| `nexus.apply.rows_with_warnings` | recommended on `apply-completed` | currently 0 by contract, but taxonomy reserves it |
| `nexus.apply.fatal_error` | recommended on `apply-completed` | stop-policy relevant summary bit |
| `file.path` | recommended on `apply-started` | consumed `plan.json` path |
| `nexus.target.operation.alias` | required for target-write events | canonical RequestSpec alias |
| `nexus.target.transport` | recommended on target-write start | `http`, other transport kinds |
| `http.request.method` | recommended for HTTP target events | transport request type |
| `url.path` | recommended for HTTP target events | path/path-template without sensitive query data |
| `http.request.body.bytes` | optional | request body size if transport can provide it |
| `nexus.target.request.payload_fields_count` | recommended on write start | top-level object field count |
| `nexus.target.request.payload_items_count` | optional | list/rows payload size |
| `nexus.target.request.payload_redacted_fields` | optional | number of masked fields in sanitized request |
| `http.response.status_code` | recommended when numeric | HTTP transport path |
| `nexus.target.answer_code` | optional | non-HTTP / string-coded answer |
| `nexus.target.response.format` | recommended on success/final failure | `json`, `text`, `none`, ... |
| `http.response.body.bytes` | optional | response body size if transport can provide it |
| `nexus.target.response.fields_count` | recommended on safe object responses | top-level object field count |
| `nexus.target.response.items_count` | recommended on list/rows responses | item count without logging payload |
| `nexus.target.response.preview_present` | recommended on failure responses | whether a safe preview exists |
| `nexus.target.response.preview` | optional on failure responses | only sanitized + truncated preview, never raw body |
| `nexus.target.fault_kind` | required on failed target events | `AUTH`, `DATA`, `THROTTLE`, `TRANSIENT`, ... |
| `nexus.target.error_reason` | optional | provider/driver-specific normalized reason |
| `nexus.target.retry.attempt`, `nexus.target.retry.max_attempts` | required on retry/final failure | retry progress |
| `nexus.target.retry.directive` | required on retry-path events | `RETRY_BACKOFF`, `RETRY_AFTER`, `FAIL`, `ESCALATE` |
| `nexus.target.retry.delay_ms` | required on `retry-attempt` | delay before next attempt |
| `nexus.target.retry.mutation` | optional | target mutation applied before retry |
| `nexus.target.stats.requests_total`, `nexus.target.stats.retries_total`, `nexus.target.stats.failures_total` | recommended on `apply-completed` | runtime totals for the whole apply run |
| `event.duration` | recommended on target final events | duration of one write operation / full apply run when available |
| `error.code`, `error.message` | required on `target-write-failed` and failed `apply-item` | `error.type` optional for normalized non-exception failures |

### Detail policy для Apply / Target

- `INFO` — `apply-started`, `apply-completed`.
- `DEBUG` — `apply-item` success path, `target-write-started`, `target-write-completed`, `retry-attempt`.
- `WARNING` — transient or degraded attempt-level target failures that are retried; `apply-item`
  with non-fatal warning outcome.
- `ERROR` — final `target-write-failed`, failed `apply-item`, command-level `apply-failed`.
- `TRACE` — допустим только для extremely chatty request/response seams, если понадобится отдельный
  investigation mode; по умолчанию текущая зона может жить на `DEBUG` как нижней детализации.

### Что не логировать

- Raw `PlanItem.desired_state`, `PlanItem.changes`, request payload, response payload целиком.
- Raw `target_id`, resolved id, response object ids, auth headers, bearer/basic credentials.
- `source_ref` values целиком; максимум count/fingerprint если позже потребуется.
- Full `error_details.response_payload` как самостоятельный лог-поле вне redaction policy.
- Vault/secret retention internals в target-write событиях.
- `url.full`, если в нём есть чувствительный query string или встроенные credentials.

### Что именно допустимо логировать из request/response

- Для request:
  `http.request.method`, `url.path`, `http.request.body.bytes`,
  `nexus.target.request.payload_fields_count`, `nexus.target.request.payload_items_count`.
- Для response success-path:
  `http.response.status_code`, `nexus.target.response.format`,
  `http.response.body.bytes`, `nexus.target.response.fields_count`,
  `nexus.target.response.items_count`.
- Для response failure-path:
  всё выше плюс `nexus.target.response.preview_present` и, опционально,
  `nexus.target.response.preview`, если preview уже прошёл redaction и truncate policy.
- Preview должен быть **исключением для расследования**, а не базовым payload dump.

### Что уже важно учесть при миграции текущего кода

- `LoggingApplyTelemetrySink` сейчас логирует `target_id` в открытом виде и использует общий action
  `apply-item` только через `message`. При ECS-migration это нужно перевести в
  `nexus.apply.target_id_fingerprint` + явный `event.action`.
- `LoggingApplyTelemetrySink.on_summary()` уже содержит правильный слой агрегации для
  `apply-completed`, но ему нужны canonical summary fields вместо ad-hoc `created/updated/failed`.
- `TargetSafeLogger.log_response_error()` сейчас логирует attempt-level warning. Это хороший source
  для `target-request-failed`; в него нужно добавить canonical `fault_kind`, retry context и safe
  transport metadata.
- `TargetGateway` уже знает `retries_used`, `max_retries`, `retry_action.directive`, `mutation`,
  значит именно он должен быть owner для `retry-attempt` и финального `target-write-*`.
- Не нужно пытаться засовывать target runtime totals в каждый per-item log. Их место — в
  `apply-completed` summary.

---
