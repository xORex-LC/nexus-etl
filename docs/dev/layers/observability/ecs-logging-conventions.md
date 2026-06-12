# ECS Logging Conventions

> Статус: планирование taxonomy и ECS-миграции
> Машинно-авторитетный источник после внедрения: `connector/infra/logging/ecs.py`

Этот документ теперь служит **точкой входа** в набор более мелких документов по ECS-таксономии
логирования. Полная модель разбита по тематическим секциям, чтобы отдельно развивать:

- общую vocabulary и field profile;
- zoned taxonomy по слоям и подсистемам;
- словарь `event.action`;
- карту текущих call-site'ов и миграционный инвентарь.

## Навигация

### База модели

- [Overview and Principles](./ecs-logging-taxonomy/overview-and-principles.md)
- [Field Catalog](./ecs-logging-taxonomy/field-catalog.md)
- [Worked Examples and Level Rules](./ecs-logging-taxonomy/worked-examples-and-level-rules.md)

### Taxonomy Zones

- [Zone 1: Runtime Orchestrator / CLI Lifecycle](./ecs-logging-taxonomy/zones/01-runtime-cli-lifecycle.md)
- [Zone 2: Command-Specific Delivery Lifecycle](./ecs-logging-taxonomy/zones/02-command-delivery-lifecycle.md)
- [Zone 3: Pipeline Stage Lifecycle](./ecs-logging-taxonomy/zones/03-pipeline-stage-lifecycle.md)
- [Zone 4: Record Context](./ecs-logging-taxonomy/zones/04-record-context.md)
- [Zone 5: Enrich Subsystem](./ecs-logging-taxonomy/zones/05-enrich-subsystem.md)
- [Zone 6: State Stores / Provider Subsystems](./ecs-logging-taxonomy/zones/06-state-stores-and-providers.md)
- [Zone 7: DSL Artifact Lifecycle](./ecs-logging-taxonomy/zones/07-dsl-artifact-lifecycle.md)
- [Zone 8: Match Decision Service](./ecs-logging-taxonomy/zones/08-match-decision-service.md)
- [Zone 9: Resolve / Plan Decision & Artifact Lifecycle](./ecs-logging-taxonomy/zones/09-resolve-plan-lifecycle.md)

### Cross-Cutting Reference

- [Event Action Dictionary](./ecs-logging-taxonomy/event-action-dictionary.md)
- [Call-Site Map](./ecs-logging-taxonomy/callsite-map.md)
- [Outcome, Kind, and Maintenance Rules](./ecs-logging-taxonomy/outcome-kind-and-maintenance.md)

## Как читать

1. Сначала `Overview and Principles` для общей модели и границ.
2. Затем `Field Catalog` для ECS/nexus/labels vocabulary.
3. Затем нужную zone-документацию для конкретного слоя или подсистемы.
4. `Event Action Dictionary` и `Call-Site Map` использовать как поперечные справочники и миграционный backlog.

## Связанные документы

- [Observability Logging](./observability-logging.md)
- [OBSERVABILITY-DEC-003](../../../adr/observability/OBSERVABILITY-DEC-003-ecs-renderer-and-field-mapping.md)
- [OBSERVABILITY-PROBLEM-003](../../../adr/observability/OBSERVABILITY-PROBLEM-003-non-ecs-log-shape.md)
- [ECS Field Reference](https://www.elastic.co/docs/reference/ecs/ecs-field-reference)
