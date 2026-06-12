# Zone 7: DSL Artifact Lifecycle

Седьмая зона описывает lifecycle внешних декларативных артефактов: discovery, load, parse,
validation, hydration/compile и сборку registry. DSL здесь рассматривается как **input boundary**,
а не как runtime-исполнение стадии.

### Границы зоны

- DSL taxonomy покрывает YAML/spec artifacts из `datasets/registry.yaml`, dataset specs, source
  specs, transform specs, cache specs, dictionary specs и target specs.
- Зона заканчивается там, где из внешнего артефакта получен типизированный runtime/stage объект.
- Runtime-ошибки выполнения операции относятся к taxonomy соответствующей стадии (`map`,
  `normalize`, `enrich`, `match`, `resolve`), но могут нести `nexus.dsl.rule.name` или
  `nexus.dsl.operation.name` как контекст.
- DSL-события не должны описывать network/DB side effects. Если событие говорит про внешний I/O,
  это taxonomy cache/dictionary/target/storage, а не DSL.
- В `nexus.dsl.spec.path` используем относительные пути; raw YAML body не логируем.

### Фазы DSL lifecycle

| Phase | Смысл |
|---|---|
| `discover` | Найден внешний spec artifact или ссылка на него |
| `load` | YAML/spec файл прочитан с диска |
| `parse` | YAML преобразован в intermediate dict/model input |
| `validate` | Pydantic/semantic validation прошла или вернула errors |
| `compile` | Spec преобразован в runtime object: rule, operation, stage config, provider config |
| `registry-build` | Собран общий registry datasets/targets/dictionaries/cache policies |
| `default-resolve` | Применены defaults, implicit links, fallback policy |

### Canonical taxonomy для зоны

| Action | Bucket | Default level | Outcome | Required ECS fields | Typical project fields | Emission point |
|---|---|---|---|---|---|---|
| `dsl-registry-loaded` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem` | `nexus.dsl.phase=load`, `nexus.dsl.spec.kind=registry`, `nexus.dsl.spec.path` | registry YAML loaded |
| `dsl-registry-built` | INFO milestone | `info` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem` | `nexus.dsl.phase=registry-build`, `nexus.dsl.spec.count`, `event.dataset` optional | effective registry ready |
| `dsl-registry-build-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem`, `error.*` | `nexus.dsl.phase=registry-build`, `nexus.dsl.error.count`, `nexus.dsl.spec.path` | registry assembly failed |
| `dsl-spec-discovered` | TRACE diagnostic | `trace` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem` | `nexus.dsl.phase=discover`, `nexus.dsl.spec.kind`, `nexus.dsl.spec.path` | spec discovery/link traversal |
| `dsl-spec-loaded` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem` | `nexus.dsl.phase=load`, `nexus.dsl.spec.kind`, `nexus.dsl.spec.name`, `nexus.dsl.spec.path` | one spec file loaded |
| `dsl-spec-parsed` | TRACE diagnostic | `trace`/`debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem` | `nexus.dsl.phase=parse`, `nexus.dsl.spec.kind`, `nexus.dsl.spec.path` | YAML parse completed |
| `dsl-spec-validated` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem` | `nexus.dsl.phase=validate`, `nexus.dsl.spec.kind`, `nexus.dsl.spec.name`, `nexus.dsl.spec.path` | Pydantic/semantic validation completed |
| `dsl-spec-compiled` | DEBUG decision | `debug` | `success` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem` | `nexus.dsl.phase=compile`, `nexus.dsl.spec.kind`, `nexus.dsl.spec.name`, `nexus.dsl.rule.name`, `nexus.dsl.operation.name` | compiler produced runtime object |
| `dsl-load-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem`, `error.*` | `nexus.dsl.phase=load`, `nexus.dsl.spec.kind`, `nexus.dsl.spec.path`, `error.code` | file read/YAML parse failure |
| `dsl-validation-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem`, `error.*` | `nexus.dsl.phase=validate`, `nexus.dsl.spec.kind`, `nexus.dsl.spec.path`, `nexus.dsl.yaml.path`, `nexus.dsl.error.count` | structural/semantic validation failure |
| `dsl-compile-failed` | INFO milestone | `error` | `failure` | `event.action`, `event.outcome`, `trace.id`, `nexus.subsystem`, `error.*` | `nexus.dsl.phase=compile`, `nexus.dsl.spec.kind`, `nexus.dsl.rule.name`, `nexus.dsl.operation.name` | valid spec cannot compile to runtime object |

### Минимальный field profile для DSL events

| Поле | Статус | Примечание |
|---|---|---|
| `event.action` | required | из DSL action-словаря |
| `event.outcome` | required on completion/failure | `success`/`failure`; discovery может быть non-terminal |
| `trace.id` | required | correlation запуска |
| `nexus.subsystem` | required | всегда `dsl` для lifecycle spec events |
| `nexus.dsl.phase` | required | одна из phase lifecycle выше |
| `nexus.dsl.spec.kind` | required when spec-scoped | тип артефакта, а не Python class name |
| `nexus.dsl.spec.path` | required when file-scoped | относительный путь, absolute path только для local debug |
| `event.dataset` | required when dataset-aware | если spec относится к конкретному dataset |
| `nexus.dsl.yaml.path` | recommended for validation errors | помогает найти проблемный ключ без raw YAML |
| `nexus.dsl.rule.name` | recommended for rule-scoped compile/validation | имя правила, если есть |
| `nexus.dsl.operation.name` | recommended for operation-chain context | имя DSL operation, если ошибка привязана к operation |
| `nexus.dsl.error.count` | recommended for aggregate failures | summary validation/registry errors |
| `error.*` | required for failures | `error.code` должен брать diagnostic/catalog code, когда он есть |

### Detail policy для DSL

- `INFO` — только registry ready/failure и blocking DSL failures, влияющие на запуск команды.
- `DEBUG` — per-spec load/validate/compile summary.
- `TRACE` — discovery traversal, default resolution, YAML path traversal, operation-chain детали.
- `WARNING` — deprecated spec shape, fallback/default, optional artifact skipped, если команда продолжает работу.
- `ERROR` — blocking load/validation/compile/registry build failures.

### Что не логировать

- Raw YAML body, source CSV snippets, target payload, generated payload.
- Секреты, default passwords, token values, vault material.
- Every YAML key на INFO/DEBUG; для глубокой диагностики использовать TRACE и `nexus.dsl.yaml.path`.
- Absolute paths в обычном режиме, если достаточно `nexus.dsl.spec.path`.
- Runtime execution result как DSL-событие: lookup/cache/target/stage actions должны жить в своих зонах.

### Что важно учесть при миграции текущего кода

- Текущий `DSL load error` в orchestrator целево маппится в `dsl-load-failed`,
  `dsl-validation-failed` или `dsl-compile-failed` по деталям `DslLoadError`. Пока такого
  classifier нет, допустим общий `dsl-load-failed` с `error.code`.
- Старые generic actions `spec-loaded`, `spec-registry-built`, `spec-validation-failed` считаются
  legacy/compat. Новые call-sites должны использовать `dsl-*`.
- Dictionary/cache/target loaders используют DSL taxonomy только для lifecycle spec artifact.
  Runtime lookup/refresh/request события этих подсистем остаются в provider taxonomy.
