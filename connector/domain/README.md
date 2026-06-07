# connector/domain

## Назначение

Ядро приложения. Содержит бизнес-логику, модели, доменные сервисы и интерфейсы (порты). Не зависит от `infra` или `delivery` — только от стандартной библиотеки и `pydantic`.

## Структура

| Подпапка | Назначение |
|---|---|
| `dsl/` | Движок трансформаций: `OperationRegistry`, `TransformationEngine`, ~44 операции |
| `transform_dsl/` | DSL-спеки (Pydantic) и компиляторы для каждой стадии пайплайна |
| `transform/` | Реализации стадий: `MapperCore`, `NormalizerEngine`, `EnricherCore`, `MatchEngine`, `ResolveEngine`, `PipelineOrchestrator` |
| `planning/` | `PlanBuilder`, `PlanItem`, `Plan` — построение плана из результатов трансформации |
| `cache_core/` | Чистая логика управления кэшем: планирование refresh, drift-детекция, dependency graph |
| `cache_dsl/` | Декларативные cache-политики через YAML |
| `dataset_dsl/` | DSL схемы датасета (catalog, payload компиляция) |
| `target_dsl/` | DSL конфигурации целевой системы |
| `dictionary_dsl/` | DSL справочников |
| `diagnostics/` | `ErrorCatalog`, `DiagnosticItem`, `SystemErrorCode`, `StopPolicy` |
| `reporting/` | Event-driven система отчётности: `InMemoryReportContext`, events, adapters |
| `secrets/` | Vault-сервисы, политики жизненного цикла секретов |
| `dependency_tree/` | Topology snapshot/query subsystem: builders, readiness evaluator, deterministic ids |
| `ports/` | Все интерфейсы (Protocols) для `cache`, `target`, `secrets`, `transform`, `topology` |
| `models.py` | Общие доменные модели: `DiagnosticItem`, `DiagnosticStage`, `RowRef`, `Identity` |

## Правила слоя

- Никаких импортов из `infra/`, `delivery/`, `usecases/`
- Проверяется `lint-imports` (architecture-тесты)
- Модели данных — `dataclass(frozen=True)`, не Pydantic (кроме DSL-спек)
