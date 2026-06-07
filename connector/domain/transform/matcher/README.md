# connector/domain/transform/matcher

## Назначение

Стадия сопоставления: идентифицирует соответствие каждой входящей записи с записью в целевой системе через кэш и, при включённой policy, использует topology как refinement/disambiguation layer. Match не определяет final write-op, а формирует explainable `MatchDecision` для downstream resolve.

## Ключевые файлы

| Файл | Назначение |
|---|---|
| `match_engine.py` | `MatchEngine` — runtime-обвязка DSL + topology consumer dependencies |
| `match_core.py` | `MatchCore` — identity/fuzzy matching, source dedup и topology-aware refinement |
| `match_models.py` | `MatchedRow`, `MatchDecision`, `MatchDecisionStatus`, `MatchCandidate`, `ResolvedRow`, topology evidence |
| `scoring.py` | Алгоритм скоринга кандидатов сопоставления (fuzzy match) |
| `dedup_store.py` | `DeduplicationStore` — детекция дублей в рамках одного прогона |
| `identity_keys.py` | `format_identity_key()` — форматирование ключей идентичности |
| `ports.py` | `IMatchBatchSettings` — протокол настроек батча (batch_size, flush_interval) |

## Статусы решения

`MATCHED` / `NOT_FOUND` / `AMBIGUOUS` / `CONFLICT_SOURCE`

## Зависимости

**Зависит от:** `domain/transform/ids/`, `domain/transform_dsl/specs/match.py`, `domain/ports/cache/roles.py` (`MatchRuntimePort`), `domain/ports/topology/`, `domain/diagnostics/`.  
**Используется:** `domain/transform/stages/stages.py` (`MatchStage`), `usecases/common/identity_sync.py`.
