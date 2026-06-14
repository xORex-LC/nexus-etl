# ECS Logging — Worknote (реализация и архитектурные детали)

Статус: draft
Последнее обновление: 2026-06-14

## Цель документа

Рабочий артефакт для обсуждения **реализации** ECS-перехода логирования. ADR
[OBSERVABILITY-DEC-003](../../adr/observability/OBSERVABILITY-DEC-003-ecs-renderer-and-field-mapping.md)
фиксирует *решение* (свой `ecs_transform`, dotted-ключи, порядок процессоров, поддержание
совместимости). Здесь — то, что ADR намеренно не доводит до деталей: пограничные случаи маппинга,
семантика спорных полей, конфиг-поверхность, тест-инфраструктура, порядок наполнения call-sites.

Документ:
- дополняется по мере обсуждения;
- фиксирует под-решения до и во время реализации Фазы 1/2;
- когда под-решение стабилизируется — переезжает в ADR или dev-doc, а здесь остаётся пометка.

Легенда приоритета: 🔴 блокер для Фазы 1 · 🟠 решить в Фазе 1 · 🟡 можно в Фазе 2 · ⚪ фон.

---

## Уже зафиксировано (контекст, не обсуждаем заново)

- Один процессор `ecs_transform` (dict→dict) перед `JSONRenderer`, только на JSON-синках.
- Порядок: `ExceptionRenderer → redaction → remove_processors_meta → ecs_transform → JSONRenderer`.
- Dotted-ключи; catch-all неучтённого в `labels.*`.
- Машинная истина taxonomy — YAML в `connector/common/observability/taxonomy/`:
  `actions.yaml` и `fields/*.yaml`. Документация в `docs/dev/layers/observability/ecs-logging-taxonomy/`
  объясняет семантику и зоны.
- `connector/infra/logging/ecs.py` — runtime-маппер в ECS-форму, не каталог taxonomy и не источник
  описаний событий.
- Production formatter остаётся своим (`ecs_transform`); библиотеку `ecs-logging` не используем как
  runtime-formatter. Её можно рассматривать только как справочный/dev-инструмент, если это даст пользу.

---

## Рабочая стартовая точка на 2026-06-14

Главный риск сейчас — начать с массовой правки call-sites и размазать ECS-логику по delivery/usecases/
infra. Поэтому порядок должен быть обратным: сначала зафиксировать границы и проверяющие контракты,
затем реализовать маленький runtime-transform, и только после этого заводить zone adapters и переносить
конкретные лог-вызовы на taxonomy.

### С чего начинаем

1. **Границы пакета и модулей.** Определить минимальный public API observability logging layer:
   `ecs_transform`, taxonomy registry/loader, event dataclasses/enums, event sink, zone adapters.
2. **Guard-тесты до интеграции.** Зафиксировать, что `domain` не импортирует logging/infra,
   `delivery/usecases` не знают про ECS-маппинг, а call-sites не передают reserved-ключи вроде
   `component`.
3. **Runtime ECS renderer.** Реализовать `ecs_transform` как чистый structlog processor без DI и I/O:
   вход `event_dict`, выход ECS dict, tolerate foreign logs, exception mapping после redaction.
4. **Taxonomy validation.** Поднять Pydantic-модели только для загрузки YAML taxonomy и тестов
   согласованности: action существует, zone/action/status/outcome валидны, field mapping не расходится
   с dev-doc.
5. **Первый вертикальный срез.** Взять одну зону с малым радиусом, например runtime/CLI lifecycle,
   и пройти путь `zone adapter → event sink → structlog → ecs_transform → JSON`.

### Предлагаемые границы модулей

| Модуль | Роль | Ограничение |
|---|---|---|
| `connector/infra/logging/ecs.py` | Чистый ECS renderer/processor: rename fields, ECS defaults, `error.*`, catch-all в `labels.*` | Без чтения YAML, без DI, без бизнес-семантики зон |
| `connector/infra/logging/taxonomy.py` | Загрузка/валидация taxonomy YAML на текущем этапе | Pydantic здесь допустим, но не в hot path |
| `connector/common/observability/events.py` | Лёгкие dataclass/enum контракты событий, если ими должны пользоваться usecases/adapters | Только stdlib; не тянуть Pydantic/structlog |
| `connector/domain/ports/observability.py` | Порт `ObservabilityEventSink`, если usecases должны эмитить события не зная infra | Protocol only, без ECS-полей и structlog |
| `connector/infra/logging/event_sink.py` | Адаптер порта в structlog runtime | Единственное место, где event object становится log kwargs |
| `connector/infra/logging/zones/*.py` | Zone adapters: удобные методы уровня `runtime_started(...)`, `vault_rotation_failed(...)` | Не форматируют ECS напрямую; выбирают action/outcome и доменные поля |

Текущий `connector/common/observability/taxonomy/` хранит YAML-данные. Кодовый loader лучше не класть
в `common`, пока `common` остаётся stdlib-only зоной. При выделении отдельного пакета `observability`
loader и модели переедут туда вместе с YAML.

### Целевая граница observability logging layer

Это целевая модель на конец реализации. Текущие нарушения могут существовать во время перехода, но
они не должны становиться нормой и должны быть закрыты до завершения ECS-слоя.

| Зона | Можно | Нельзя |
|---|---|---|
| `connector/common/observability` | Value-only shared kernel: `ServiceComponent`, layout policies, redaction policy, lightweight event dataclasses/enums, YAML taxonomy data | `structlog`, stdlib `logging`, `pydantic`, `yaml`, filesystem I/O, DI, imports из `domain/usecases/infra/delivery` |
| `connector/domain` | Diagnostics/reporting/domain events; при необходимости — только `Protocol` порта observability и value objects | `structlog`, `logging.getLogger`, ECS dotted fields, `event.action` strings, imports из `infra/logging` |
| `connector/usecases` | Оркестрация и вызов `ObservabilityEventSink`/zone-port, если событие является частью usecase lifecycle | `structlog`, `logging.getLogger`, прямой `ctx.logger`, ECS-маппинг, `component=` в log kwargs |
| `connector/infra/logging` | structlog runtime, redaction, ECS transform, taxonomy loader, concrete event sink, zone adapter implementations | Импорт из `delivery`, бизнес-оркестрация usecases, изменение report/plan artifacts |
| `connector/infra/observability` | Ledger, retention, pointers, artifact viewer; best-effort эксплуатационная инфраструктура | ECS field mapping, taxonomy decisions, log statement authoring |
| `connector/delivery/cli` | Composition root: wiring runtime, sinks, ports, adapters; CLI context binding | ECS-transform logic, taxonomy validation logic, domain decisions |
| `connector/delivery/commands` | Тонкие handlers, presenter-facing command flow; временно могут логировать через `ctx.logger` до миграции | Новые raw `structlog.get_logger`, новые event.action literals, reserved `component=` kwargs |

