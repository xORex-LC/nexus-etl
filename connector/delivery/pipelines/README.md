# connector/delivery/pipelines

## Назначение

Lifecycle-aware пайплайн для команды `import plan`. Инкапсулирует полный цикл планирования: сборку стадий трансформации, runtime filters, управление match-scope, буферизацию resolve-контекста и pending-replay из предыдущих прогонов.

## Файлы

| Файл | Назначение |
|---|---|
| `planning_pipeline.py` | `PlanningPipeline` — lifecycle-aware конвейер; `open()` возвращает поток `TransformResult`; управляет `dedup_store.reset()`, lifecycle match-scope через hooks, очисткой expired pending |
| `planning_pipeline_hooks.py` | Хуки стадий для `PlanningPipeline`: `on_stage_complete("match")` — очистка match-runtime scope |

## Порядок стадий внутри

```
MapStage → SourceTopologyFilterStage → NormalizeStage → EnrichStage → MatchStage → ResolveContextStage → ResolveStage
```

`SourceTopologyFilterStage` активен только когда topology bootstrap подготовил source validation state.
`ResolveContextStage` буферизует батч, строит `batch_index`.  
`ResolveStage` лениво разрешает записи через этот индекс.

Failed `TransformResult` из стадий сохраняются в потоке до `PlanBuilder`, чтобы `import plan`
мог корректно посчитать `failed_rows` и записать row-level диагностики в report.

## Зависимости

**Зависит от:** `delivery/cli/stages/`, `domain/transform/stages/`, `usecases/` (stage usecases), `domain/ports/cache/`.  
**Используется:** `delivery/cli/containers.py` (`PipelineContainer.planning_pipeline`), `delivery/commands/import_plan.py`.

## Эволюция

По TRANSFORM-DEC-007: `PipelineOrchestrator` → `PipelineComposer`. Интерфейс `open()` не изменился.
