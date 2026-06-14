# Zone 2: Command-Specific Delivery Lifecycle

Вторая рабочая зона taxonomy — lifecycle **конкретных CLI-сценариев доставки**, которые уже
выходят за рамки общего runtime orchestration, но ещё не являются глубокой телеметрией
внутренних подсистем. Это слой между `orchestrator` и `usecase/stage subsystem` taxonomy.

Сюда относятся:

- `import plan`
- `import apply`
- `check-api`
- debug-команды `mapping`, `normalize`, `enrich`, `match`, `resolve`

Эта зона отвечает на вопрос: **какой пользовательский сценарий выполнялся и чем он закончился**.
Она не должна описывать внутренние cache/dictionary/target действия построчно: такие события
живут в последующих subsystem-зонах.

### Принципы именно для этой зоны

- Runtime-события (`run-started`, `report-written`, `resource-init-failed`) не дублируются
  здесь. Зона 2 описывает только специфический outcome конкретной команды.
- Различия между командами выражаются прежде всего через `service.type`, а не через искусственное
  размножение почти одинаковых action для каждого шага одной и той же команды.
- Capability-команды (`cache refresh`, `cache clear`, `vault-management rotate`) допустимо
  фиксировать здесь как command lifecycle. При этом operational telemetry тех же capability
  (`cache lookup`, `secret read`, `provider fallback`) должна жить в отдельных subsystem-зонах.
- Если событие уже относится к конкретной pipeline stage или к cache/target/vault subsystem,
  оно не должно оставаться в command-zone только потому, что было залогировано из delivery слоя.
- Для dataset-aware команд canonical business context передаётся через `event.dataset`; для
  dataset-agnostic команд поле может отсутствовать.

### Canonical taxonomy для зоны

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `plan-written` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `file.path` | `event.dataset`, `nexus.subsystem=plan`, `nexus.plan.items_count`, `nexus.plan.planned_create`, `nexus.plan.planned_update` | plan command persisted resulting artifact |
| `plan-build-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `error.*` | `event.dataset`, `nexus.stage.name`, `nexus.subsystem=core` | import plan command failed semantically |
| `apply-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `error.*` | `event.dataset`, `nexus.stage.name`, `nexus.subsystem=core` | import apply command failed semantically |
| `identity-init-failed` | DEBUG decision | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `error.*` | `event.dataset`, `nexus.subsystem=identity` | apply-specific identity bootstrap failed |
| `api-check-completed` | INFO milestone | `info`/`error` | `success` or `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type` | `nexus.subsystem=target`, `url.full` or target endpoint metadata | check-api command completed |
| `debug-stage-completed` | INFO milestone | `info`/`error` | `success` or `failure` | `event.action`, `event.outcome`, `trace.id`, `service.type`, `nexus.stage.name` | `event.dataset`, `nexus.stage.rows_total` or `nexus.stage.items_count`, `event.duration` | debug stage command completed with stage artifact/result |

### Нормализация и анти-дублирование

- Не вводить отдельные action вида `mapping-command-completed`, `normalize-command-completed`,
  `enrich-command-completed`, если различие уже выражается через `nexus.stage.name` и `service.type`.
- Не смешивать `plan-written` с runtime `report-written` / `log-written`. Первое — outcome
  command use case, вторые — observability finalization.
- Не поднимать внутрь command-zone subsystem-события вроде `cache-refresh-started`,
  `target-write-failed`, `dictionary-lookup`; даже если их инициировала конкретная команда.
- Если debug-команда завершилась на границе stage и не создаёт отдельной бизнес-семантики,
  допустим один обобщённый action `debug-stage-completed` с обязательным `nexus.stage.name`.

### Минимальный field profile для зоны

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | всегда из canonical словаря зоны |
| `event.outcome` | required | команда или command-specific subflow должны иметь явный outcome |
| `trace.id` | required | основной correlation key одного запуска |
| `service.type` | required | `planner`, `applier`, `topology`, `normalizer`, `matcher`, … |
| `event.dataset` | optional but expected for dataset-aware commands | отсутствует у dataset-agnostic команд |
| `nexus.stage.name` | required only for stage-bound debug commands and stage-aware failures | не нужен для `check-api` |
| `labels.pipeline_run_id` | optional | только если нужно связать несколько command runs/artifacts |
| `error.type`, `error.message` | required on failure events | stack trace — по общим правилам уровня |
| `file.path` | optional | артефакт команды (`plan.json`, debug output, etc.) |
| `event.duration` | recommended on completion | особенно для debug/stage commands и API check |
| `nexus.subsystem` | recommended | `core`, `identity`, `target`, `report` |

### Что останется на следующие зоны

- `stage-started`, `stage-completed`, `stage-failed` — отдельная зона pipeline stage lifecycle.
- `cache-refresh-*`, `cache-status-*`, `cache-init-failed` — зона cache.
- `apply-item`, `apply-completed`, `target-write-*` — зона target/apply execution (Zone 10).
- `dictionary-lookup`, `lookup-hit/miss`, candidate telemetry — зона enrich/dictionary.

---