Ключевое правило: прикладной код сообщает о событии, observability layer решает, как оно выглядит в
ECS JSON. `event.action`, `event.kind`, `event.category`, `event.type`, `ecs.version`, `labels.*` и
`error.*` не должны собираться руками в command/usecase/domain коде.

### Разделение responsibility внутри observability

Нужно держать отдельно четыре подслоя, иначе новый пакет сразу станет связанным с текущей CLI-формой:

| Подслой | Ответственность | Примеры |
|---|---|---|
| Shared kernel | Стабильные value objects и данные taxonomy | `ServiceComponent`, `ObservabilityEvent`, `actions.yaml`, `fields/*.yaml` |
| Runtime logging | Транспорт и форматирование логов | `StructuredLoggingRuntime`, `ecs_transform`, redaction, handlers |
| Semantic adapters | Прикладные фасады зон | `RuntimeLifecycleEvents`, `VaultManagementEvents`, `PipelineStageEvents` |
| Artifact observability | Где лежат логи/отчёты/планы и как их обслуживать | layout, retention, ledger, pointers, viewer |

Связи между ними должны быть однонаправленными:
- semantic adapters → event sink → runtime logging;
- runtime logging → shared kernel только за value objects;
- artifact observability → shared kernel layout/value objects;
- shared kernel → никуда наружу.

`ecs_transform` не должен зависеть от zone adapters. Zone adapters не должны знать про dotted ECS keys.
Taxonomy loader может валидировать YAML и строить registry, но runtime processor должен уметь обработать
обычный legacy/foreign log без registry lookup.

### Reserved keys и владение полями

К концу реализации у каждого поля должен быть один владелец:

| Поле/группа | Владелец | Источник |
|---|---|---|
| `@timestamp`, `log.level`, `log.logger` | runtime logging | structlog processors / stdlib record |
| `ecs.version`, `service.*`, `host.*`, `process.*` | runtime logging | `LoggingRuntimeMeta` и constants |
| `trace.id`, `nexus.run_id`, `nexus.pipeline_run_id`, `labels.component`, `labels.dataset` | context binding | `bind_observability_context(...)` |
| `event.action`, `event.kind`, `event.category`, `event.type`, `event.outcome` | taxonomy + zone adapter | action registry and event object |
| `message` | call-site/zone adapter | human-readable message |
| `error.*` | runtime ECS transform | redacted `exception` / explicit safe error fields |
| domain fields (`record_ref`, `diag_code`, `stage`, `duration_ns`, etc.) | event object / zone adapter | typed event fields |
| `labels.*` catch-all | runtime ECS transform | остаток безопасных kwargs |

Reserved keys нельзя передавать как обычные kwargs из call-sites: `component`, `ecs.version`,
`event.kind`, `event.category`, `event.type`, `host`, `pid`, `service`, `process`, `log`, `labels`,
`error`, `exception`. Если прикладному коду нужно уточнить подсистему, он использует `scope`, а не
`component`.

### Целевая политика прямого логирования

В конце миграции прямые log calls остаются только там, где слой действительно владеет transport/runtime:
- `connector/infra/logging/*` — да, это сам logging runtime.
- `connector/delivery/cli/runtime/orchestrator.py` — допустимо только как composition/lifecycle boundary,
  либо через runtime lifecycle zone adapter.
- `connector/delivery/cli/stream_capture.py` — допустимо, потому что это bridge stdout/stderr → logger.

В остальных местах предпочтительный путь:
- domain: diagnostics/reporting/domain result, без логгера;
- usecases: `ObservabilityEventSink` или zone adapter, инжектированный через DI;
- delivery command handlers: `ctx` + injected adapter/sink, без новых `structlog.get_logger`;
- infra adapters: logger допустим для инфраструктурных событий, но без ECS dotted keys и без
  reserved `component`.

### Контракт runtime-события

Минимальный объект события должен описывать не JSON-строку, а намерение:
- `action`: канонический `event.action` из taxonomy.
- `outcome`: `success` / `failure` / `unknown`, когда применимо.
- `kind`: из taxonomy по action, а не вручную в каждом call-site.
- `message`: человекочитаемый текст; не машинный код события.
- `fields`: доменные структурные поля (`dataset`, `stage`, `record_ref`, `diag_code`, `duration_ns`).

`ecs_transform` не должен угадывать бизнес-событие по `message`. Если action не передан, это либо
foreign log, либо legacy call-site; такой лог остаётся ECS-совместимым, но без полной taxonomy-семантики.

### Pydantic-модели

Pydantic нужен на границе YAML taxonomy и конфигурации, а не в каждом log-вызове:
- `TaxonomyActionSpec`, `TaxonomyFieldSpec`, `TaxonomyRegistry` — `frozen=True`, `extra="forbid"`.
- В runtime hot path — dataclass/StrEnum/Literal, чтобы логирование не стало дорогим и хрупким.
- Валидацию неизвестного action делаем в тестах и, опционально, в dev/debug режиме, но не как hard fail
  production-лога.

### Порт и адаптеры

Один generic sink выглядит достаточным как внутренний транспорт:

```python
class ObservabilityEventSink(Protocol):
    def emit(self, event: ObservabilityEvent) -> None: ...
```

Но usecase-facing API не должен быть generic `emit(action=...)`. Zone adapters должны быть тонкими
фасадами над sink-ом. Их задача — не форматировать ECS, а скрыть от прикладного кода названия action,
outcome и обязательные поля конкретной зоны. Если зона требует синхронного результата, метрик или
span-like lifecycle, это остаётся на уровне adapter API, но транспорт внутри observability всё равно
один: `emit(event)`.

### DI-модель

DI нужен только для stateful/swappable частей:
- `StructuredLoggingRuntime` уже живёт как runtime resource.
- `StructlogObservabilityEventSink` можно завести как singleton/factory поверх runtime logger.
- Zone adapters можно создавать factory-провайдерами или обычными dataclass-объектами в composition root.
- `ecs_transform` не должен получать зависимости через DI; его конфигурация должна быть простой и
  передаваться при сборке logging runtime.

