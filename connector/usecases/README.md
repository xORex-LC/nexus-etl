# connector/usecases

## Назначение

Оркестрационный слой. Usecases координируют domain-сервисы и инфраструктурные адаптеры для выполнения конкретных сценариев приложения: запуск стадий пайплайна, refresh кэша, применение плана, управление vault.

**Правило:** usecases знают о `domain` и используют `infra` через порты. Не содержат HTTP-вызовов, SQL или бизнес-правил трансформации.

## Структура

| Подпапка/файл | Назначение |
|---|---|
| `mapping_usecase.py` | `MappingUseCase` — запуск стадии mapping с отчётностью |
| `normalize_usecase.py` | `NormalizeUseCase` — normalize + map |
| `enrich_usecase.py` | `EnrichUseCase` — enrich с записью секретов в vault |
| `match_usecase.py` | `MatchUseCase` — identity matching |
| `resolve_usecase.py` | `ResolveUseCase` — conflict resolution с pending replay |
| `import_apply_service.py` | `ImportApplyService` — выполнение плана: adapter → executor → identity sync |
| `cache_command_service.py` | Оркестрация cache admin операций |
| `cache_refresh_service.py` | Refresh кэша из target API |
| `cache_clear_usecase.py` | Очистка кэша |
| `cache_status_usecase.py` | Статус кэша |
| `topology_match.py` | `SourceTopologyLocatorBuilder`, `TopologyMatchService` — topology-aware consumer для `MatchStage` |
| `topology_target_build.py` | `TargetTopologyBuildUseCase` — read → build → readiness для target topology |
| `topology_bootstrap.py` | `TopologyRequirementResolver`, `TopologyBootstrapUseCase`, `StaticTopologyProvider`, `TraceToSink` |
| `apply/` | `ApplyResult`, `ApplySummary`, `ApplyTelemetrySink` |
| `common/` | `IdentityIndexSyncer` — post-apply синхронизация |
| `operations/` | Legacy re-exports vault key management |
| `management/vault/` | `VaultKeyManagementUseCase` — init/status/rotate/rewrap |

## Зависимости

**Зависит от:** `domain/`, `domain/ports/` (через DI).  
**Используется:** `delivery/commands/`, `delivery/pipelines/`.
