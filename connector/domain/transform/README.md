# connector/domain/transform

## Назначение

Реализации всех стадий ETL-пайплайна и инфраструктура их оркестрации. Содержит ядра стадий, модели результатов, провайдеры и оркестратор.

## Структура

| Подпапка | Назначение |
|---|---|
| `core/` | `TransformResult[T]`, `SourceRecord`, `iter_micro_batches()`, базовые итераторы и модели |
| `common/` | Утилиты для стадий: `read_field_value()`, `read_value()`, `sink_schema`, нормализаторы текста |
| `ids/` | Value objects: `MatchKey`, `TargetId`, `build_delimited_match_key()` |
| `stages/` | `StageContract[T_in, T_out]`, `PipelineOrchestrator`, `MapStage`, `NormalizeStage`, `EnrichStage`, `MatchStage`, `ResolveContextStage`, `ResolveStage` |
| `mapping/` | `MapperCore`, `MapperEngine` |
| `normalize/` | `NormalizerEngine` |
| `enrich/` | `EnricherCore`, `EnricherEngine`, провайдеры обогащения |
| `matcher/` | `MatchEngine`, `MatchCore`, `MatchedRow`, `MatchDecision`, `DeduplicationStore` |
| `resolver/` | `ResolveEngine`, `ResolveCore`, pending-codec, batch index service |
| `providers/` | `ProviderGateway` — runtime-реестр enrich-провайдеров (`cache.by_field`, `dictionary.by_key`, …) |

## Контракт стадии

```python
class StageContract[T_in, T_out](Protocol):
    stage_name: str
    def run(self, source: Iterable[T_in]) -> Iterator[TransformResult[T_out]]: ...
```

## Зависимости

**Зависит от:** `domain/dsl/`, `domain/transform_dsl/`, `domain/diagnostics/`, `domain/ports/`.  
**Используется:** `delivery/cli/stages/`, `delivery/pipelines/`, `usecases/`.