### Внешние зависимости

На текущий этап новых runtime-зависимостей не требуется:
- `structlog` уже решает processor pipeline.
- `pydantic` и `PyYAML` уже достаточны для taxonomy/config boundary.
- `dependency-injector` уже покрывает wiring.
- `ecs-logging` не даёт достаточной выгоды как production formatter, потому что наша сложность не в
  JSON-формате, а в taxonomy, reserved keys, redaction order, zones и совместимости с текущим runtime.

Потенциальные зависимости вроде `jsonschema`, `orjson`, `loguru`, `rich` сейчас не добавляем: они либо
дублируют существующий стек, либо увеличивают поверхность поддержки до того, как стабилизирована модель.

### Guard-тесты, которые стоит завести первыми

- `ecs_transform` не мутирует входной dict, переносит `event` в `message`, выставляет `@timestamp`,
  `log.level`, `ecs.version`, `event.action`, `event.outcome`, `labels.*`.
- `ecs_transform` корректно обрабатывает foreign log без `action`, `dataset`, `stage`.
- `ExceptionDictTransformer` output превращается в `error.type`, `error.message`, `error.stack_trace`
  после redaction.
- Taxonomy YAML загружается и все action из callsite-map существуют в `actions.yaml`.
- Architecture/import-linter: ECS renderer не импортируется из domain/usecases; zone adapters не
  импортируются из domain; `common/observability` не зависит от infra/delivery.
- Reserved-field guard: call-sites не передают `component` как log kwarg, кроме controlled context binding.

### Guard-тесты для границ слоя

Эти проверки можно вводить ratchet-стратегией: сначала с явным списком known violations, затем список
сокращается, а к концу реализации становится пустым. Важно: allowlist — только временный механизм
перехода, не архитектурное разрешение.

| Проверка | Инструмент | Целевое состояние |
|---|---|---|
| `connector.common.observability` не импортирует внешние слои и runtime libs | `tests/architecture` AST + import-linter | Только stdlib и `connector.common.*` |
| `connector.domain` не импортирует `structlog`, `logging`, `connector.infra.logging` | import-linter + AST test | Ноль нарушений |
| `connector.usecases` не импортирует `structlog`, stdlib `logging`, `connector.infra.logging` | AST test с временным allowlist | Ноль нарушений к концу ECS |
| `connector.delivery.commands` не создаёт новые raw loggers | AST test: запрет `structlog.get_logger`, `logging.getLogger` | Только `ctx.logger` на переходе, затем adapters |
| Reserved kwargs не используются в log calls | AST test по `logger.*(..., component=...)` и другим reserved names | Ноль, кроме context binding/runtime |
| ECS dotted fields не собираются вне `infra/logging/ecs.py` | `rg`/AST test по строкам `event.action`, `ecs.version`, `error.type` | Только renderer/tests/docs/taxonomy |
| Zone adapters не импортируются в domain | import-linter forbidden contract | Ноль |
| Taxonomy YAML валидна и синхронна с callsite-map | unit/architecture tests | Все actions/fields загружаются, нет orphan/unknown actions |
| Logging runtime не пишет в stdout | integration test runtime sinks | JSON/human logs только stderr/file |
| Redaction стоит раньше ECS mapping | unit test processor order | `exception` и kwargs попадают в ECS уже masked |

Минимальный набор файлов для guard-тестов:
- `tests/architecture/test_observability_boundaries.py` — layer/import/reserved-key guards.
- `tests/unit/observability/test_ecs_transform.py` — pure processor contract.
- `tests/unit/observability/test_taxonomy_registry.py` — Pydantic/YAML validation.
- `tests/integration/observability/test_logging_runtime_ecs.py` — ProcessorFormatter + stderr/file path.

### Import-linter contracts, которые стоит добавить

В `pyproject.toml` текущая модель уже запрещает `domain → infra` и `usecases → infra`. Для ECS слоя
нужны более точечные контракты:

```toml
[[tool.importlinter.contracts]]
name = "observability shared kernel stays pure"
type = "forbidden"
source_modules = ["connector.common.observability"]
forbidden_modules = [
  "connector.domain",
  "connector.usecases",
  "connector.infra",
  "connector.delivery",
  "structlog",
  "pydantic",
  "yaml",
  "dependency_injector",
]

[[tool.importlinter.contracts]]
name = "core layers do not depend on logging implementation"
type = "forbidden"
source_modules = ["connector.domain", "connector.usecases"]
forbidden_modules = [
  "connector.infra.logging",
  "structlog",
]

[[tool.importlinter.contracts]]
name = "domain does not depend on observability zone adapters"
type = "forbidden"
source_modules = ["connector.domain"]
forbidden_modules = ["connector.infra.logging.zones"]
```

Если на момент добавления эти контракты падают из-за текущего legacy, фиксируем нарушения в worknote и
временно покрываем их AST-тестом с allowlist. Но финальная цель — контракты без `ignore_imports`.

### Очередь следующих решений

Дальше двигаемся не к массовой миграции call-sites, а к контракту события. Это точка, от которой
зависят порт, adapters, DI wiring, runtime renderer и guard-тесты.

1. **`ObservabilityEvent` shape.** Решить, какие поля являются обязательными в value object:
   `action`, `message`, `level`, `outcome`, `fields`, `cause/exception`, `duration_ns`. Здесь важно
   не протащить ECS dotted keys в прикладной код.
2. **Где живёт порт.** Подтвердить, нужен ли `connector/domain/ports/observability.py` сейчас или
   достаточно временного adapter API в delivery/infra до первого usecase, которому нужен sink.
   Критерий: если usecases должны эмитить события напрямую — нужен доменный Protocol; если только
   runtime/orchestrator — порт можно отложить.
3. **Zone adapter API.** Определить форму фасадов: отдельные классы по зонам
   (`RuntimeLifecycleEvents`, `PipelineStageEvents`, `VaultManagementEvents`) или один generic helper.
   Предпочтение: отдельные узкие классы, потому что они скрывают taxonomy и лучше соблюдают ISP.
