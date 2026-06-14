# OBSERVABILITY-DEC-003: ECS JSON rendering and logging taxonomy boundary

> **Статус**: Принято
> **Дата принятия**: 2026-06-14
> **Решает проблему**: [OBSERVABILITY-PROBLEM-003](./OBSERVABILITY-PROBLEM-003-non-ecs-log-shape.md)
> **Развивает**: [OBSERVABILITY-DEC-001](./OBSERVABILITY-DEC-001-structlog-as-standard.md) и
> [OBSERVABILITY-DEC-002](./OBSERVABILITY-DEC-002-per-component-prod-observability-layout.md)
> **Участники решения**: @xorex-LC

---

## Контекст

После DEC-001/DEC-002 приложение уже пишет структурированные JSON-логи через `structlog`, разделяет
stdout/stderr, применяет redaction и раскладывает runtime-артефакты по `ServiceComponent`.
Оставшаяся проблема: JSON-форма не соответствует Elastic Common Schema (ECS), поэтому Elasticsearch
требует ingest-side переименований или получает нестабильные поля.

Задача этого решения - привести **только финальный JSON-вывод** к ECS и одновременно зафиксировать,
где живёт taxonomy полей и событий. Транспорт, layout, contextvars-корреляция, redaction,
человекочитаемые sink-и и lifecycle observability-артефактов остаются в рамках DEC-001/DEC-002.

---

## Решение

Ввести один финальный structlog processor `ecs_transform` (`dict -> dict`) и включать его только для
JSON sink-ов непосредственно перед `JSONRenderer` внутри `ProcessorFormatter`.

Целевой порядок для JSON sink:

```text
ExceptionRenderer(ExceptionDictTransformer())
  -> LogRedactionEngine.processor
  -> ProcessorFormatter.remove_processors_meta
  -> ecs_transform
  -> JSONRenderer
```

Для text/human sink-ов порядок не меняется: ECS-преобразование применяется только к JSON-выводу.

Почему именно так:

- Redaction остаётся до ECS-переименования, поэтому маскирование продолжает работать по текущим
  внутренним ключам и по traceback payload.
- `remove_processors_meta` остаётся до `ecs_transform`, чтобы служебные `_record` и
  `_from_structlog` не попали в выходной лог.
- `ecs_transform` отделён от сериализации: его можно unit-тестировать как чистую функцию без парсинга
  JSON и без поднятия CLI runtime.
- Call-site-ы не обязаны сразу эмитить dotted ECS-ключи: переход выполняется централизованно.

---

## Taxonomy sources

ADR не хранит словарь полей и `event.action`. Детальная taxonomy теперь вынесена в отдельные
машинные и человекочитаемые источники:

| Что | Где | Роль |
|---|---|---|
| Машинный словарь `event.action` | `connector/common/observability/taxonomy/actions.yaml` | Canonical action registry: action name, zone, bucket, default level, outcome policy, required fields |
| Машинный каталог полей | `connector/common/observability/taxonomy/fields/*.yaml` | Canonical field registry по зонам: ECS/nexus/labels key, type, tier, sensitivity, alias mapping для contract/runtime bridge |
| Человекочитаемая навигация | `docs/dev/layers/observability/ecs-logging-conventions.md` | Единственная canonical entry point для людей: правила уровней, зон, glossary и ссылки |
| Зональная семантика | `docs/dev/layers/observability/ecs-logging-taxonomy/zones/*.md` | Описание, где и зачем эмитится событие конкретной зоны |
| Call-site backlog | `docs/dev/layers/observability/ecs-logging-taxonomy/callsite-map.md` | Инвентарь текущих логирующих точек и миграционный план |

После реализации `ecs_transform` runtime-модуль `connector/infra/logging/ecs.py` становится
исполняемым маппером ECS-формы. Он не должен дублировать полную taxonomy: enum/registry в коде
должны строиться из YAML или проверяться контрактными тестами против YAML.

Для field mapping принимается следующая стратегия:

- runtime/event adapters работают с короткими доменными именами полей, а не с dotted ECS keys;
- соответствие `short_name -> canonical dotted key` хранится в `fields/*.yaml` через явные
  `aliases`;
- `ecs_transform` и связанные registry helpers резолвят только alias-ы, зарегистрированные в YAML;
- silent hardcode соответствий в `ecs.py` без отражения в YAML не допускается.

Правило владения:

- YAML taxonomy - источник допустимых действий и полей.
- `ecs_transform` - источник правил преобразования runtime `event_dict` в ECS JSON.
- Zone adapters - источник удобных методов для call-site-ов, чтобы бизнес-код не собирал ECS-поля
  вручную.
- ADR - только архитектурное решение и инварианты.

---

## Отношение к `ecs-logging`

Полное подключение библиотеки `ecs-logging` как production formatter не принимается на текущем этапе.
Причина не в качестве библиотеки, а в несовпадении роли: она закрывает formatter/rendering layer, а в
проекте уже есть `ProcessorFormatter` с несколькими sink-ами, redaction до render и dual transport.

Что не используем:

- `ecs_logging.StructlogFormatter` как терминальный renderer вместо нашего `ProcessorFormatter`.
- `ecs_logging.StdlibFormatter` как отдельный formatter для foreign/stdlib logs.
- Автоматическое владение shape-ом логов библиотекой в обход нашей taxonomy.

Что можно рассмотреть позже:

- Использовать библиотеку как reference/dev tool при проверке ожидаемых ECS field names.
- Сверять наши emitted dotted keys с официальным ECS field set в контрактных тестах.

Пока production dependency не добавляется. `ecs.version` и mapping rules контролируются внутри
observability logging layer.

---

## Архитектурные границы

`ecs_transform` принадлежит observability logging layer. В текущей структуре это
`connector/infra/logging/ecs.py`; при выделении отдельного пакета этот модуль должен переехать вместе
с observability runtime.

Контракты observability должны лежать выше infra-слоя:

- `connector/common/observability/` - runtime-neutral contract layer для `ObservabilityEvent`,
  `ObservabilityError`, `EventOutcome`, `EventKind`, `LogLevel` и zone-specific Protocol;
- `connector/common/observability/taxonomy/` - machine-readable YAML registry для `actions` и
  `fields`;
- `connector/infra/logging/` - runtime implementation: `ecs_transform`, taxonomy loader/helpers,
  structlog emission, formatter wiring;
- `connector/delivery/cli/containers.py` - только DI wiring concrete adapters/sinks.

Это правило нужно, чтобы `usecases` и orchestration seams могли импортировать observability
contracts без `usecases -> infra`, а `domain` не тянул `infra/logging` ради типов событий.

Запрещено:

- заводить ECS mapping в `delivery`, `usecases`, `domain` или отдельных pipeline stage modules;
- писать dotted ECS keys напрямую в каждом call-site как основной паттерн;
- дублировать словарь событий в ADR, README или коде без проверки против YAML taxonomy;
- обходить `LogRedactionEngine` новым formatter-ом или отдельной JSON-сериализацией.

Generic event sink является внутренним транспортом observability logging layer, например:

```python
class ObservabilityEventSink(Protocol):
    def emit(self, event: ObservabilityEvent) -> None: ...
```

Этот sink не является рекомендуемым публичным API для usecase-ов. Usecase-facing API должен быть
узким и zone-specific: `RuntimeLifecycleEvents`, `PipelineStageEvents`, `VaultManagementEvents`,
`ApplyTargetEvents` и т.п. Такие фасады знают семантику зоны и собирают корректный
`ObservabilityEvent`; transport/rendering остаются ниже.

Иными словами:

- внутри observability logging layer есть один generic transport sink;
- наружу для прикладного кода выдаются узкие semantic ports/adapters по зонам;
- прикладной код не вызывает `emit(action="...")` и не знает строковые `event.action`;
- новые zone-specific Protocol вводятся по мере появления реального consumer-а, а не заранее для
  всех зон taxonomy.

---

## Event contract

Runtime-событие описывает намерение, а не ECS JSON. Базовая модель:

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

Где:

- `action` - канонический `event.action` из YAML taxonomy;
- `message` - человекочитаемый текст, не машинный код события;
- `fields` - доменные поля без dotted ECS keys; ключи должны быть short-name alias-ами,
  зарегистрированными в field taxonomy;
- `level`, `outcome`, `kind` могут быть явно заданы adapter-ом, но по умолчанию подтягиваются из
  `actions.yaml`;
- `duration_ns` маппится в `event.duration`;
- `error` несёт безопасные `type/message/code` и, при наличии живого exception, передаётся sink-ом в
  structlog через `exc_info`.

