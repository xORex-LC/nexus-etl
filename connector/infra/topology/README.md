# connector/infra/topology

## Назначение

Infrastructure-адаптеры topology-подсистемы. Здесь живут read seams для target hierarchy,
target membership и source adjacency, которые читают данные из SQLite cache snapshot-а
и CSV source через узкие порты.

## Файлы

| Файл | Назначение |
|---|---|
| `polars_source_reader.py` | `PolarsSourceAdjacencyReader` — чтение source adjacency rows из CSV с проекцией физических source-полей в domain DTO |
| `sqlite_membership_reader.py` | `SqliteTopologyTargetMembershipReader` — чтение множества target ids из cache snapshot-а для source anchoring |
| `sqlite_target_reader.py` | `SqliteTopologyTargetReader` — реализация `TopologyTargetReadPort` поверх узкого `TopologyCacheReadPort` (без прямого доступа к `SqliteCacheGateway`) |

## Границы

- Зависит от `domain/ports/topology`, `domain/ports/cache` (`TopologyCacheReadPort`), `domain/transform_dsl`, `polars`
- Чтение кэша только через role-порт; конкретный `SqliteCacheGateway` не импортируется
- Не принимает readiness decisions и не строит `TopologySnapshot`
- Не знает о CLI/DI/bootstrap activation
