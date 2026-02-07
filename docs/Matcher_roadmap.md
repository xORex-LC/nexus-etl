# Matcher Roadmap (черновик)

## Цель
Зафиксировать текущую роль `matcher`, ближайший план развития и идеи на будущее отдельно от общего DSL-плана.

## Текущее состояние matcher
1. Сопоставляет запись с sink/cache по identity-правилам.
2. Формирует `desired_state` и `fingerprint` для downstream.
3. Определяет typed-статусы матчинга (`match_decision.status`) и transitional `match_status`.
4. Source-dedup (duplicate/conflict внутри входного потока) выполняется в match-core.
5. Кросс-доменное связывание target-сущностей выполняет не matcher, а resolve-стадия.

## Ближайший утвержденный план
1. Добавить `fuzzy`-сопоставление с `confidence scoring`.
2. Ввести пороги решений:
   1. `score >= accept_threshold` -> `MATCHED`
   2. `review_threshold <= score < accept_threshold` -> `CONFLICT_TARGET` или `NEEDS_REVIEW`
   3. `score < review_threshold` -> `NOT_FOUND`
3. Возвращать расширенный результат матчинга:
   1. `match_mode` (`exact`/`fuzzy`/`none`)
   2. `score`
   3. `decision_reason`
   4. `top_candidates` (ограниченно, например top-3)
4. Перенести source-dedup из use-case в match-core (единая доменная логика стадии).
5. Перевести правила матчинга в декларативный `MatchSpec` (DSL).

## Архитектура миграции matcher (подтверждено)
### Целевой runtime-контур
1. `MatchSpec` (DSL) -> `MatchDsl.compile()` -> `MatchingRules`.
2. `MatchEngine` исполняет `MatchCore` с уже скомпилированными правилами.
3. `MatchUseCase` остается orchestration-слоем:
   - батчинг/flush/lifecycle;
   - запуск stage-engine;
   - инкрементальный репортинг.

### Границы ответственности
1. `MatchCore`:
   - candidate generation;
   - exact-first + fuzzy fallback;
   - weighted scoring и thresholds;
   - source-dedup по каноническому ключу;
   - формирование typed решения (`match_decision`).
2. `MatchUseCase`:
   - не содержит match-правил и дедуп-алгоритмов;
   - не дублирует scoring/decision-логику.
3. `Resolve`:
   - не определяет match decision повторно;
   - потребляет результат matcher и выполняет link/pending policy.

### Transitional совместимость (временно)
1. Legacy-статусы сохраняются через adapter typed -> legacy.
2. `MatchedRow.match_status` живет параллельно с `match_decision`.
3. Полный переход на typed-only контракт выполняется после DSL cutover и миграции downstream.

### Что убираем после cutover
1. Runtime wiring через Python-фабрику `build_matching_rules()` — уже удалено.
2. Ручную сборку dataset match-правил в коде как primary source.
3. Дубли decision-логики между usecase/core.

## Идеи на будущее (пока не реализуем)
1. Explainability: вклад каждого поля в финальный score.
2. Threshold profiles: разные пороги для разных типов записей.
3. Fallback blocking keys: альтернативные блок-ключи при слабой identity.
4. Temporal tie-breaker: учет свежести (`updated_at`) только при равных score.
5. Soft-delete policy: отдельное поведение для удаленных target-записей.
6. Отдельный статус `NEEDS_REVIEW` как часть контракта matcher.
7. Quality metrics: `hit-rate`, `ambiguous-rate`, `avg-score`.

## Границы ответственности
1. Matcher отвечает за candidate generation, scoring и decision по матчингу.
2. Resolver отвечает за link-resolution, pending/retry и подготовку к операциям apply/plan.
3. Clustering и survivorship не входят в matcher и, при необходимости, выносятся в отдельную стадию.

## Статус
1. Документ создан как backlog/ориентир.
2. Реализация fuzzy/scoring и typed-contract выполнена.
3. Cutover на `MatchSpec` как единственный runtime-источник правил выполнен.
4. Следующий шаг: поэтапное снятие оставшегося transitional legacy (`match_status` downstream).
