# Zone 11: Vault / Secrets Runtime Lifecycle

Одиннадцатая зона описывает runtime-путь секретов в dataset-aware командах
`enrich`, `import plan`, `import apply`:

- **vault control plane**: runtime mode decision, rollout gate, startup guard, readiness of vault path;
- **secret data plane**: write/read lifecycle секретов, post-apply retention и maintenance hooks.

Это **не** зона manual lifecycle-операций `vault-management` и **не** row-level business events
enrich/apply. Она отвечает на вопрос: **включили ли мы vault-path, почему именно так, готов ли он к
работе, и как вёл себя runtime read/write/cleanup секретов**.

### Границы зоны

- `apply-failed`, `plan-build-failed`, `debug-stage-completed` остаются в command lifecycle.
- `enrich-secret-fields-stored` остаётся в enrich taxonomy: это stage-level бизнес-сигнал, что
  enrich собрал и передал secret candidates в store boundary.
- `apply-item`, `apply-completed`, `target-write-*` остаются в apply/target taxonomy.
- `vault-init-*`, `vault-status-*`, `vault-rotate-*`, `vault-rewrap-*`, `admin-gate-*` не входят
  сюда: это [Zone 12](./12-vault-management-lifecycle.md).
- `vault-startup-failed` остаётся общим command/runtime failure event из Zone 1, но его
  детальный field profile для `vault` owner-смысла определяется этой зоной.
- Plaintext secret values, passphrase, master key material, DEK plaintext, ciphertext, raw
  `match_key`, raw `source_ref` и raw locator hash не логируются.

### Реальная модель, на которую опираемся

| Code model | Logging meaning |
|---|---|
| `resolve_vault_runtime_mode()` | `vault-runtime-evaluated`, `nexus.vault.runtime.*` |
| `evaluate_vault_rollout()` | `vault-rollout-evaluated`, `nexus.vault.rollout.*` |
| `ctx.container.sqlite.vault_ready.init()` / `VaultStartupGuard.ensure_ready()` | `vault-startup-completed` / `vault-startup-failed`, `nexus.vault.startup.*` |
| `VaultDomainError.code/details` | `error.code`, `nexus.vault.startup.reason` or `nexus.secret.reason` |
| `SecretVaultWriteService.put_many()` | `secret-written`, `nexus.secret.fields_count`, `nexus.secret.match_key_fingerprint` |
| `SecretVaultReadService.get_secret()` | `secret-read`, `nexus.secret.field.name`, `nexus.secret.hit`, `nexus.secret.run_scope` |
| `VaultRetentionService.on_apply_success()` | `secret-retention-completed`, `nexus.secret.retention.*`, `nexus.secret.lifecycle.*` |
| `VaultRetentionService.run_maintenance()` | `secret-maintenance-completed`, `nexus.secret.maintenance.*` |
| `build_vault_operational_metrics()` | source for optional future summary events; пока primary owner — report/apply context, не обязательный baseline log |

