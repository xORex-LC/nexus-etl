# Zone 12: Vault Management Lifecycle

Двенадцатая зона описывает manual lifecycle-операции `vault-management`:

- `vault-management init` — первичная инициализация unseal metadata и startup probe;
- `vault-management status [--verify]` — read-only snapshot состояния vault и optional verify;
- `vault-management rotate` — смена unseal passphrase, создание новой metadata и rewrap DEK;
- `vault-management rewrap` — rewrap DEK текущим active key без смены passphrase;
- admin password gate перед manual операциями.

Это **не** runtime read/write секретов и **не** startup guard dataset-команд. Runtime path остаётся в
[Zone 11](./11-vault-secrets-runtime-lifecycle.md); эта зона отвечает на вопрос: **какая manual
операция была запрошена, прошла ли administrative gate, что изменилось в keyring/DEK metadata и
какой итог получил оператор**.

### Границы зоны

- `vault-runtime-evaluated`, `vault-rollout-evaluated`, `vault-startup-*`, `secret-read`,
  `secret-written`, `secret-retention-*` остаются в Zone 11.
- `run-started` / `run-failed` остаются в Zone 1/2 как общий CLI lifecycle.
- Prompt lifecycle не логируется как отдельная baseline telemetry: фиксируем только безопасный итог
  admin gate или unseal verify.
- Passphrase, admin password, Argon2 salt, HMAC salt/digest, master key material, DEK plaintext,
  wrapped DEK и probe payload не логируются.

### Реальная модель, на которую опираемся

| Code model | Logging meaning |
|---|---|
| `delivery/commands/vault_management.py` handlers | command-specific management lifecycle and CLI options |
| `VaultAdminPasswordGate.verify_manual_access()` | `admin-gate-skipped`, `admin-gate-passed`, `admin-gate-failed` |
| `VaultKeyManagementUseCase.init_keyring()` | `vault-init-started`, `vault-init-completed`, `vault-init-failed` |
| `VaultKeyManagementUseCase.status()` | `vault-status-completed`, `vault-status-failed` |
| `VaultKeyManagementUseCase.verify_unseal()` | `vault-unseal-verified`, `vault-unseal-failed` |
| `VaultKeyManagementUseCase.rotate_and_rewrap()` | `vault-rotate-started`, `vault-rotate-completed`, `vault-rotate-failed` |
| `VaultKeyManagementUseCase.rewrap_all_dek()` | `vault-rewrap-started`, `vault-rewrap-completed`, `vault-rewrap-failed` |
| `VaultKeyManagementStatus` | status fields: initialized, active key version, DEK totals, last rotation metadata |
| `VaultKeyManagementResult` | operation result: operation id, active key version, rewrapped count, rotated timestamp |
| `VaultDomainError.code/details` | `error.code`, `nexus.vault.management.reason`, `nexus.vault.admin_gate.reason` |

