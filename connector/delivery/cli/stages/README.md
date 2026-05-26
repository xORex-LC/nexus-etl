# connector/delivery/cli/stages

## Назначение

Типизированная фабрика и реестр стадий пайплайна для wiring в `delivery`-слое. Связывает DSL-стадии (`MapStage`, `NormalizeStage`, …) с DI-контейнером.

## Файлы

| Файл | Назначение |
|---|---|
| `registry.py` | `build_stage_factory()` — регистрирует typed factory functions для всех 6 стадий (`map`, `normalize`, `enrich`, `match`, `resolve`, `resolve_context`); содержит комментарий почему `match`/`resolve` — Singleton, а не Factory |
| `config.py` | `CheckpointName` enum — имена контрольных точек пайплайна (напр. `"match"`) для lifecycle hooks |
| `composer.py` | `PipelineComposer` — собирает последовательность стадий из `StageDescriptor` в исполняемый конвейер |

## Зависимости

**Зависит от:** `domain/transform/stages/`, `domain/transform/factory.py`, `domain/ports/cache/`.  
**Используется:** `delivery/cli/containers.py` (`PipelineContainer`), `delivery/pipelines/`.

## Примечание

`MatchStage` и `ResolveStage` создаются как Singleton (не через `StageFactory`) — им нужен общий `batch_index` (`IBatchIndexService`). Stub-функции в реестре для них намеренно бросают `NotImplementedError`.