### Canonical taxonomy для vault control plane

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `vault-runtime-evaluated` | INFO/DEBUG decision | `info` | `success`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=vault`, `nexus.vault.runtime.mode`, `nexus.vault.runtime.requested_vault`, `nexus.vault.runtime.requires_vault`, `nexus.vault.runtime.explicit_mode`, `nexus.vault.runtime.reason` | after runtime mode policy is resolved |
| `vault-rollout-evaluated` | INFO/DEBUG decision | `info`/`error` | `success`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=vault`, `nexus.vault.rollout.mode`, `nexus.vault.rollout.enabled`, `nexus.vault.rollout.startup_guard_required`, `nexus.vault.rollout.force_dry_run`, `nexus.vault.rollout.reason`, `nexus.vault.rollout.canary_bucket`, `nexus.vault.rollout.canary_selected` | after rollout gate decision |
| `vault-startup-completed` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=vault`, `nexus.vault.startup.storage_mode`, `nexus.vault.startup.probe_present`, `nexus.vault.startup.probe_created`, `nexus.vault.startup.strict_readonly_policy`, `nexus.vault.key.version`, `nexus.vault.dek.version` | after startup guard passes and vault path is ready |
| `vault-startup-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type`, `error.code`, `error.message` | `nexus.subsystem=vault`, `nexus.vault.startup.storage_mode`, `nexus.vault.startup.reason`, `nexus.vault.startup.probe_present`, `nexus.vault.startup.strict_readonly_policy` | startup guard / key validation failure aborts command |

### Canonical taxonomy для secret data plane

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `secret-written` | DEBUG decision | `debug`/`error` | `success`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=secrets`, `nexus.secret.fields_count`, `nexus.secret.match_key_fingerprint`, `nexus.secret.locator.version`, `nexus.secret.run_scope`, `nexus.vault.key.version`, `nexus.vault.dek.version`, `nexus.storage.database=vault` | after one `put_many()` batch store |
| `secret-read` | DEBUG decision | `debug`/`error` | `success`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=secrets`, `nexus.secret.field.name`, `nexus.secret.hit`, `nexus.secret.reason`, `nexus.secret.match_key_fingerprint`, `nexus.secret.locator.version`, `nexus.secret.run_scope`, `nexus.storage.database=vault` | after one `get_secret()` read attempt |
| `secret-retention-completed` | DEBUG decision | `debug` | `success`/`unknown`/`failure` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=secrets`, `nexus.secret.lifecycle.mode`, `nexus.secret.lifecycle.delete_on_success`, `nexus.secret.lifecycle.ttl_seconds`, `nexus.secret.retention.deleted`, `nexus.secret.retention.kept`, `nexus.secret.retention.skipped`, `nexus.secret.retention.errors` | after post-success retention counters are aggregated |
| `secret-maintenance-completed` | DEBUG decision | `debug` | `success`/`unknown` | `event.action`, `event.outcome`, `trace.id`, `event.dataset`, `service.type` | `nexus.subsystem=secrets`, `nexus.secret.maintenance.cleanup_expired`, `nexus.secret.maintenance.cleanup_orphans`, `nexus.secret.maintenance.rewrap_candidates` | after best-effort runtime maintenance hooks |

### Нормализация и анти-дублирование

- `vault-runtime-evaluated` фиксирует **intent** (`on|off|auto` и факт необходимости секретов).
  `vault-rollout-evaluated` фиксирует **policy gate** поверх этого intent. Это два разных слоя
  решения, их не надо сливать в один action.
- `vault-rollout-evaluated` не должен размножаться на `vault-rollout-full`,
  `vault-rollout-canary-selected`, `vault-rollout-disabled`. Различия выражаются через
  `nexus.vault.rollout.*`.
- `vault-startup-failed` — command-aborting runtime milestone. `secret-read` / `secret-written`
  — data-plane boundary events и не должны маскироваться под startup.
- `enrich-secret-fields-stored` подтверждает, что stage обработал secret candidates. `secret-written`
  подтверждает, что vault write boundary реально завершился на store path.
- `secret-read` с `nexus.secret.hit=false` и понятной причиной `not_found` /
  `locator_context_missing` — это корректный boundary result и не обязан быть `failure`.
  `failure` использовать для storage/decrypt/integrity/config ошибок.
- `secret-retention-completed` не должен превращаться в per-field spam. Для baseline logs лучше
  агрегировать counters хотя бы до item/run summary.
- `provide_runtime_unseal_passphrase()` по умолчанию не должна создавать отдельные telemetry events:
  prompt lifecycle слишком шумный и чувствительный для baseline мониторинга.

