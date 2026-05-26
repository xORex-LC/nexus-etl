# connector/domain/transform/matcher

## Назначение

Стадия сопоставления: идентифицирует соответствие каждой входящей записи с записью в целевой системе (через кэш). Определяет: это CREATE или UPDATE.

## Ключевые файлы

| Файл | Назначение |
|---|---|
| `match_engine.py` | `MatchEngine` — итерирует поток, делегирует `MatchCore` |
| `match_core.py` | `MatchCore` — основная логика: строит `match_key`, ищет в кэше, вычисляет `MatchDecision` |
| `match_models.py` | `MatchedRow`, `MatchDecision`, `MatchDecisionStatus`, `MatchCandidate`, `ResolvedRow` |
| `scoring.py` | Алгоритм скоринга кандидатов сопоставления (fuzzy match) |
| `dedup_store.py` | `DeduplicationStore` — детекция дублей в рамках одного прогона |
| `identity_keys.py` | `format_identity_key()` — форматирование ключей идентичности |
| `ports.py` | `IMatchBatchSettings` — протокол настроек батча (batch_size, flush_interval) |

## Статусы решения

`MATCHED` / `NOT_FOUND` / `AMBIGUOUS` / `CONFLICT_SOURCE`

## Зависимости

**Зависит от:** `domain/transform/ids/`, `domain/transform_dsl/specs/match.py`, `domain/ports/cache/roles.py` (`MatchRuntimePort`), `domain/diagnostics/`.  
**Используется:** `domain/transform/stages/stages.py` (`MatchStage`), `usecases/common/identity_sync.py`.
