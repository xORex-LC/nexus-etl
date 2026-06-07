# connector/domain/ports/topology

## Назначение

Runtime-facing topology порты и DTO. Это boundary между topology domain/usecase логикой
и будущими bootstrap/stage consumer-ами.

## Файлы

| Файл | Назначение |
|---|---|
| `models.py` | `SourceTopologyCanonicalPath`, `SourceTopologyValidationState`, `TopologyMatchResult`, `TopologyLinkResolutionResult`, `TargetHierarchyRow`, readiness/freshness DTO, `TopologyRuntimeRequirements` |
| `provider.py` | `TopologyProviderPort`, `TopologyNotAvailableError` |
| `builders.py` | `SourcePathTopologyBuilderPort`, `TargetHierarchyTopologyBuilderPort` |
| `readers.py` | `SourceAdjacencyReadPort`, `TopologyTargetMembershipReadPort`, `TopologyTargetReadPort` — read seams для source adjacency, membership и target hierarchy |
| `observability.py` | `TopologyEventSink` — transport-neutral runtime seam для topology lifecycle событий |
| `services.py` | `SourceTopologyLocatorBuilderPort`, `TopologyMatchServicePort`, `TopologyLinkResolutionServicePort` — stage-facing topology consumer contracts |

## Правило

Здесь живут только контракты и маленькие DTO. Реализации builders/provider/readiness/readers
должны оставаться в domain/usecases/infra слоях согласно их ответственности.
