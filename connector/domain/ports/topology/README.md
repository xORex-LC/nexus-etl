# connector/domain/ports/topology

## Назначение

Runtime-facing topology порты и DTO. Это boundary между topology domain/usecase логикой
и будущими bootstrap/stage consumer-ами.

## Файлы

| Файл | Назначение |
|---|---|
| `models.py` | `SourceTopologyCanonicalPath`, `TargetHierarchyRow`, readiness/freshness DTO |
| `provider.py` | `TopologyProviderPort`, `TopologyNotAvailableError` |
| `builders.py` | `SourcePathTopologyBuilderPort`, `TargetHierarchyTopologyBuilderPort` |
| `readers.py` | `TopologyTargetReadPort` — cache-backed read seam для target hierarchy |
| `observability.py` | `TopologyEventSink` — transport-neutral runtime seam для topology lifecycle событий |

## Правило

Здесь живут только контракты и маленькие DTO. Реализации builders/provider/readiness/readers
должны оставаться в domain/usecases/infra слоях согласно их ответственности.
