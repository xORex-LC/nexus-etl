# connector/delivery/pipelines

## Назначение

Lifecycle-aware пайплайн для команды `import plan`. Инкапсулирует полный цикл планирования: сборку стадий трансформации, управление match-scope, буферизацию resolve-контекста и pending-replay из предыдущих прогонов.

## Файлы

| Файл | Назначение |
|---|---|
| `planning_pipeline.py` | `PlanningPipeline` — lifecycle-aware конвейер; `open()` возвращает поток `TransformResult`; управляет `dedup_store.reset()`, lifecycle match-scope через hooks, очисткой expired pending |
| `planning_pipeline_hooks.py` | Хуки стадий для `PlanningPipeline`: `on_stage_complete("match")` — очистка match-runtime scope |

## Порядок стадий внутри

```
MapStage → NormalizeStage → EnrichStage → MatchStage → ResolveContextStage → ResolveStage
```

`ResolveContextStage` буферизует батч, строит `batch_index`.  
`ResolveStage` лениво разрешает записи через этот индекс.

## Зависимости

**Зависит от:** `delivery/cli/stages/`, `domain/transform/stages/`, `usecases/` (stage usecases), `domain/ports/cache/`.  
**Используется:** `delivery/cli/containers.py` (`PipelineContainer.planning_pipeline`), `delivery/commands/import_plan.py`.

## Эволюция

По TRANSFORM-DEC-007: `PipelineOrchestrator` → `PipelineComposer`. Интерфейс `open()` не изменился.
