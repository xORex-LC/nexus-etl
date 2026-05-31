# connector/infra/topology

## Назначение

Infrastructure-адаптеры topology-подсистемы. На текущем этапе здесь живёт cache-backed
read seam для target hierarchy, который читает adjacency rows и freshness metadata
из SQLite cache snapshot-а.

## Файлы

| Файл | Назначение |
|---|---|
| `sqlite_target_reader.py` | `SqliteTopologyTargetReader` — реализация `TopologyTargetReadPort` поверх `SqliteCacheGateway` |

## Границы

- Зависит от `domain/ports/topology`, `domain/transform_dsl`, `infra/cache`, `infra/sqlite`
- Не принимает readiness decisions и не строит `TopologySnapshot`
- Не знает о CLI/DI/bootstrap activation
