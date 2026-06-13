# Zone 1: Runtime Orchestrator / CLI Lifecycle

Первая рабочая зона taxonomy — общий lifecycle CLI-команды и runtime-обвязки в
`connector/delivery/cli/runtime/orchestrator.py`. Это **не** бизнес-события отдельных подсистем
(`cache`, `vault`, `target`, `topology`), а общий каркас исполнения команды:
bootstrap → validation → init → handler → finalize → pointers/ledger → shutdown.

### Принципы именно для этой зоны

- События зоны описывают **общий lifecycle команды**, а не детали конкретного use case.
- Если событие одинаково важно для `mapping`, `import plan`, `import apply`, `check-api`, оно
  фиксируется здесь как runtime-milestone, а не дублируется в taxonomy по подсистемам.
- Различия между командами выражаются через `service.type`, `event.dataset`,
  `nexus.subsystem`, а не через отдельный action на каждую команду.
- Best-effort observability события (`ledger`, `pointer`, `retention`) остаются в runtime-зоне,
  потому что они относятся к orchestration/finalization, а не к бизнес-логике.

### Canonical taxonomy для зоны

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `command-started` | INFO milestone | `info` | — | `event.action`, `trace.id`, `service.type` | `nexus.subsystem=core` | runtime enters command execution |
| `command-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.type`, `error.message`, `trace.id` | `nexus.subsystem=core` | unhandled command-level exception |
| `config-load-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=config` | `SettingsLoadError` path |
| `dsl-load-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=dsl`, `nexus.dsl.phase=load`, `error.code` | `DslLoadError` path |
| `runtime-validation-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=config`, `nexus.runtime.exit_code` | invalid CLI/runtime requirements |
| `resource-init-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=core`, `nexus.resource.phase=init` | generic DI/runtime init failure |
| `cache-init-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=cache` | sqlite/cache init failure |
| `vault-startup-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=vault`, `error.code` | vault startup / key validation failure |
| `resource-shutdown-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=core`, `nexus.resource.phase=shutdown`, `nexus.resource.subcontainer` | one subcontainer shutdown failed |
| `resource-shutdown-completed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id` | `nexus.subsystem=core`, `nexus.resource.failed_subcontainers` | shutdown finished with one or more failures |
| `report-written` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id` | `nexus.subsystem=report`, `file.path` | report JSON persisted successfully |
| `report-finalize-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `error.*`, `trace.id` | `nexus.subsystem=report` | final report assembly or write failed |
| `log-written` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id` | `nexus.subsystem=log`, `file.path` | non-report path finalized active log |
| `ledger-record-failed` | DEBUG decision | `warning` | `failure` | `event.action`, `event.outcome`, `trace.id` | `nexus.subsystem=observability`, `nexus.observability.phase=ledger-build` | report/non-report ledger record build failed |
| `ledger-append-failed` | DEBUG decision | `warning` | `failure` | `event.action`, `event.outcome`, `trace.id` | `nexus.subsystem=observability`, `nexus.observability.phase=ledger-append` | backend append failed |
| `pointer-publish-failed` | DEBUG decision | `warning` | `failure` | `event.action`, `event.outcome`, `trace.id` | `nexus.subsystem=observability`, `nexus.observability.phase=pointer-publish` | latest pointer update failed |
| `retention-sweep-failed` | DEBUG decision | `warning` | `failure` | `event.action`, `event.outcome`, `trace.id` | `nexus.subsystem=observability`, `nexus.observability.phase=retention-sweep` | startup sweeper failed |

### Нормализация и анти-дублирование

- Не плодить action по имени конкретной CLI-команды (`mapping-started`, `check-api-started`,
  `import-plan-started`) на уровне runtime. Для этого уже есть `service.type`.
- Не плодить отдельные action для каждой вторичной observability-операции (`report-pointer-failed`,
  `plan-pointer-failed`, `log-pointer-failed`), если различие можно выразить через
  `nexus.observability.phase` или `nexus.artifact.kind`.
- Не использовать runtime-зону для событий бизнес-подсистем (`cache-refresh-started`,
  `target-write-failed`, `dictionary-lookup`). Они будут жить в своих зонах taxonomy.

### Минимальный field profile для зоны

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | всегда из canonical словаря зоны |
| `event.outcome` | required on completion/failure | `success`/`failure`; не нужен на `command-started` |
| `trace.id` | required | основной correlation key одного command/pipeline run |
| `labels.pipeline_run_id` | optional | только если нужен correlation шире одного `trace.id` |
| `service.type` | required | идентичность исполняющего компонента/команды |
| `event.dataset` | optional | только для dataset-aware runtime events; не обязателен для общего bootstrap/shutdown lifecycle |
| `nexus.stage.*` | not used by default | runtime zone не должна искусственно притягивать stage, если событие вне pipeline stage |
| `nexus.subsystem` | recommended | `core`, `config`, `dsl`, `report`, `log`, `observability`, `cache`, `vault` |
| `error.type`, `error.message` | required on error/warning-failure events | оба источника (`exception` dict и manual kwargs) поддерживаются |
| `error.code` | optional | когда есть domain/diag code |
| `file.path` | optional | `report-written`, `log-written`, `plan-written` |
| `nexus.resource.phase` | optional | `init` / `shutdown` |
| `nexus.resource.subcontainer` | optional | имя subcontainer при shutdown/init failure |
| `nexus.observability.phase` | optional | `retention-sweep`, `ledger-build`, `ledger-append`, `pointer-publish` |

### Что останется на следующие зоны

- `plan-written`, `plan-build-failed`, `apply-failed`, `api-check-completed` — это уже зона
  command-specific delivery lifecycle, не общий runtime orchestration.
- `target-write-*` — зона target/apply execution (Zone 10).
- `cache-refresh-*` — зона cache.
- `vault-runtime-*`, `secret-read`, `secret-written`, retention/maintenance — зона vault/secrets runtime lifecycle (Zone 11).
- `vault-init-*`, `vault-status-*`, `vault-rotate-*`, `vault-rewrap-*`, `admin-gate-*` —
  vault management lifecycle (Zone 12).

---