### Минимальный field profile

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | из vault/secrets action dictionary |
| `event.outcome` | required on completion/failure | runtime/rollout/startup/read/write/retention must be explicit |
| `trace.id` | required | correlation одного command run |
| `event.dataset` | required for runtime dataset commands | `enrich`, `import-plan`, `import-apply` are dataset-scoped |
| `service.type` | required | `enricher`, `planner`, `applier` |
| `nexus.subsystem` | required | `vault` for control plane, `secrets` for data plane |
| `nexus.vault.runtime.*` | required for runtime mode evaluation | mode/requested/requires/explicit/reason |
| `nexus.vault.rollout.*` | required for rollout evaluation | mode/enabled/startup_guard_required/force_dry_run/reason; canary fields optional |
| `nexus.vault.startup.*` | recommended for startup events | storage/probe/policy state without secret material |
| `nexus.secret.field.name` | recommended for `secret-read` | single field resolved for apply hydration |
| `nexus.secret.fields_count` | recommended for `secret-written` | batch count for `put_many()` |
| `nexus.secret.hit` | required for `secret-read` success-path | boundary found secret or not |
| `nexus.secret.reason` | recommended for read/write failure or miss | `not_found`, `locator_context_missing`, `crypto_error`, ... |
| `nexus.secret.match_key_fingerprint` | recommended | never raw `match_key` |
| `nexus.secret.locator.version` | recommended | current locator contract version |
| `nexus.secret.run_scope` | optional | `exact`, `default`, `global_fallback`, `none` |
| `nexus.secret.lifecycle.*` | required for retention events | mode/delete_on_success/ttl |
| `nexus.secret.retention.*` | required for retention summary | deleted/kept/skipped/errors |
| `nexus.secret.maintenance.*` | required for maintenance summary | cleanup_expired/cleanup_orphans/rewrap_candidates |
| `nexus.storage.backend`, `nexus.storage.database`, `nexus.storage.operation` | recommended on backend failures | especially for repository/storage boundary issues |
| `error.code`, `error.message` | required on failures | `VaultDomainError.code` should map directly to `error.code` |

### Detail policy для Vault / Secrets runtime

- `INFO` — runtime mode/rollout decision and startup completed/failure. Эти события редкие и
  операционно значимые.
- `DEBUG` — secret read/write boundary, retention and maintenance summaries.
- `WARNING` — degraded retention/maintenance outcome, rollout evaluated but command blocked by policy,
  or secret boundary returned suspicious but non-fatal condition.
- `ERROR` — startup guard failure, secret read/write storage or crypto failure, hard rollout refusal
  that aborts command.
- `TRACE` — по умолчанию не нужен. Если когда-нибудь понадобится forensic mode, его лучше вводить
  только для ultra-detailed secret store/read internals без plaintext leakage.

### Что не логировать

- Runtime unseal passphrase, admin password, master key, wrapped DEK, DEK plaintext.
- Plaintext secret values, ciphertext, raw `match_key`, raw `source_ref`, raw locator hash.
- Probe plaintext/payload и полные `VaultProbeRecord` / `VaultSecretRecord`.
- Absolute paths к hash/key files, если они раскрывают sensitive deployment layout; по умолчанию
  достаточно логической роли и безопасной причины ошибки.
- Полные `details` исключений из crypto/storage, если в них потенциально есть sensitive material.

### Что уже легко заполнить при внедрении

- `VaultRuntimeModeDecision.to_context()` already gives full payload for `nexus.vault.runtime.*`.
- `VaultRolloutDecision.to_context()` already gives full payload for `nexus.vault.rollout.*`.
- `VaultDomainError.code` и `details["reason"]` already map to `error.code` and
  `nexus.vault.startup.reason` / `nexus.secret.reason`.
- `SecretVaultWriteService.put_many()` already knows `dataset`, `match_key`, `secrets` batch size,
  `run_id`, locator version and DEK/key versions.
- `SecretVaultReadService.get_secret()` already knows `dataset`, `field`, locator version, normalized
  source-ref presence and effective run-scope semantics.
- `ApplySummary.retention_stats` and `VaultRetentionService.run_maintenance()` already provide
  aggregate counters for `secret-retention-completed` / `secret-maintenance-completed`.

### Что вынесено в vault-management зону

- `vault-init-*`, `vault-status-*`, `vault-rotate-*`, `vault-rewrap-*` — manual lifecycle operations.
- `admin-gate-*` — password gate and manual access control telemetry.
- `vault-unseal-*`, `vault-post-verify-*` для `vault-management status --verify`,
  `init`, `rotate`, `rewrap`.

См. [Zone 12: Vault Management Lifecycle](./12-vault-management-lifecycle.md).

---
