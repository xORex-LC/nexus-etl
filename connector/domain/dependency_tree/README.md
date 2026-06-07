# connector/domain/dependency_tree

## Назначение

Чистое domain-ядро topology/dependency-tree подсистемы. Содержит immutable snapshot,
query API, source/target builders и deterministic hash helpers.

## Файлы

| Файл | Назначение |
|---|---|
| `models.py` | `TopologyNode` — неизменяемый контракт topology-узла |
| `snapshot.py` | `TopologyQueryPort`, `TopologySnapshot` — read-only graph/query-слой |
| `comparison.py` | `TopologyMatchMode`, `TopologyComparisonResult`, `compare_topology_candidates()` — shared comparison ladder для consumer-ов |
| `anchoring.py` | `anchor_source_nodes()` и DTO source adjacency anchoring — валидация, что source-узлы достижимы от target или batch parent |
| `source_builder.py` | `SourcePathTopologyBuilder` — source-side сборка из canonical path-ов |
| `target_builder.py` | `TargetHierarchyTopologyBuilder` — target-side валидация adjacency и сборка |
| `readiness.py` | `TopologyTargetReadinessEvaluator` — readiness/freshness оценка target snapshot-а |
| `fingerprints.py` | Детерминированные SHA-256-хелперы для synthetic id и structural signature |
| `ports.py` | `TopologyTracePort`, `NullTopologyTrace` — domain-local trace seam для DEBUG |

## Границы

- Не зависит от `infra`, `delivery`, `usecases`, `polars`, `structlog`
- Не читает YAML/spec и не знает о cache/SQLite
- Не читает target hierarchy сам и не содержит bootstrap/stage orchestration