4. **Pipeline lifecycle hook integration.** Решить, используем ли существующие `PipelineHooks` для
   stage start/complete/error или заводим отдельный pipeline observability adapter. Предпочтение:
   использовать hooks, не менять `StageContract` и не добавлять логи в сами стадии.
5. **Guard tests ratchet.** Сначала добавить architecture test с known violations, чтобы фиксировать
   текущее состояние и не допускать новых нарушений. Затем постепенно сокращать allowlist.
6. **Минимальный vertical slice.** После решений 1–5 реализовать маленький путь:
   runtime lifecycle event → sink → structlog kwargs → `ecs_transform` → JSON output test.

Что не делаем следующим шагом:
- не переписываем все logger call-sites;
- не добавляем новый pipeline stage ради логирования;
- не делаем generic observability framework с множеством Protocol до первого реального consumer-а;
- не добавляем внешние зависимости, пока не доказана необходимость.

### Контракт событий — принято

Событийный контракт должен описывать **намерение**, а не конечный ECS JSON. Это принципиально: как
только usecase/command начнёт собирать `event.action`, `error.type`, `labels.*` и `ecs.version`
руками, observability слой перестанет быть отдельным слоем.

#### Что уже есть в проекте

- `domain/reporting/events.py` использует immutable dataclass-события. Это хороший паттерн для
  value object: дешёвый, типизированный, без runtime-зависимостей.
- `domain/ports/topology/observability.py` уже содержит `TopologyEventSink`: узкий sink с
  `enabled(level)` и `emit(level, event, payload)`. Это правильный seam, но для ECS он слишком
  строковый: `event` и `payload` не знают taxonomy.
- `actions.yaml` уже хранит `name`, `default_level`, `outcome`, `kind`, `required_fields`.
  Значит default level/kind/outcome-policy должны подтягиваться из registry, а не дублироваться
  в каждом call-site.
- `PipelineHooks` уже являются корректной точкой stage lifecycle. Логирование стадий нельзя класть
  внутрь stage implementations и нельзя менять `StageContract` ради observability.

#### Рекомендуемая модель

Используем двухслойную модель:

1. **Generic transport event** — один внутренний контракт observability слоя:

```python
@dataclass(frozen=True)
class ObservabilityEvent:
    action: str
    message: str
    fields: Mapping[str, LogFieldValue] = field(default_factory=dict)
    level: LogLevel | None = None
    outcome: EventOutcome | None = None
    kind: EventKind | None = None
    duration_ns: int | None = None
    error: ObservabilityError | None = None
```

2. **Semantic zone ports/adapters** — внешний API для usecases/delivery:

```python
class PipelineStageEvents(Protocol):
    def stage_started(self, *, stage: str) -> None: ...
    def stage_completed(self, *, stage: str, duration_ns: int, item_count: int) -> None: ...
    def stage_failed(self, *, stage: str, duration_ns: int, exc: BaseException) -> None: ...
```

Так прикладной код не знает action names, ECS dotted fields и processor details. Он вызывает
семантический метод зоны, а adapter строит `ObservabilityEvent`.

#### Почему не один публичный `emit(action=...)`

Один generic `ObservabilityEventSink.emit(event)` хорош как **внутренний транспорт**, но плох как
публичный usecase-facing API:
- usecase начнёт знать строковые action names из taxonomy;
- при переименовании action придётся менять бизнес-оркестрацию;
- появится соблазн прокидывать raw ECS kwargs через `fields`;
- ISP нарушается: всем consumer-ам будет доступен весь словарь событий, хотя им нужна одна зона.

Поэтому компромисс:
- внутри observability один generic sink;
- наружу по мере миграции добавляются узкие zone-specific Protocols;
- первый такой Protocol заводим только для реального consumer-а, не создаём все 16 зон заранее.

#### Где жить классам

| Объект | Целевое место | Почему |
|---|---|---|
| `LogLevel`, `EventOutcome`, `EventKind`, `ObservabilityError`, `ObservabilityEvent` | `connector/common/observability/events.py` | stdlib-only value objects; ими могут пользоваться ports и adapters |
| `ObservabilityEventSink` | если нужен usecases: `connector/domain/ports/observability.py`; иначе временно в `infra/logging/event_sink.py` как internal Protocol | порт в domain нужен только когда usecase зависит от sink |
| Zone-specific Protocols | `connector/domain/ports/observability.py` или подпакет `domain/ports/observability/` при росте | Protocol only; usecases зависят от абстракции |
| Zone adapter implementations | `connector/infra/logging/zones/*.py` | выбирают action/outcome/fields и пишут в generic sink |
| `StructlogObservabilityEventSink` | `connector/infra/logging/event_sink.py` | единственное место, где event object превращается в logger kwargs |
| `TaxonomyRegistry` loader | `connector/infra/logging/taxonomy.py` на текущем этапе | Pydantic/YAML не тянем в `common` |

#### Предлагаемые value types

```python
class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class EventOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNKNOWN = "unknown"

class EventKind(str, Enum):
    EVENT = "event"
    METRIC = "metric"
    STATE = "state"

LogScalar = str | int | float | bool | None
LogFieldValue = LogScalar | tuple[LogScalar, ...]

@dataclass(frozen=True)
class ObservabilityError:
    type: str | None = None
    message: str | None = None
    code: str | None = None
    exception: BaseException | None = field(default=None, repr=False, compare=False)
```

`ObservabilityError.exception` нужен для stack trace через `ExceptionDictTransformer`; safe
`type/message/code` нужны для случаев без живого exception object. Sink должен передавать exception
в structlog как `exc_info=(type(exc), exc, exc.__traceback__)`, а не сериализовать его в `fields`.

#### Правила для `fields`

`fields` — это не ECS dict и не escape hatch для всего подряд:
- ключи в `fields` должны быть доменными именами (`stage`, `record_ref`, `diag_code`,
  `item_count`, `scope`, `duration_ns`), а не dotted ECS keys;
- reserved keys (`component`, `labels`, `event`, `error`, `ecs.version`, `log`, `service`, `host`,
  `process`, `exception`) запрещены;
- значения — только JSON-safe scalar/tuple; большие dict/list payload запрещены, если они не прошли
  отдельный sanitizer;
- секретные значения не передаются вообще; допускаются только fingerprint/count/reference.

Маппинг `fields → ECS` делает `StructlogObservabilityEventSink` и `ecs_transform`:
- `duration_ns` → `event.duration`;
- `stage` → `nexus.stage.name` или agreed labels/nexus field по taxonomy;
- `record_ref` → соответствующее safe поле taxonomy;
- неизвестное безопасное поле → `labels.<name>`.

