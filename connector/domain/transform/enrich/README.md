# connector/domain/transform/enrich

## Назначение

Стадия обогащения: вычисляет производные поля (lookup в кэше/справочниках, генерация паролей/логинов, запись секретов в vault).

## Ключевые классы

| Файл | Назначение |
|---|---|
| `enricher_engine.py` | `EnricherEngine` — итерирует поток через `EnricherCore` |
| `enricher_core.py` | `EnricherCore` — применяет `EnrichBlock` (lookup + generate) к одной записи |
| `resolver.py` | `EnrichConflictResolver` — обрабатывает конфликты генерации (стратегия `retry_with_suffixes`) |
| `models.py` | `EnrichResult`, `SecretWriteRecord` — результаты enrich и записи в vault |
| `providers.py` | Утилиты для работы с enrich-провайдерами |

## Особенности

- **Secrets**: записывает секреты в vault через `SecretVaultWriteService` во время выполнения этой стадии
- **Merge-политика**: `recompute_always`, `fill_only_if_empty`, `never_override`, `override_if_empty`, `override_if_authoritative`
- **run_when_errors**: `"never"` | `"if_any"` | `"always"` — условное выполнение правила при наличии ошибок

## Зависимости

**Зависит от:** `domain/dsl/engine.py`, `domain/transform_dsl/specs/enrich.py`, `domain/transform/providers/`, `domain/ports/cache/roles.py` (`EnrichLookupPort`), `domain/ports/secrets/`.  
**Используется:** `domain/transform/stages/stages.py` (`EnrichStage`).
