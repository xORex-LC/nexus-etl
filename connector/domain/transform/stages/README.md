# connector/domain/transform/stages

## Назначение

Контракты стадий пайплайна и их конкретные реализации. Содержит `StageContract`, `PipelineOrchestrator`, основные stage-классы и дополнительные pipeline filters.

## Файлы

| Файл | Назначение |
|---|---|
| `source_topology_filter.py` | `SourceTopologyFilterStage` — post-map фильтр source rows, которые topology bootstrap признал unanchored |
| `stages.py` | `StageContract[T_in, T_out]` (Protocol); `PipelineOrchestrator`; `MapStage`, `NormalizeStage`, `EnrichStage`, `MatchStage`, `ResolveContextStage`, `ResolveStage` |

## Парная модель Resolve (TRANSFORM-DEC-004)

`ResolveContextStage` — буферизует весь батч, строит `batch_index` через `IBatchIndexService.set_index()`.  
`ResolveStage` — читает индекс через `IBatchIndexService.get()`, лениво разрешает каждую запись.  
Оба класса используют общий `IBatchIndexService` (Singleton в DI-контейнере).

## Зависимости

**Зависит от:** `domain/transform/core/`, `domain/transform/mapping/`, `domain/transform/normalize/`, `domain/transform/enrich/`, `domain/transform/matcher/`, `domain/transform/resolver/`, `domain/ports/`.  
**Используется:** `delivery/cli/stages/`, `delivery/pipelines/`.