#### Кто выставляет level/outcome/kind

Порядок разрешения:

1. Zone adapter может явно задать `outcome`, когда знает результат (`success/failure/unknown`).
2. Zone adapter обычно не задаёт `level` и `kind`, если они есть в `actions.yaml`.
3. `StructlogObservabilityEventSink` делает lookup action в `TaxonomyRegistry` и применяет
   `default_level`, `kind`, `outcome` policy.
4. Если action неизвестен registry, в dev/test это ошибка guard-теста; в production sink не должен
   валить команду, а должен залогировать событие best-effort с переданным или fallback level.

#### Pipeline lifecycle

Для стадий используем существующие `PipelineHooks`:
- `on_stage_start(stage)` → `PipelineStageEvents.stage_started(stage=stage)`;
- `on_stage_complete(stage, ms, stats)` → `stage_completed(duration_ns=int(ms * 1_000_000), item_count=stats["items"])`;
- `on_stage_error(stage, exc, ms)` → `stage_failed(..., exc=exc)`;
- `on_stage_abort(stage, ms)` → отдельное событие `stage-aborted`, если оно есть/будет в taxonomy.

Это сохраняет lazy pipeline semantics: событие stage start появляется только при первом pull, completion
только при полном consumption. Логи не добавляются в сами stage classes.

#### Решение, которое предлагаю принять

- Принять `ObservabilityEvent` как frozen dataclass в shared kernel.
- Принять generic `ObservabilityEventSink` как внутренний транспортный порт.
- Для usecases не давать прямой `emit(action=...)`; вместо этого вводить узкие zone-specific Protocols
  по мере миграции конкретной зоны.
- Первый vertical slice делать на runtime/pipeline lifecycle, потому что там уже есть `PipelineHooks`
  и понятные start/complete/fail события.
- `event.category`/`event.type` пока не включать в базовый контракт: текущий machine taxonomy хранит
  `kind`, но не хранит category/type. Добавим позже, если они появятся в YAML как обязательная часть.

---

## Открытые темы

### 1. ✅ RESOLVED — Коллизии «контекст vs call-site» для `component`/`dataset`
**Механизм (проверено, structlog 26.1.0).** `merge_contextvars` делает `event_dict.setdefault(k, ctx[k])`
→ contextvar пишется только если ключа ещё нет. Сила: `call-site kwarg > .bind() > contextvar (fallback)`.
Значит call-site `component=` **перетирает** канонический контекстный компонент, и каноника теряется
(setdefault её пропустил).

**Очаги (по коду):**
- `usecases/management/vault/usecase.py:85,120,169,200,222` — `component="vault_management"` (не `ServiceComponent`;
  логгер `structlog.get_logger(__name__)` без bound-компонента → контекст `vault` перетирается).
- `infra/dictionaries/telemetry.py:135,188,218` — `component="dictionary"` (компонента нет; работает внутри enrich/cache).
- `delivery/commands/obs_artifacts.py:90,99,150,160` — `component=opts.component.value` (семантическая перегрузка:
  эмитент = OBSERVABILITY, а кладётся *запрашиваемый* компонент).
- `dataset=` дублируется (cache/resolve сервисы) — обычно тем же значением, безвредно, но хрупко.
- `scope=`/`op=` — НЕ коллизии (собственные поля, contextvar нет).

**Почему критично.** Файловый хендлер per-process: `emit()` пишет в `layout.log_file(runtime.component)`
независимо от per-record `component`. Запись с `component="dictionary"` во время enrich уедет в
`var/logs/enricher/` → `labels.component` врёт про размещение и ломает ES-корреляцию.

**Модель (decided).** `component` = идентичность запущенной единицы (`ServiceComponent`), **только из
контекста**, per-process, = партиция файла; на call-site не передаётся. Cross-cutting подсистема
(cache/dictionary/vault/topology) = `component` только под своей командой/lifecycle; при *обращении* к
ней из запущенного компонента — `scope=<subsystem>` (per-record).

**Прецедент (подтверждает).** cache метит `scope="cache"` (в `infra/cache` нет `component=`); vault/secrets
— нет `component=`, а `scope="vault"` уже есть в коде. Конвенция уже существует — аномальны только 3 места выше.

**Решение:**
- `component` зарезервирован (источник = контекст). Доступ к подсистеме → `scope=<subsystem>`.
- Правки call-sites (Фаза 2): dictionary `component="dictionary"`→`scope="dictionary"`;
  vault-usecase — убрать `component="vault_management"` (контекст = vault), оставить `op=`;
  obs_artifacts `component=opts.component.value`→`target_component=` (→ `labels.target_component`).
- Enforcement: `ecs_transform` берёт `component` из контекста (reserved-ключ); guard-тест
  `labels.component ∈ ServiceComponent`.

**Связанный долг (ортогонален, НЕ блокирует).** dictionary синхронно завязан на enrich, а по сути —
стадия-независимая подсистема (известный просчёт). Логи-конвенция стабильна к будущему развязыванию:
при вызове из стадии останется `scope=dictionary`; `component=dictionary` появится только если dictionary
получит собственный запуск/команду. Зафиксировать как отдельную задачу вне ECS-скоупа.

### 2. 🟠 Семантика `scope` / `stage` / `component` / `op`
Сейчас в коде разнобой: `scope="cache"`, `stage=…`, `component="vault_management"`, `op="start"/"success"`.
Нужны чёткие определения и таргеты:
- `component` → `labels.component` (= `ServiceComponent`, из контекста).
- `stage` → `labels.stage` (стадия пайплайна).
- `scope` → `labels.scope` (под-область внутри компонента) — **или** схлопнуть в `stage`? Обсудить.
- `op="start"/"success"` — это фактически `event.action`+`event.outcome`. **Рекомендация:** в Фазе 1
  оставить как `labels.op` (catch-all), в Фазе 2 мигрировать на `action`/`outcome`.

### 3. 🟠 `message` vs `event.action` — читаемость сообщения
Часть call-sites шлёт **event-code как сообщение**: `logger.info("vault_mgmt_init", …)`. После
переименования `event → message` поле `message` станет машинным кодом, а не человекочитаемым.
**Рекомендация / правило:** `message` — человекочитаемое («Vault init started»); машинный код —
в `event.action` (`vault-init-started`). Это правило уже в dev-doc; в Фазе 2 чиним такие call-sites.
В Фазе 1 — не ломаем (оставляем как есть, message = текущая строка).