`fields` не является escape hatch для raw ECS. Запрещены reserved keys и structural roots:
`@timestamp`, `message`, `component`, `ecs`, `event`, `error`, `exception`, `labels`, `log`,
`service`, `host`, `process`, `trace`, `span`, `http`, `url`, `file`, `tags`, `nexus`.
Неизвестные безопасные поля могут попасть в `labels.*`; известные поля маппятся в ECS/nexus keys
централизованно через alias registry.

Если одновременно присутствуют manual `error` и живой `exc_info`, применяется следующий precedence:

- `error.code` берётся из `ObservabilityError`, если он задан;
- `error.type` и `error.message` берутся из exception payload, если `exc_info` присутствует, иначе
  из `ObservabilityError`;
- `error.stack_trace` формируется только из `exc_info` / `ExceptionRenderer`;
- дополнительные безопасные domain-specific error fields могут быть дополнены из manual error object,
  если они не конфликтуют с exception-derived core fields.

`event.category` и `event.type` не входят в базовый контракт этого решения, потому что текущая
machine taxonomy хранит `kind`, но не хранит `category/type`. Они могут быть добавлены позже, если
появятся в YAML registry как обязательная часть taxonomy.

Для pipeline lifecycle должны использоваться существующие `PipelineHooks`: `on_stage_start`,
`on_stage_complete`, `on_stage_error`, `on_stage_abort`. Логирование stage lifecycle не добавляется
в сами stage implementations и не меняет `StageContract`.

---

## Pydantic and runtime models

Pydantic используется на trust boundary taxonomy YAML:

- `ActionTaxonomyEntry` / `ActionTaxonomyRegistry` для `actions.yaml`;
- `FieldTaxonomyEntry` / `FieldTaxonomyRegistry` для `fields/*.yaml`;
- validators для kebab-case action names, уникальности ключей, допустимых `zone`, `bucket`,
  `default_level`, `outcome`, `kind`, `ecs_type`, `owner`, `tier`, alias uniqueness.

Runtime hot path не должен валидировать каждую log-запись через Pydantic. Для runtime-событий
достаточно `dataclass(frozen=True)` и `StrEnum`/`Literal`-типов, а корректность поддерживается
unit/contract tests.

---

## Implementation plan

### Phase 1: ECS renderer contract

Код:

| Файл | Изменение |
|---|---|
| `connector/infra/logging/ecs.py` | Новый `ecs_transform`, ECS constants, field mapping, error mapping, catch-all |
| `connector/infra/logging/runtime.py` | Вставить `ecs_transform` только перед JSONRenderer; добавить logger name processor |
| `connector/infra/logging/README.md` | Зафиксировать processor order и boundary ECS слоя |

Минимальные инварианты Phase 1:

- JSON logs contain `@timestamp`, `message`, `log.level`, `log.logger`, `ecs.version`,
  `service.name`.
- `event` как строковое сообщение не остаётся root key; оно становится `message`.
- Unknown business kwargs go under `labels.*` or an approved project namespace.
- Text sinks remain unchanged.
- Redaction still happens before ECS transformation.

### Phase 2: Taxonomy registry and guards

Код:

| Файл | Изменение |
|---|---|
| `connector/common/observability/taxonomy/` | Оставить YAML source of truth |
| `connector/infra/logging/taxonomy.py` или будущий package module | Pydantic loader/registry для YAML taxonomy |
| `tests/unit/.../test_ecs_taxonomy.py` | Contract tests YAML registry, action names, field keys, duplicates |

Минимальные инварианты Phase 2:

- `actions.yaml` валидируется как registry.
- Все `required_fields` action-ов существуют в field registry.
- Все field keys имеют разрешённый root (`ecs`, `event`, `log`, `error`, `trace`, `service`,
  `span`, `host`, `process`, `file`, `http`, `url`, `nexus`, `labels`, `tags`, `@timestamp`).
- Все alias-ы глобально уникальны и резолвятся в один canonical field key.
- Sensitive fields не допускают raw-value logging policy.

### Phase 3: Event contract and zone adapters

Начинать с зон, где уже есть стабильные call-site-ы:

1. Zone 1: Runtime Orchestrator / CLI Lifecycle.
2. Zone 2: Command-Specific Delivery Lifecycle.
3. Zone 12: Vault Management Lifecycle.

Каждая zone adapter должна принимать domain/usecase DTO или явно типизированные параметры и
эмитить `ObservabilityEvent` через общий sink. Она не должна знать про `ProcessorFormatter`,
файлы логов, redaction или Elasticsearch.

Первый vertical slice должен пройти путь:

```text
zone-specific method -> ObservabilityEvent -> ObservabilityEventSink
  -> structlog kwargs -> ecs_transform -> JSONRenderer
```

---

## Validation

Unit tests:

- `ecs_transform` maps core structlog keys to ECS dotted keys.
- `ecs_transform` maps exception dict to `error.*` after redaction.
- unknown fields are moved to `labels.*` or approved `nexus.*`.
- no unknown root keys escape the transformer.
- JSON formatter uses `ecs_transform`; text formatter does not.
- logger name is present in JSON logs.

Taxonomy contract tests:

- action names are unique kebab-case values.
- field keys are unique dotted paths.
- every action `required_fields` entry exists in field registry.
- every action zone has a matching zone document or approved migration status.
- YAML `ecs_version` values match the runtime `ECS_VERSION`.

Architecture/import guards:

- observability logging modules do not import `connector.delivery` or `connector.usecases`.
- `domain` does not import ECS/logging modules.
- future observability package boundary should allow host adapters for config/DI/SQLite, but not
  reverse imports from package to application delivery code.

Operational smoke:

- run a CLI command with JSON console sink;
- verify stderr lines are valid JSON;
- verify stdout remains presenter-only;
- verify secrets in event fields and traceback text are redacted.

---

## Risks

| Риск | Митигация |
|---|---|
| Drift между YAML taxonomy и runtime enums/mapping | Contract tests: YAML registry vs code constants |
| Mapping explosion в Elasticsearch из-за произвольных kwargs | catch-all under `labels.*`, scalar/JSON-string coercion, no unknown root keys test |
| Security regression в traceback redaction | processor order test: redaction before `ecs_transform` |
| ECS fields start appearing in business layers | import-linter/architecture tests and zone adapters |
| Incomplete `event.action` coverage during migration | Phase 1 accepts valid ECS shape first; Phase 3 migrates zones incrementally |

---

## Follow-up

Отдельно от renderer boundary остаётся инфраструктурное решение по Elasticsearch templates:

- reserved ECS-поля должны опираться на официальный ECS component template, а не на вручную
  сопровождаемый кастомный mapping;
- project-specific mapping должен жить только в отдельном template для `nexus.*` и, при
  необходимости, ограниченного набора `labels.*`;
- стратегию index template / component template нужно оформить отдельным DEC или follow-up design note
  до production rollout в Elasticsearch.

---

## Влияние на компоненты

| Компонент | Влияние |
|---|---|
| `connector/infra/logging/runtime.py` | Adds ECS processor for JSON sinks |
| `connector/infra/logging/redaction.py` | No behavior change; remains before ECS transform |
| `connector/common/observability/taxonomy/` | Becomes machine-readable contract for actions/fields |
| `docs/dev/layers/observability/ecs-logging-taxonomy/` | Remains human-readable semantic catalog and migration backlog |
| `delivery/cli/containers.py` | Later wires event sink and zone adapters through `ObservabilityContainer` |
| call-sites | Phase 1 no broad changes; later migrate through zone adapters |

---

## Связанные документы

- [OBSERVABILITY-PROBLEM-003](./OBSERVABILITY-PROBLEM-003-non-ecs-log-shape.md)
- [OBSERVABILITY-DEC-001](./OBSERVABILITY-DEC-001-structlog-as-standard.md)
- [OBSERVABILITY-DEC-002](./OBSERVABILITY-DEC-002-per-component-prod-observability-layout.md)
- [ECS Logging Conventions](../../dev/layers/observability/ecs-logging-conventions.md)
- [Event Action Dictionary](../../dev/layers/observability/ecs-logging-taxonomy/event-action-dictionary.md)
- [Field Catalog](../../dev/layers/observability/ecs-logging-taxonomy/field-catalog.md)
- [Call-Site Map](../../dev/layers/observability/ecs-logging-taxonomy/callsite-map.md)
- `connector/common/observability/taxonomy/actions.yaml`
- `connector/common/observability/taxonomy/fields/*.yaml`
- `connector/infra/logging/runtime.py`
- `connector/infra/logging/redaction.py`

---

## История

| Дата | Событие |
|---|---|
| 2026-06-09 | Решение предложено: ECS JSON shape через финальный structlog processor |
| 2026-06-14 | Решение принято: taxonomy вынесена из ADR в YAML/dev-docs; `ecs_transform` остаётся финальным JSON processor; generic event sink внутренний, наружу - zone-specific adapters |
