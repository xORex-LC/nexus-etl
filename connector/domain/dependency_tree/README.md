# connector/domain/dependency_tree

## Назначение

Чистое domain-ядро topology/dependency-tree подсистемы. Содержит immutable snapshot,
query API, source/target builders и deterministic hash helpers.

## Файлы

| Файл | Назначение |
|---|---|
| `models.py` | `TopologyNode` — неизменяемый контракт topology-узла |
| `snapshot.py` | `TopologyQueryPort`, `TopologySnapshot` — read-only graph/query-слой |
| `source_builder.py` | `SourcePathTopologyBuilder` — source-side сборка из canonical path-ов |
| `target_builder.py` | `TargetHierarchyTopologyBuilder` — target-side валидация adjacency и сборка |
| `fingerprints.py` | Детерминированные SHA-256-хелперы для synthetic id и structural signature |
| `ports.py` | `TopologyTracePort`, `NullTopologyTrace` — domain-local trace seam для DEBUG |

## Границы

- Не зависит от `infra`, `delivery`, `usecases`, `polars`, `structlog`
- Не читает YAML/spec и не знает о cache/SQLite
- Не решает readiness/bootstrap orchestration и не содержит stage logic