### 4. 🔴 `error.*` из `ExceptionDictTransformer`
`ExceptionRenderer(ExceptionDictTransformer())` кладёт под `exception` **список** (цепочка
`__cause__`/`__context__`), а ECS `error.*` — singular. Нужно решить:
- `error.type`/`error.message` ← какое звено? **Рекомендация:** внешнее (последнее) исключение —
  то, что реально всплыло.
- `error.stack_trace` ← собранный человекочитаемый трейс всей цепочки в одну строку.
- Цепочка причин — терять или сложить в `error.stack_trace`? **Рекомендация:** в stack_trace.
- Инвариант: `ecs_transform` читает **уже redacted** `exception` (redaction раньше в цепочке) — нельзя
  лезть в сырой `exc_info` повторно.

### 5. 🟠 `log.logger` — схема имён
Нужен `structlog.stdlib.add_logger_name` в цепочке. Сейчас `get_logger` зовёт логгер
`nexus.{component.value}`. Это и будет `log.logger`? Гранулярности «по компоненту» хватает, или хотим
по модулю (`nexus.normalizer.mapper_core`)? **Рекомендация:** оставить `nexus.{component}` —
совпадает с партиционированием артефактов; модульная гранулярность избыточна.

### 6. 🟠 Конфиг-поверхность: что значит `format: json`?
Сейчас `observability.logging.sinks.{console,file}.format ∈ {json, text}`. Варианты:
- (A) `json` **становится** ECS-json (ECS — единственная форма машинного вывода). Проще, меньше
  сущностей. **Рекомендация.**
- (B) добавить третье значение `ecs` и оставить «сырой json» как escape hatch на миграцию.

Связанные мелочи: `service.environment` — откуда (новый `observability`/`runtime` конфиг: prod/staging/
dev)? `ECS_VERSION` — константа в `ecs.py` (не конфиг). Обсудить, нужен ли вообще «сырой json».

### 7. 🟠 Foreign-логи (httpx, sqlite3) в ECS
Через `foreign_pre_chain` они получают контекст (`run_id` из contextvars — если бинд активен) и пройдут
через `ecs_transform` в общем формате. Но у них **нет** наших `action`/`dataset`/`stage`. Нужно:
- убедиться, что `ecs_transform` не падает на «чужом» dict (есть `event`/`level`, нет наших kwargs);
- решить, мапить ли их `event` → `message` так же (да);
- их `log.logger` будет `httpx`/`sqlite3` — это полезно, оставляем.
**Открыто:** нужен ли foreign-логам `event.dataset` (вряд ли — бинд контекста его даёт, если активен).

### 8. 🟡 Формат `@timestamp`
`TimeStamper(fmt="iso", utc=True)` даёт ISO-8601 (offset `+00:00`). ES принимает. **Открыто:**
нормализовать к суффиксу `Z` для косметики/совместимости дашбордов или оставить `+00:00`. Низкий риск.

### 9. 🟠 Тест-инфраструктура совместимости
- Где живёт вендоренный срез ECS-полей: `tests/.../observability/ecs_fields_8_11.{yml|json}`? Формат?
  **Рекомендация:** один JSON со списком `{name, type}` только эмитируемых полей — компактно, легко
  diff'ить при апгрейде.
- Autouse-фикстура: снапшот/восстановление root-logger (handlers/level/propagate) +
  `structlog.reset_defaults()` — `build_structured_logging_runtime(root_logger_name="")` мутирует
  глобальный logging-стейт (отмечено в observability-тестах).
- Golden: один прогон событий → точный ожидаемый ECS-dict (info/warning/error-с-исключением + foreign).

### 10. ✅ ~~`LegacyCompatibleStructlogLogger`~~ — снят (адаптера уже нет)
Проверено по коду: `LegacyCompatibleStructlogLogger` и весь legacy-фасад (`setup.py`,
`log_event`/`create_command_logger`/`EnsureFieldsFilter`) **удалены** в `82ae47b` (Stage Z). Команды
берут логгер через `structlog.get_logger(__name__)` / `runtime.get_logger(component=…)`. Legacy-пути,
через который надо было бы прогонять `ecs_transform`, не существует — тема закрыта.
**Побочка:** dev-doc `observability-logging.md` (стр. 58/96/131/260) и skill `observability` всё ещё
описывают удалённый класс — это doc drift, нужно вычистить отдельно (вне ECS-скоупа).

### 11. 🟡 Фаза 2 — порядок наполнения call-sites
Где вводим `action`/`outcome`/`duration_ns`:
- lifecycle-точки: `orchestrator.py` (run start/complete), стадии (stage start/complete/fail).
- `duration_ns` через `time.perf_counter_ns()` на границах стадий — где именно (PlanningPipeline?).
- Порядок компонентов: предлагаю начать с orchestrator (run-*) и одной стадии как образца, затем
  размножить. vault/cache — вторым заходом (там legacy `op=`).

### 12. ⚪ Не путать версии схем
`schema_version="1.0"` (наш лог-конверт) → `labels.schema_version`; `ecs.version="8.11"` (ECS);
плюс есть `schema_version` в `ReportEnvelope.meta` (reporting — другое). Зафиксировать в dev-doc,
что это **три разные** версии, чтобы не слить.

### 13. 🟡 stdlib `%s`-форматирование вместо structlog kwargs
Найдено при инвентаризации call-sites: два места логируют в стиле stdlib `logger.warning("… %s …", a, b)`
вместо structlog kwargs: `domain/transform/resolve_core.py:200` (merge_policy overwrite) и
`infra/cache/dsl_adapter.py:129` (cache sync value expr). Их `message` несёт интерполяцию, а не чистый
текст → в ECS поля не разложатся. Привести к structlog (`logger.warning("…", field=a, codes=b)`) при
наполнении call-sites в Фазе 2.

---

## Журнал решений

