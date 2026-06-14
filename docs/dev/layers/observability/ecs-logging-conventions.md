# ECS Logging Conventions

> Статус: планирование taxonomy и ECS-миграции
> Canonical human entry point: этот документ
> Машинно-авторитетные источники после внедрения: `connector/common/observability/taxonomy/actions.yaml`,
> `connector/common/observability/taxonomy/fields/*.yaml` и runtime mapping в `connector/infra/logging/ecs.py`

Этот документ служит **единственной точкой входа** в набор более мелких документов по ECS-таксономии
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
- [Zone 10: Apply Execution / Target Write Lifecycle](./ecs-logging-taxonomy/zones/10-apply-target-execution.md)
- [Zone 11: Vault / Secrets Runtime Lifecycle](./ecs-logging-taxonomy/zones/11-vault-secrets-runtime-lifecycle.md)
- [Zone 12: Vault Management Lifecycle](./ecs-logging-taxonomy/zones/12-vault-management-lifecycle.md)
- [Zone 13: Extract / Source Ingestion](./ecs-logging-taxonomy/zones/13-extract-source-ingestion.md)
- [Zone 14: Normalize / Data Quality Stage](./ecs-logging-taxonomy/zones/14-normalize-stage.md)
- [Zone 15: Topology Subsystem](./ecs-logging-taxonomy/zones/15-topology-subsystem.md)
- [Zone 16: Map / Mapping Stage](./ecs-logging-taxonomy/zones/16-map-stage.md)

### Cross-Cutting Reference

- [Event Action Dictionary](./ecs-logging-taxonomy/event-action-dictionary.md)
- [Call-Site Map](./ecs-logging-taxonomy/callsite-map.md)
- [Outcome, Kind, and Maintenance Rules](./ecs-logging-taxonomy/outcome-kind-and-maintenance.md)

## Как читать

1. Сначала `Overview and Principles` для общей модели и границ.
2. Затем `Field Catalog` для ECS/nexus/labels vocabulary.
3. Затем нужную zone-документацию для конкретного слоя или подсистемы.
4. `Event Action Dictionary` и `Call-Site Map` использовать как поперечные справочники и миграционный backlog.

`overview-and-principles.md` остаётся детальной prose-расшифровкой модели, но не отдельной второй
точкой входа. Ссылаться из ADR и из других dev-doc следует в первую очередь на этот документ.

## Связанные документы

- [Observability Logging](./observability-logging.md)
- [OBSERVABILITY-DEC-003](../../../adr/observability/OBSERVABILITY-DEC-003-ecs-renderer-and-field-mapping.md)
- [OBSERVABILITY-PROBLEM-003](../../../adr/observability/OBSERVABILITY-PROBLEM-003-non-ecs-log-shape.md)
- [ECS Field Reference](https://www.elastic.co/docs/reference/ecs/ecs-field-reference)
