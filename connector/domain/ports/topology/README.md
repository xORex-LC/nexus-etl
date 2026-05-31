# connector/domain/ports/topology

## Назначение

Runtime-facing topology порты и DTO. Это boundary между topology domain/usecase логикой
и будущими bootstrap/stage consumer-ами.

## Файлы

| Файл | Назначение |
|---|---|
| `models.py` | `SourceTopologyCanonicalPath`, `TargetHierarchyRow` |
| `provider.py` | `TopologyProviderPort`, `TopologyNotAvailableError` |
| `builders.py` | `SourcePathTopologyBuilderPort`, `TargetHierarchyTopologyBuilderPort` |

## Правило

Здесь живут только контракты и маленькие DTO. Реализации builders/provider/readiness/readers
должны оставаться в domain/usecases/infra слоях согласно их ответственности.