| Дата | Тема | Решение |
|------|------|---------|
| 2026-06-09 | — | Worknote заведён; темы 1–12 поставлены на обсуждение |
| 2026-06-09 | Тема 10 | Закрыта: `LegacyCompatibleStructlogLogger` удалён в `82ae47b` (Stage Z); адаптера нет. Выявлен doc drift в `observability-logging.md` + skill |
| 2026-06-10 | Тема 1 | RESOLVED: `component` — только из контекста (per-process = партиция файла); доступ к подсистеме → `scope=<subsystem>` (прецедент cache/vault). Правки call-sites (vault-usecase/dictionary/obs_artifacts) + reserved-ключ в `ecs_transform` + guard-тест. Dictionary-coupling — отдельный долг, ортогонален |
| 2026-06-10 | Поля/действия | В `ecs-logging-conventions.md` добавлены: «Анатомия лог-строки», полная карта call-site→event.action→outcome (92 call-sites), дополнен `error.*` (ручные `error`/`error_type`/`diag_code` + `error.code`). Карта = источник `EventAction` enum (Фаза 2) |
| 2026-06-14 | Старт реализации | Рабочий порядок: сначала границы модулей и guard-тесты, затем `ecs_transform`, taxonomy validation, один вертикальный срез зоны. ADR остаётся только для окончательно принятых решений |
| 2026-06-14 | `ecs-logging` | Не используем как production formatter; новых runtime-зависимостей на текущий этап не добавляем |
| 2026-06-14 | Контракт событий | ACCEPTED: `ObservabilityEvent` — frozen dataclass intention-object; generic `ObservabilityEventSink` — внутренний transport; наружу для usecases выдаются узкие zone-specific Protocols/adapters. Первый vertical slice — runtime/pipeline lifecycle через `PipelineHooks` |

---

## Связанные документы

- [OBSERVABILITY-DEC-003](../../adr/observability/OBSERVABILITY-DEC-003-ecs-renderer-and-field-mapping.md) — решение
- [OBSERVABILITY-PROBLEM-003](../../adr/observability/OBSERVABILITY-PROBLEM-003-non-ecs-log-shape.md) — проблема
- [ecs-logging-conventions.md](../../dev/layers/observability/ecs-logging-conventions.md) — семантика полей/уровней/действий
- [observability-logging.md](../../dev/layers/observability/observability-logging.md) — текущий runtime/процессоры/redaction
- `connector/infra/logging/runtime.py`, `connector/infra/logging/ecs.py` (новый)

---

## План Phase 1

### Цель фазы

Собрать первый production-ready срез ECS-логгирования так, чтобы:
- все машинные JSON-логи проходили через единый `ecs_transform`;
- observability-логика была локализована внутри своей зоны, без протекания ECS-деталей в стадии и
  прикладные use case;
- у нас появился минимальный, но устойчивый runtime-контур для дальнейшего наполнения зон
  (`pipeline`, `vault`, `cache`, `apply`) без пересборки архитектуры;
- архитектурные границы были защищены guard-тестами и import-boundary проверками заранее, а не постфактум.

### Что именно считаем результатом Phase 1

Phase 1 не пытается сразу покрыть весь проект новыми `event.action` call-site'ами. Фаза закрывает
каркас и первый вертикальный срез:
- ECS renderer/transform в logging runtime;
- контракт внутреннего observability-события;
- внутренний sink/adapter слой внутри observability;
- один опорный lifecycle-срез через runtime/pipeline hooks;
- guard-тесты на границы, reserved keys и processor order.

Иными словами: к концу фазы у нас должен быть не «весь проект уже переложен на ECS», а корректная
архитектурная ось, через которую последующие изменения будут добавляться без расползания ответственности.

### Архитектурное устройство Phase 1

#### 1. Внутренний контракт observability

Базовый объект события остаётся intention-level контрактом, а не финальным ECS-документом:
- `connector/common/observability/events.py`
- `ObservabilityEvent` = frozen dataclass
- содержит принятые атрибуты контракта: `action`, `message`, `fields`, `level`, `outcome`, `kind`,
  `duration_ns`, `error`
- `dataset`, `stage`, `diag_code` и прочие доменные атрибуты живут внутри `fields`, а не как
  ad-hoc top-level поля
- не содержит ECS-specific dotted keys как часть публичного API

Это важно: ECS-форма должна рождаться в renderer/transform слое, а не быть формой общения между
use case, стадиями и адаптерами.

#### 2. Внутренний transport внутри observability

Внутри observability разрешён generic sink:
- `connector/common/observability/ports.py`
- `ObservabilityEventSink` принимает `ObservabilityEvent`

Но наружу он не торчит как глобальный порт для всех зон. Для потребителей будут узкие фасады:
- `PipelineLifecycleLogger`
- далее отдельно `VaultObservabilityPort`, `CacheObservabilityPort`, `ApplyObservabilityPort`

То есть generic sink используется как внутренняя транспортная ось observability-пакета, а не как
универсальный «лог-порт на всё приложение».

Для Phase 1 этого достаточно: отдельный `domain/ports/observability.py` не нужен, потому что первый
vertical slice идёт через orchestrator / lifecycle hooks и ещё не вводит самостоятельного
usecase-facing consumer-а. Если такой consumer появится во Phase 2, тогда и вводится отдельный
domain/usecase-facing port.

#### 3. Zone-specific adapters на входе

Наружные компоненты не должны знать:
- как выглядит ECS;
- какие поля являются reserved;
- как устроен structlog/runtime;
- как собирается `event.kind`, `log.logger`, `ecs.version` и т.д.

Поэтому Phase 1 вводит узкий фасад для pipeline lifecycle:
- адаптер в observability слое принимает семантически понятные аргументы;
- строит `ObservabilityEvent`;
- отправляет его во внутренний sink;
- sink уже переводит событие в structlog вызов/runtime emission.

#### 4. ECS renderer как последняя трансформация перед JSONRenderer

Ответственность `ecs_transform`:
- принять event dict после context merge, level/timestamp enrichment, redaction и exception rendering;
- нормализовать запись в ECS shape;
- перенести наши поля в `event.*`, `labels.*`, `error.*`, `service.*`, `process.*`, `trace.*`;
- защитить reserved keys (`component`, системные ECS поля, processor meta);
- не падать на foreign/stdlib логах;
- оставить text/human renderer вне ECS-обязательств.

Принцип: весь ECS-aware mapping живёт только здесь и в связанных helper-объектах этой же зоны.

#### 5. Runtime wiring и процессорный конвейер

Phase 1 фиксирует целевой порядок JSON-конвейера:
1. context merge / runtime meta
2. stdlib/structlog metadata
3. exception normalization
4. redaction
5. cleanup processor meta
6. `ecs_transform`
7. `JSONRenderer`