### Canonical taxonomy для admin gate

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `admin-gate-skipped` | INFO decision | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `service.type` | `nexus.subsystem=vault`, `nexus.vault.management.operation`, `nexus.vault.admin_gate.required=false`, `nexus.vault.admin_gate.mode`, `nexus.vault.admin_gate.reason=policy_disabled` | admin gate policy disabled manual access check |
| `admin-gate-passed` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `service.type` | `nexus.subsystem=vault`, `nexus.vault.management.operation`, `nexus.vault.admin_gate.required=true`, `nexus.vault.admin_gate.mode`, `nexus.vault.admin_gate.hash_source` | admin password was verified |
| `admin-gate-failed` | INFO milestone | `warning`/`error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `error.code`, `error.message` | `nexus.subsystem=vault`, `nexus.vault.management.operation`, `nexus.vault.admin_gate.required=true`, `nexus.vault.admin_gate.mode`, `nexus.vault.admin_gate.reason`, `nexus.vault.admin_gate.hash_source`, `nexus.vault.admin_gate.file_mode` | admin password config/access check failed |

### Canonical taxonomy для manual operations

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `vault-init-started` | INFO milestone | `info` | — | `event.action`, `trace.id`, `service.type` | `nexus.subsystem=vault`, `nexus.vault.management.operation=init`, `nexus.vault.management.operation_id`, `nexus.vault.management.dry_run`, `nexus.vault.management.verify_requested` | before init checks metadata and creates key version |
| `vault-init-completed` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `service.type` | `nexus.subsystem=vault`, `nexus.vault.management.operation=init`, `nexus.vault.management.operation_id`, `nexus.vault.management.active_key_version`, `nexus.vault.management.rotated_at`, `nexus.vault.unseal.kdf_algo`, `nexus.vault.unseal.hmac_algo` | unseal metadata and post-verify completed |
| `vault-init-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `error.code`, `error.message` | `nexus.subsystem=vault`, `nexus.vault.management.operation=init`, `nexus.vault.management.operation_id`, `nexus.vault.management.reason` | init failed or vault already initialized |
| `vault-status-completed` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `service.type` | `nexus.subsystem=vault`, `nexus.vault.management.operation=status`, `nexus.vault.management.initialized`, `nexus.vault.management.verified`, `nexus.vault.management.active_key_version`, `nexus.vault.management.key_versions_count`, `nexus.vault.management.dek_total`, `nexus.vault.management.dek_rewrap_required`, `nexus.vault.management.last_rotation_result`, `nexus.vault.management.last_rotation_reason` | status snapshot rendered |
| `vault-status-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `error.code`, `error.message` | `nexus.subsystem=vault`, `nexus.vault.management.operation=status`, `nexus.vault.management.reason` | status or optional verify failed |
| `vault-rotate-started` | INFO milestone | `info` | — | `event.action`, `trace.id`, `service.type` | `nexus.subsystem=vault`, `nexus.vault.management.operation=rotate`, `nexus.vault.management.operation_id`, `nexus.vault.management.dry_run`, `nexus.vault.management.verify_requested` | before current passphrase is verified and new metadata is created |
| `vault-rotate-completed` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `service.type` | `nexus.subsystem=vault`, `nexus.vault.management.operation=rotate`, `nexus.vault.management.operation_id`, `nexus.vault.management.active_key_version`, `nexus.vault.management.dek_rewrapped_count`, `nexus.vault.management.rotated_at`, `nexus.vault.management.last_rotation_result=ok` | rotate and DEK rewrap completed |
| `vault-rotate-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `error.code`, `error.message` | `nexus.subsystem=vault`, `nexus.vault.management.operation=rotate`, `nexus.vault.management.operation_id`, `nexus.vault.management.reason`, `nexus.vault.management.last_rotation_result=failed` | rotate failed before or during rewrap/post-verify |
| `vault-rewrap-started` | INFO milestone | `info` | — | `event.action`, `trace.id`, `service.type` | `nexus.subsystem=vault`, `nexus.vault.management.operation=rewrap`, `nexus.vault.management.operation_id`, `nexus.vault.management.dry_run`, `nexus.vault.management.verify_requested` | before DEK rewrap with current active key |
| `vault-rewrap-completed` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `service.type` | `nexus.subsystem=vault`, `nexus.vault.management.operation=rewrap`, `nexus.vault.management.operation_id`, `nexus.vault.management.active_key_version`, `nexus.vault.management.dek_rewrapped_count`, `nexus.vault.management.last_rotation_result=ok` | rewrap completed |
| `vault-rewrap-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `error.code`, `error.message` | `nexus.subsystem=vault`, `nexus.vault.management.operation=rewrap`, `nexus.vault.management.operation_id`, `nexus.vault.management.reason`, `nexus.vault.management.last_rotation_result=failed` | rewrap failed before/during/post-verify |
| `vault-dry-run-evaluated` | INFO decision | `info` | `success`/`failure` | `event.action`, `event.outcome`, `trace.id`, `service.type` | `nexus.subsystem=vault`, `nexus.vault.management.operation`, `nexus.vault.management.dry_run=true`, `nexus.vault.management.can_apply`, `nexus.vault.management.initialized`, `nexus.vault.management.dek_total`, `nexus.vault.management.dek_rewrap_required` | dry-run branch decides whether operation can be applied |

### Canonical taxonomy для unseal / post-verify

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `vault-unseal-verified` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `service.type` | `nexus.subsystem=vault`, `nexus.vault.management.operation`, `nexus.vault.management.active_key_version`, `nexus.vault.unseal.kdf_algo`, `nexus.vault.unseal.kdf_memory_cost_kib`, `nexus.vault.unseal.kdf_time_cost`, `nexus.vault.unseal.kdf_parallelism`, `nexus.vault.unseal.hmac_algo` | passphrase matched persisted unseal metadata |
| `vault-unseal-failed` | INFO milestone | `warning`/`error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `error.code`, `error.message` | `nexus.subsystem=vault`, `nexus.vault.management.operation`, `nexus.vault.management.reason`, `nexus.vault.unseal.kdf_algo`, `nexus.vault.unseal.hmac_algo` | passphrase/KDF/HMAC validation failed |
| `vault-post-verify-completed` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `service.type` | `nexus.subsystem=vault`, `nexus.vault.management.operation`, `nexus.vault.management.active_key_version`, `nexus.vault.startup.probe_present`, `nexus.vault.startup.probe_created` | post-verify startup guard accepted new/current keyring |
| `vault-post-verify-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `error.code`, `error.message` | `nexus.subsystem=vault`, `nexus.vault.management.operation`, `nexus.vault.management.reason`, `nexus.vault.management.active_key_version` | post-verify startup guard failed |

### Нормализация и анти-дублирование

- Не плодить отдельные action для interactive/non-interactive admin mode:
  `nexus.vault.admin_gate.mode` достаточно.
- Не создавать `vault-rotate-dek-rewrapped` на каждый DEK в baseline logs. Для ES-мониторинга
  достаточно `nexus.vault.management.dek_rewrapped_count`; per-DEK forensic trace можно добавить
  позже отдельным sampled/TRACE режимом без secret material.
- `vault-dry-run-evaluated` не заменяет `vault-init-started` / `vault-rotate-started`: dry-run
  фиксирует проверку применимости без изменения storage.
- `vault-unseal-verified` описывает проверку passphrase against metadata. `vault-post-verify-*`
  описывает startup-readiness проверку после изменения или проверки keyring.
- `admin-gate-failed` не должен содержать hash value, password value или абсолютный путь к hash-файлу.
  Допустимы reason, mode, hash source, file mode и безопасный error code.

### Минимальный field profile

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | из vault-management action dictionary |
| `event.outcome` | required on completion/failure | `success`/`failure`; не нужен на `*-started` |
| `trace.id` | required | correlation command run |
| `service.type` | required | component identity: `vault`; конкретная manual operation живёт в `nexus.vault.management.operation` |
| `event.dataset` | not used by default | manual vault management не dataset-scoped |
| `nexus.subsystem` | required | `vault` |
| `nexus.vault.management.operation` | required | `init`, `status`, `rotate`, `rewrap` |
| `nexus.vault.management.operation_id` | recommended | внутренний `vault_mgmt_<uuid>` для mutation operations |
| `nexus.vault.management.dry_run` | recommended | CLI dry-run mode |
| `nexus.vault.management.force` | recommended | CLI force skipped confirm step |
| `nexus.vault.management.non_interactive` | recommended | CLI/admin gate input mode |
| `nexus.vault.management.verify_requested` | recommended | post-verify requested |
| `nexus.vault.management.verified` | recommended for status | status included unseal/startup verify |
| `nexus.vault.management.can_apply` | required for dry-run | dry-run applicability result |
| `nexus.vault.management.initialized` | recommended for status/dry-run | whether unseal metadata exists |
| `nexus.vault.management.active_key_version` | recommended | safe key version identifier only |
| `nexus.vault.management.key_versions_count` | recommended | count, not raw key material |
| `nexus.vault.management.dek_total` | recommended | total stored DEK records |
| `nexus.vault.management.dek_rewrap_required` | recommended | DEK records not wrapped by active key |
| `nexus.vault.management.dek_rewrapped_count` | required on rotate/rewrap completion | aggregate changed DEK count |
| `nexus.vault.management.rotated_at` | recommended | timestamp returned by result/status |
| `nexus.vault.management.last_rotation_result` | recommended | `ok`, `failed`, `rotating`, ... |
| `nexus.vault.management.last_rotation_reason` | recommended | stable safe reason |
| `nexus.vault.management.last_rotation_run_id` | optional | previous management operation id |
| `nexus.vault.management.reason` | recommended on failures/degraded decisions | safe reason from domain details |
| `nexus.vault.admin_gate.*` | required for admin-gate events | mode/required/reason/hash source without password/hash leakage |
| `nexus.vault.unseal.*` | recommended for verify/init/rotate | algorithm and KDF params without salts/digest |
| `nexus.vault.startup.*` | recommended for post-verify | reuse startup field profile from Zone 11 |
| `error.code`, `error.message` | required on failures | `VaultDomainError.code` maps directly to `error.code` |

### Detail policy для Vault Management

- `INFO` — operation start/completion, status snapshot, dry-run result, admin gate passed/skipped,
  unseal verify and post-verify success.
- `WARNING` — admin access denied or operator/input/config condition that blocks operation without an
  unexpected exception.
- `ERROR` — operation failed during storage, crypto, DEK unwrap/rewrap, post-verify, or unexpected
  delivery/usecase exception.
- `DEBUG` — optional storage-level details only when they remain aggregate and safe.
- `TRACE` — not baseline; reserve for future forensic per-DEK rewrap diagnostics without plaintext,
  wrapped material or raw record bodies.

### Что не логировать

- Admin password, unseal passphrase, master key material, DEK plaintext, wrapped DEK.
- Argon2/HMAC salts, HMAC digest, raw unseal metadata payload.
- Full `VaultDekRecord`, `VaultProbeRecord`, `VaultUnsealMetadata`.
- Absolute hash file paths by default; prefer `hash_source=file`, configured boolean and safe file mode.
- Prompt text/result beyond final safe outcome.

### Что уже легко заполнить при внедрении

- `VaultKeyManagementStatus` already provides initialized/key/dek/last-rotation fields.
- `VaultKeyManagementResult` already provides operation id, active key version, rewrapped count and
  rotated timestamp.
- `VaultAdminPasswordGate` already knows mode, policy-required state, reason and safe file mode.
- `VaultDomainError.code` and `details["reason"]` already map to `error.code` and
  `nexus.vault.management.reason` / `nexus.vault.admin_gate.reason`.
- `VaultUnsealMetadata` already contains KDF/HMAC algorithm and cost params; salts and digest must be
  dropped before logging.

### Что останется вне зоны

- Runtime startup/read/write/retention секретов — Zone 11.
- Generic command report/ledger/pointer finalization — Zone 1/2.
- Future external KMS/HSM provider telemetry, если появится отдельный key-provider backend.

---
