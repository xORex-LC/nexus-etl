# Matcher Roadmap (черновик)

## Цель
Зафиксировать текущую роль `matcher`, ближайший план развития и идеи на будущее отдельно от общего DSL-плана.

## Текущее состояние matcher
1. Сопоставляет запись с sink/cache по identity-правилам.
2. Формирует `desired_state` и `fingerprint` для downstream.
3. Определяет базовый статус матчинга: `MATCHED`, `NOT_FOUND`, `CONFLICT_TARGET`.
4. Source-dedup (duplicate/conflict внутри входного потока) сейчас частично выполняется в use-case (transitional).
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
2. Реализация пока не начата.