Ключевой инвариант: redaction идёт до ECS render, чтобы masking происходил ещё на сырых значениях,
а `ecs_transform` уже работал с безопасным payload.

#### 6. Точка входа первого vertical slice

Первый slice берём не с vault/cache, а с runtime/pipeline lifecycle:
- run started / run completed;
- stage started / stage completed / stage failed;
- один seam для интеграции: `PipelineHooks` или ближайшая lifecycle orchestration boundary.

Почему именно так:
- это наименьший риск по бизнес-логике;
- даёт максимальную видимость в логах сразу;
- задаёт шаблон для последующего подключения остальных зон;
- не требует встраивать логгирование внутрь stage core.

### Модули и ответственность в Phase 1

#### `connector/common/observability/`
- event contract (`ObservabilityEvent`)
- internal generic sink protocol + zone-facing narrow ports для lifecycle
- без structlog, без runtime wiring, без file/handler concerns

#### `connector/infra/logging/ecs.py`
- `ecs_transform`
- taxonomy lookup helpers / validators, если они действительно нужны на runtime-path
- reserved-key policy
- field mapping helpers

#### `connector/infra/logging/runtime.py`
- processor pipeline wiring
- вызов `ecs_transform` только на JSON sinks
- сохранение текущих invariants по stderr/file transport

#### `connector/infra/observability/` или `connector/infra/logging/`
- sink implementation, которая принимает `ObservabilityEvent` и эмитит structlog запись
- тонкие adapter implementations для pipeline lifecycle

#### `connector/delivery/cli/containers.py`
- только DI wiring
- создание runtime/sink/adapters
- никакой ECS mapping логики

#### `connector/usecases/` / pipeline orchestration
- только вызов узкого lifecycle-порта
- без прямого structlog kwargs, без dotted ECS keys, без знания про taxonomy storage

### Что входит в реализацию Phase 1

1. Ввести минимальный event contract и внутренний sink внутри observability зоны.
2. Реализовать `ecs_transform` и подключить его в JSON runtime pipeline.
3. Определить и зафиксировать reserved keys / ownership полей.
4. Провести первый lifecycle slice через pipeline hooks/orchestrator boundary.
5. Написать guard-тесты, которые запрещают разнос логики ECS за пределы observability.
6. Подготовить import-linter/architecture проверки, отражающие целевую модель.

### Что сознательно НЕ входит в Phase 1

- массовый перенос всех existing log call-site'ов на новый контракт;
- покрытие всех зон (`vault`, `cache`, `apply`, `dictionaries`) новыми адаптерами;
- полный enum/class hierarchy для всех `event.action`;
- расширение на `event.category` / `event.type`;
- миграция текстового console renderer в ECS-представление;
- внешние зависимости ради formatter/runtime, если текущий слой решает задачу сам.

### Порядок реализации

1. Зафиксировать файловую карту и финальные границы модулей в коде и тестах.
2. Ввести event contract и внутренний sink без подключения call-site'ов.
3. Реализовать `ecs_transform` как чистый processor с unit/golden тестами.
4. Подключить `ecs_transform` в runtime только для JSON sinks.
5. Добавить pipeline lifecycle adapter и один вертикальный slice.
6. Добить guard-тесты на запрет обходных путей.
7. После стабилизации каркаса переходить к наполнению зон во Phase 2.

### Checklist Phase 1

- [ ] Создан минимальный `ObservabilityEvent` contract в observability package.
- [ ] Определён внутренний `ObservabilityEventSink` и он не экспортируется как глобальный app-wide порт.
- [ ] Для pipeline lifecycle заведён узкий zone-specific adapter/port.
- [ ] `ecs_transform` реализован как чистый processor без побочных эффектов.
- [ ] `ecs_transform` устойчив к foreign/stdlib логам и неполным event dict.
- [ ] JSON file sink использует `ecs_transform`.
- [ ] JSON console sink использует `ecs_transform`.
- [ ] Text/human sink не зависит от ECS mapping.
- [ ] Redaction выполняется до `ecs_transform`.
- [ ] Reserved keys policy совпадает с полным множеством structural roots и покрыта тестом.
- [ ] `fields` запрещает dotted keys и structural-root aliases, это покрыто тестом.
- [ ] Processor order зафиксирован тестом.
- [ ] Pipeline lifecycle slice проходит через hooks/orchestration seam, а не через stage core.
- [ ] В stage core/use case нет прямого знания о dotted ECS keys.
- [ ] Добавлен guard-тест на запрет прямого ECS field mapping вне observability зоны.
- [ ] Добавлен guard-тест на запрет прямого structlog/event-emission в неподходящих слоях, где должен идти adapter.
- [ ] Import-linter/architecture checks отражают целевые границы observability слоя.

### Finally Checkup для завершения Phase 1

Фаза считается завершённой, если одновременно выполняются все условия:

- [ ] Любой JSON-лог проекта проходит через один и тот же `ecs_transform`.
- [ ] Ни один use case, stage core или domain service не формирует ECS-dotted fields вручную.
- [ ] Наружные зоны взаимодействуют с observability через узкий adapter/port, а не через generic sink напрямую.
- [ ] `component`, `service.*`, `ecs.version`, `event.kind`, `labels.*` ownership закреплены внутри observability слоя.
- [ ] `fields` принимает только short-name aliases / безопасные доменные ключи и не принимает dotted ECS keys.
- [ ] Redaction, exception rendering и ECS transform выстроены в корректном порядке и это защищено тестом.
- [ ] Foreign/stdlib логи не ломают JSON pipeline и не требуют специальных call-site patch'ей.
- [ ] Первый lifecycle slice (`run-*`, `stage-*`) пишет ожидаемые ECS-события end-to-end.
- [ ] Architecture/import guard'ы зелёные и блокируют расползание логики за границы observability.
- [ ] ADR не расходится с worknote: в ADR только принятые решения, в worknote осталась реализационная детализация.

### Критерий готовности к Phase 2

После завершения этой фазы мы должны быть в состоянии:
- подключать новые зоны по образцу `pipeline lifecycle adapter -> ObservabilityEvent -> sink -> ecs_transform`;
- расширять taxonomy и field mapping без правок в stage core;
- переносить legacy call-site'ы по одному кластеру за раз, не ломая runtime и не перепридумывая архитектуру.
