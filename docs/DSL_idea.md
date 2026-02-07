# Dataset DSL Idea (рабочий черновик)

## Цель
Упростить добавление новых датасетов без переписывания большого количества модулей:
- изменения правил через YAML/JSON;
- единый runtime-путь для стадий;
- минимум ручного wiring в usecase.

## Идея
Ввести минимальный DSL для описания стадий:
- `mapping`
- `normalize`
- `enrich`
- `match`
- `resolve`
- (опционально) `plan/apply` правила на следующих этапах.

Движок читает DSL и собирает исполняемую конфигурацию стадий.
Для редких кейсов остаются `custom`-правила, но они подключаются как расширения, а не как второй pipeline-путь.

## Единая модель DSL-обвязки для всех стадий
Цель: каждая стадия выглядит одинаково архитектурно, а отличается только бизнес-логикой.

### Общая схема (для любой стадии)
1) `StageSpec` (pydantic-модель DSL правил)
2) `StageDsl` (compile: spec -> core config)
3) `StageEngine` (исполнитель стадии)
4) `StageCore` (чистая доменная логика без YAML/CLI/I/O)
5) Дополнительно: `StageProviders/StageReport`, если это действительно часть стадии

### Почему так
- DSL одинаков по форме (`Spec/Dsl/Engine/Core`);
- ядра стадий тестируются изолированно;
- оркестрация и I/O не протекают в доменную логику;
- перенос правил в DSL не требует переписывания core-алгоритмов.

## Архитектурные принципы
### 1) Единый каркас стадии
- `StageSpec` описывает правила;
- `StageDsl` компилирует в core-конфиг;
- `StageEngine` исполняет;
- `StageCore` принимает решения.

### 2) Жесткая граница ответственности
- `TransformationEngine/ops`: только pure transforms;
- `StageCore`: policy/orchestration внутри стадии;
- `UseCase`: runtime orchestration, batching, lifecycle, report I/O.

### 3) Diagnostics вместо исключений
- Ошибки правил и ops накапливаются как diagnostics;
- исключения остаются только для truly unexpected/runtime случаев.

### 4) Декларативность dataset-специфики
- Все, что можно описать в YAML, выносится в dataset-спеки;
- Python-код датасета остается только для transitional/wiring и custom handlers.

### 5) Sink-контракт по стадиям
- `map`: структурная/required проверка;
- `normalize`: типы/nullability/форматы;
- `enrich`: только lookup/generate/secret/match-key зона ответственности;
- без лишнего дублирования между стадиями.

### 5.1) Уточнение по sink-validation (зафиксировано)
Итог договоренности по границам ответственности:
1) `normalize` выполняет полную валидацию строки против `sink`-контракта:
   - `required`,
   - `nullable`,
   - type-check.
2) `enrich` выполняет частичную (targeted) валидацию только для изменяемых полей:
   - перед применением candidate в target поле;
   - только по соответствующему sink-field;
   - ошибка маппится через policy операции (`on_provider_error`), без отдельного runtime-пути.
3) `match` не валидирует данные против `sink_schema`:
   - matcher не меняет payload строки для sink;
   - matcher отвечает за сопоставление (`identity/fuzzy/scoring/tie`), а не за type/nullability контракт sink.

Что уже реализовано:
1) `normalize` wiring для employees подключает `sink_spec` и включает sink-check в runtime.
2) В `enrich` добавлена field-level sink-проверка через общий helper (`validate_sink_fields`), без дублирования полного row-check.
3) `matcher` не зависит от `sink_schema`; сохраняется только валидация внутренних инвариантов стадии match.

Правило на будущее:
1) Не добавлять `sink_schema` проверки в matcher/resolver.
2) Если новая enrich-операция меняет sink-target, она автоматически проходит targeted sink-check в enrich-core.

### 6) Секреты и match_key
- `match_key` и secret-поток живут в enrich-слое;
- после vault запись в row очищается, а служебная мета остается в `meta`.

### 7) Reuse-first
Перед новым кодом проверяем общий kernel (`ops/helpers/diagnostics`).

### 8) Без оверинжиниринга
Новая абстракция принимается только если:
- снижает дублирование в 2+ местах;
- упрощает подключение датасета;
- не порождает второй runtime-путь.

## Минимальные базовые абстракции (псевдокод)
```python
class StageSpec(Protocol): ...

class StageCore(Protocol):
    def apply(self, item: TransformResult) -> TransformResult: ...

class StageDsl(Protocol):
    def compile(self, spec: StageSpec) -> StageCore: ...

class StageEngine(Generic[S]):
    def __init__(self, spec: S, dsl: StageDsl[S]):
        self.core = dsl.compile(spec)

    def run(self, item: TransformResult) -> TransformResult:
        return self.core.apply(item)
```

## Соответствие стадий
- `MappingSpec -> MapperDsl -> MapperEngine -> MapperCore`
- `NormalizeSpec -> NormalizerDsl -> NormalizerEngine -> NormalizerCore`
- `EnrichSpec -> EnricherDsl -> EnricherEngine -> EnricherCore`
- `MatchSpec -> MatchDsl -> MatchEngine -> MatchCore`
- `ResolveSpec -> ResolveDsl -> ResolveEngine -> ResolveCore`

## Match/Resolve: целевая модель данных
### Match
Matcher отвечает за вопрос: "Кто это?" и возвращает решение матчинга с explainability:
- `match_status`
- `match_mode` (`exact|fuzzy`)
- `score`
- `decision_reason`
- `top_candidates`

### Resolve
Resolver отвечает за вопрос: "Что делать с найденной/неоднозначной записью?":
- merge/link rules;
- pending/retry path;
- финальная operation-готовность для plan/apply.

Правило границы:
- matcher не делает survivorship значений по полям;
- survivorship относится к resolve/merge policy.

## Актуальная проблема (закрыта): Match DSL
Match-правила переведены с Python-конфига на декларативный `MatchSpec`.

Нужно перевести в DSL:
1) `identity_rules`
2) `source_dedup` policy
3) `fuzzy` policy:
   - `blocking_keys`
   - `comparators`
   - `weights`
   - thresholds (`accept/review`)
   - `tie_delta`
   - `top_k`
   - `max_candidates`
   - `score_round`

### Зафиксированная инвентаризация после миграции (matcher)
Где сейчас находится dataset-специфика матчинга:
1) `datasets/employees.match.yaml`:
   - identity rules,
   - source-dedup policy,
   - fuzzy/scoring параметры.
2) `connector/datasets/employees/spec.py`:
   - runtime wiring через `load_match_spec_for_dataset(...) + MatchDsl.compile(...)`.

Важно по границам:
1) `connector/datasets/employees/load/link_rules.py` не относится к matcher-DSL миграции:
   - это resolve-правила (следующая стадия, отдельная миграция).
2) `projector.py` не является конфигом matcher-алгоритмов:
   - он формирует входные признаки/снимок, но не задает политику match decision.

Что уже ушло после завершения Match DSL:
1) прямой runtime-вызов `build_matching_rules()` из dataset wiring;
2) ручная Python-сборка параметров match как primary source.

Что может временно остаться (transitional):
1) adapter typed -> legacy statuses;
2) fallback dedup policy, пока downstream не полностью переведен на DSL+typed контракт.

## Fuzzy + Scoring (MVP модель)
### Цель
Расширить match от strict identity lookup до управляемого сопоставления с оценкой вероятности.

### Алгоритм (MVP)
1) `exact-first`:
   - если identity найдено точно -> `MATCHED`.
2) `fuzzy fallback`:
   - генерируем кандидатов по `blocking_keys`;
   - считаем field scores (`exact|casefold|similarity`);
   - агрегируем weighted score;
   - ранжируем top candidates.
3) Decision:
   - `score >= accept_threshold` -> `MATCHED`
   - `review_threshold <= score < accept_threshold` -> conflict/review status
   - `score < review_threshold` -> `NOT_FOUND`
   - tie по `tie_delta` -> ambiguity/conflict status.

### Explainability (текущий минимум)
- `decision_reason` как канонический reason-code;
- `top_candidates` c `target_id/score` (без полного evidence; это следующий этап).

### Статус закрытия Phase 1 (текущее состояние)
1) Введен typed-контракт решения матчинга:
   - `MatchDecisionStatus`
   - `MatchCandidate`
   - `MatchDecision`
2) Добавлен переходный адаптер в legacy-статусы:
   - `decision_status_to_match_status()`
   - `AMBIGUOUS -> MatchStatus.AMBIGUOUS` (прокинут end-to-end)
3) `MatchedRow` дополнен полем `match_decision`:
   - resolver/plan продолжают работать по текущему `match_status`,
   - explainability доступна без изменения downstream-контрактов.
4) Source dedup-key закреплен как канонический:
   - `dataset:identity_primary:identity_value`
   - fallback по `identity_value` оставлен только как transitional policy (`fallback_identity_value`).

### Transitional legacy (зафиксировано после текущего шага)
Что сознательно оставлено для обратной совместимости:
1) `MatchedRow.match_status` остается рабочим контрактом для downstream.
2) `MatchedRow.match_decision` остается каноничным typed-контрактом рядом с `match_status`.
3) `decision_status_to_match_status()` остается переходным адаптером typed -> legacy.
4) Legacy-статусы `CONFLICT_TARGET`/`CONFLICT_SOURCE` не удаляются на этом этапе.
5) `source_dedup.fallback_identity_value` и fallback dedup-key (`dataset:_fallback:<value>`) остаются временно (но fallback выключен по умолчанию).

### Актуализация legacy по результатам аудита
Ниже фиксация фактического статуса по каждому пункту (что можно убирать уже сейчас, что следующим шагом, что пока рано).

Можно убирать сейчас (низкий риск):
1) П.5 (`INVALID_INPUT -> CONFLICT_TARGET`) — закрыто:
   - сейчас `MatchDecisionStatus.INVALID_INPUT` не формируется runtime-путем;
   - transitional fallback удален, unknown статус теперь не маскируется в `CONFLICT_TARGET`.
2) П.9 (`AMBIGUOUS` через `RESOLVE_CONFLICT`) — закрыто:
   - введен отдельный diag-код `RESOLVE_AMBIGUOUS` для ambiguous-пути resolve.
3) П.8 (pending replay без `match_decision`) — закрыто:
   - в replay-пути `MatchedRow` теперь всегда создается с `match_decision`.

Можно убирать следующим шагом (средний риск, но реализуемо):
1) П.7 (`fallback_identity_value` + fallback dedup-key):
   - отключить по умолчанию — закрыто;
   - удалить fallback dedup-key после стабилизационного окна — в работе.
2) П.6 (дубли explainability-полей рядом с `match_decision`) — закрыто:
   - в `MatchedRow` оставлен единый канонический `match_decision`.
3) Legacy runtime fallback на Python-rules — закрыто:
   - runtime-ветка `matcher_use_legacy_rules` удалена.
4) Legacy Python match factory (`connector/datasets/employees/load/matching_rules.py`) — закрыто:
   - файл удален из runtime и из тестового контура;
   - matcher-конфигурация идет только через `datasets/employees.match.yaml` + `MatchDsl`.

Пока рано убирать (нужна миграция downstream):
1) П.1 (`MatchedRow.match_status` как рабочий downstream-контракт).
2) П.3 (`decision_status_to_match_status()` transitional adapter).
3) П.4 (legacy `CONFLICT_TARGET/CONFLICT_SOURCE` в downstream guard-логике).
4) П.2 (`match_decision` пока параллельно, а не единственный источник истины).

Рекомендуемый порядок снятия legacy (обновленный):
1) Снять low-risk пункты: п.5 + п.9 + п.8.
2) Перевести resolve/plan/report на `match_decision.status` как канонический источник.
3) Удалить адаптер typed -> legacy и дубли explainability-полей.
4) Удалить fallback dedup и legacy runtime feature-flag.
5) Финально убрать остатки legacy-веток/кодов (`match_status`-only зависимости).

Почему так:
1) не ломать текущий `match -> resolve -> plan -> apply` за один проход;
2) перевести DSL и downstream поэтапно;
3) сохранить стабильность отчетов/тестов/exit-policy во время миграции.

### План удаления legacy (когда и в каком порядке)
PR 1 (MatchSpec DSL as single source):
1) ввести `MatchSpec` + compile;
2) убрать ручную сборку Python `matching_rules.py` из runtime-пути;
3) выключить fallback dedup (`fallback_identity_value`) по умолчанию, затем удалить.

PR 2 (downstream migration to typed contract):
1) перевести resolve/plan/report на `match_decision.status`;
2) убрать `decision_status_to_match_status()` и временные маппинги;
3) удалить дублирующие legacy explainability-поля, оставить один канонический `match_decision`;
4) ввести отдельные diag-коды для ambiguous/invalid-input и убрать `RESOLVE_CONFLICT`-overload.

## Производительность Match/Resolve
Подход для runtime остается:
- микро-батчи (`batch_size`, `flush_interval_ms`);
- runtime-state в existing repositories с run-scope;
- cleanup в `finally`;
- idempotent updates;
- partition-by-identity для queue-based runtime.

Важно:
- это runtime tuning в `Settings`, а не бизнес-правила DSL.

## Нерешенные вопросы/задачи
1) `MatchSpec` DSL:
   - compile-time валидация правил;
   - совместимость с текущим core без переписывания алгоритма.
2) Explainability phase 2:
   - расширение `top_candidates` до evidence-модели.
3) Survivorship DSL:
   - декларативные merge/survivor rules в resolve-слое.
4) Dataset diagnostics catalog split:
   - core-коды отдельно, dataset-коды регистрируются датасетом.

## План следующего этапа (Match DSL)
1) Ввести `MatchSpec` (pydantic).
2) Реализовать `MatchDsl.compile()` -> `MatchingRules`.
3) Перенести employees match-правила из Python в DSL-спеку.
4) Подключить strict-validation на compile-шаге.
5) Сохранить transitional fallback только под feature-flag.
6) После стабилизации удалить fallback путь.

### Детальный пошаговый план реализации (execution-ready)
Ниже план в том порядке, в котором его безопасно выполнять одним проходом.

#### Шаг 0. Зафиксировать baseline (до изменений)
Цель:
1) Зафиксировать текущее поведение matcher для parity-проверок.

Изменения:
1) Не менять runtime-код.
2) Добавить/обновить baseline-тесты на текущем Python-config пути:
   - exact match,
   - fuzzy accept/review/reject,
   - tie -> ambiguous,
   - source duplicate/conflict.

Файлы:
1) `tests/planning/test_matcher_*`
2) `tests/test_stage6_plan.py` (интеграционный сценарий)

Критерий готовности:
1) Полный baseline набор тестов зеленый и будет использоваться как эталон.

#### Шаг 1. Расширить DSL-контракт MatchSpec
Цель:
1) Сделать DSL способным выразить весь runtime-контракт matcher.

Изменения:
1) Расширить `MatchSpec` в `connector/domain/transform/dsl/specs.py`.
2) Добавить модели:
   - `SourceDedupSpec`,
   - `FuzzySpec`,
   - `ComparatorSpec` (или эквивалентные поля в `FuzzySpec`).
3) Добавить compile-time валидации:
   - `0 <= review_threshold <= accept_threshold <= 1`,
   - `tie_delta >= 0`,
   - `top_k >= 1`,
   - `max_candidates >= 1`,
   - для comparator-полей есть weights/comparators (без конфликтов ключей).

Файлы:
1) `connector/domain/transform/dsl/specs.py`

Критерий готовности:
1) `MatchSpec` валидирует все параметры из текущих `MatchingRules`/`FuzzyScoringRules`.
2) Некорректные спецификации падают на compile-time, а не в runtime.

#### Шаг 2. Добавить Match DSL компилятор
Цель:
1) Преобразовывать `MatchSpec` в существующий runtime-контракт без переписывания core-алгоритма.

Изменения:
1) Добавить `connector/domain/transform/matching/match_dsl.py`.
2) Реализовать `MatchDsl.compile(spec: MatchSpec) -> MatchingRules`.
3) Маппинг comparator-имен из DSL в текущие runtime-значения (`exact|casefold|similarity`).
4) Проставлять дефолты строго из DSL-модели (не дублировать дефолты в двух местах).

Файлы:
1) `connector/domain/transform/matching/match_dsl.py`
2) при необходимости `connector/domain/transform/matching/__init__.py`

Критерий готовности:
1) На одном и том же наборе параметров `MatchDsl.compile()` порождает эквивалент текущему `build_matching_rules()`.

#### Шаг 3. Ввести MatchEngine (тонкий runtime wrapper)
Цель:
1) Привести matcher к общей модели `Spec -> Dsl -> Engine -> Core`.

Изменения:
1) Добавить `connector/domain/transform/matching/match_engine.py`.
2) `MatchEngine`:
   - принимает `MatchSpec`,
   - компилирует в `MatchingRules` через `MatchDsl`,
   - создает `DeduplicationTransform` (core),
   - предоставляет метод `match(...)`/`run(...)` без собственной бизнес-логики.

Файлы:
1) `connector/domain/transform/matching/match_engine.py`
2) экспорт в `connector/domain/transform/matching/__init__.py`

Критерий готовности:
1) `MatchEngine` не содержит scoring/dedup/decision-правил, только wiring.

#### Шаг 4. Перенести employees-правила в YAML
Цель:
1) Сделать `datasets/employees.match.yaml` фактическим источником истины.

Изменения:
1) Заполнить `datasets/employees.match.yaml` параметрами из текущего `build_matching_rules()`.
2) Проверить, что в YAML есть:
   - identity rules,
   - source-dedup block,
   - fuzzy block (thresholds/weights/comparators/top_k/tie/max_candidates).

Файлы:
1) `datasets/employees.match.yaml`

Критерий готовности:
1) YAML полностью покрывает текущую конфигурацию employees matcher без Python factory.

#### Шаг 5. Переключить employees runtime на DSL-путь
Цель:
1) Использовать DSL как primary runtime-путь.

Изменения:
1) В `connector/datasets/employees/spec.py`:
   - убрать прямой primary вызов `build_matching_rules()`,
   - подключить `load_match_spec_for_dataset("employees") + MatchDsl.compile()`/`MatchEngine`.
2) Сохранить fallback на Python-rules под feature-flag:
   - `matcher_use_legacy_rules` (или эквивалент).

Файлы:
1) `connector/datasets/employees/spec.py`
2) `connector/config/config.py` + CLI wiring (если флаг задается из settings)

Критерий готовности:
1) По умолчанию работает DSL путь.
2) Legacy fallback можно включить явно для rollback.

#### Шаг 6. Сохранить downstream-совместимость
Цель:
1) Не ломать `resolve/plan/apply` на том же релизе.

Изменения:
1) Оставить transitional adapter typed -> legacy:
   - `decision_status_to_match_status()`.
2) Сохранить `MatchedRow.match_status` как рабочий контракт.
3) Оставить `MatchedRow.match_decision` как каноничный новый контракт.

Файлы:
1) `connector/domain/transform/matching/match_models.py`
2) места использования в `resolve_usecase/import_plan_service` (без поведенческих изменений)

Критерий готовности:
1) Нет регрессий в resolve/plan/apply при включенном DSL matcher.

#### Шаг 7. Диагностика и traceability для DSL matcher
Цель:
1) Удержать единый diagnostic-контракт по стадиям.

Изменения:
1) Для compile/runtime ошибок matcher использовать текущий diagnostics pipeline.
2) Проверить/добавить использование `RowRef` в местах, где формируются matcher diagnostics.
3) Исключить ad-hoc строковые ошибки вне каталога.

Файлы:
1) `connector/domain/transform/dsl/diagnostics.py`
2) `connector/domain/transform/matching/*` (по месту)

Критерий готовности:
1) Diagnostics в matcher идут тем же путем, что и в других DSL-стадиях.

#### Шаг 8. Parity и интеграционные тесты
Цель:
1) Доказать эквивалентность поведения до/после cutover.

Изменения:
1) Добавить parity-тесты "legacy rules vs DSL rules" на одном fixture-наборе.
2) Прогнать интеграционный `import plan` и проверить инварианты:
   - те же итоговые `match_status`,
   - та же классификация source-dedup,
   - корректный проход в resolve.

Файлы:
1) `tests/planning/test_matcher_*`
2) `tests/test_stage6_plan.py`

Критерий готовности:
1) DSL путь повторяет legacy поведение по согласованным сценариям.

#### Шаг 9. Операционный cutover и стабилизация
Цель:
1) Переключить прод-runtime на DSL и собрать телеметрию/диагностику.

Изменения:
1) Включить DSL matcher по умолчанию.
2) Оставить feature-flag rollback на 1-2 релиза.
3) Мониторить:
   - долю `AMBIGUOUS`,
   - долю `CONFLICT_SOURCE`,
   - изменения в not-found rate.

Критерий готовности:
1) Нет существенных отклонений по match quality и latency.

#### Шаг 10. Удалить legacy путь (после стабилизации)
Цель:
1) Убрать второй источник истины и закрыть миграцию.

Изменения:
1) Удалить `build_matching_rules()` как runtime primary source.
2) Удалить fallback feature-flag и dead code.
3) Обновить документацию/diagram/DoD.

Файлы:
1) `connector/datasets/employees/load/matching_rules.py` (или оставить только как compatibility artifact с TODO на удаление)
2) `connector/datasets/employees/spec.py`
3) `docs/DSL_idea.md`

Критерий готовности:
1) Matcher полностью DSL-driven, один runtime-путь, без дублирующих конфигов.

### Статус выполнения плана (текущая реализация)
Ниже зафиксирован фактический статус после миграции matcher на DSL primary path.

1) Шаг 0 (baseline parity): `DONE`
- добавлены/обновлены baseline и parity тесты для exact/fuzzy/tie/source-dedup.

2) Шаг 1 (расширение `MatchSpec`): `DONE`
- `MatchSpec` расширен до полного покрытия runtime-параметров matcher;
- добавлены compile-time проверки порогов, `top_k`, `max_candidates`, `tie_delta` и весов.

3) Шаг 2 (`MatchDsl.compile()`): `DONE`
- реализован компилятор DSL -> `MatchingRules`;
- сохранена совместимость runtime-контракта без переписывания `MatchCore`.

4) Шаг 3 (`MatchEngine`): `DONE`
- добавлен тонкий stage-wrapper `MatchSpec -> MatchDsl -> DeduplicationTransform`.

5) Шаг 4 (employees YAML): `DONE`
- `datasets/employees.match.yaml` заполнен эквивалентом legacy Python-правил.

6) Шаг 5 (runtime switch + fallback flag): `DONE`
- `EmployeesSpec.build_planning_bundle(...)` переключен на DSL как primary;
- fallback на legacy rules оставлен через `settings.matcher_use_legacy_rules`;
- параметр добавлен в settings merge (`ENV/config/defaults`).

7) Шаг 6 (downstream совместимость): `DONE`
- transitional typed->legacy адаптер сохранен;
- `resolve/plan/apply` контракт не сломан.

8) Шаг 7 (diagnostics traceability): `DONE`
- matcher использует текущий diagnostics pipeline;
- DSL diagnostics helper переведен на `RowRef | None`;
- для map/normalize/match стадий прокидывается `record_ref` в едином формате.

9) Шаг 8 (parity + integration regression): `DONE`
- parity-тесты и planning/integration тесты проходят;
- полный `pytest` зеленый на текущем срезе.

10) Шаг 9 (операционный cutover): `DONE` (для кодовой части)
- DSL путь активен по умолчанию;
- rollback через feature-flag присутствует.

11) Шаг 10 (удаление legacy пути): `PENDING`
- намеренно отложено до стабилизации;
- legacy нужен как контролируемый rollback.

### Архитектурные договоренности для matcher-миграции
1) Для matcher сохраняется единая модель стадий:
   - `MatchSpec -> MatchDsl -> MatchEngine -> MatchCore`.
2) `MatchCore` является единственным местом бизнес-решения:
   - candidate generation;
   - exact/fuzzy policy;
   - scoring/threshold/tie policy;
   - source-dedup policy.
3) `MatchUseCase` не содержит dedup/scoring/decision-правил:
   - только orchestration, batching, lifecycle и report I/O.
4) Dataset-специфика matcher должна задаваться декларативно в `MatchSpec`,
   а не в Python factory/wiring.
5) До полного cutover допускается transitional adapter typed -> legacy,
   но новый функционал добавляется только в typed/DSL путь.

## Результаты детального анализа (matcher migration + DSL kernel)
Этот раздел фиксирует итог двух технических анализов и является опорой для дальнейшей реализации.

### 1) Фактическое состояние matcher (as-is)
Текущий runtime-путь:
1) `connector/datasets/employees/spec.py`:
   - `build_planning_bundle()` использует `load_match_spec_for_dataset(...) + MatchDsl.compile(...)`.
2) `connector/domain/transform/matching/match_core.py`:
   - уже содержит полноценный `MatchCore`:
     - identity candidate generation;
     - exact-first + fuzzy fallback;
     - weighted scoring + thresholds + tie;
     - source-dedup в ядре.
3) `connector/domain/transform/matching/match_models.py`:
   - typed match-контракт (`MatchDecision*`) уже внедрен.
4) `connector/datasets/employees/load/matching_rules.py`:
   - удален (legacy runtime path закрыт).

Вывод:
1) бизнес-алгоритм matcher уже в правильном месте (core);
2) source of truth для конфигурации matcher — DSL YAML.

### 2) Фактическое состояние DSL ядра (as-is)
DSL kernel уже стабилен и переиспользуется в map/normalize/enrich:
1) `connector/domain/transform/dsl/specs.py` — pydantic-модели;
2) `connector/domain/transform/dsl/loader.py` — загрузка dataset DSL из `datasets/registry.yml`;
3) `connector/domain/transform/dsl/engine.py` + `registry.py` + `ops.py` — универсальный execution kernel;
4) `connector/domain/transform/dsl/diagnostics.py` — bridge `DslIssue -> DiagnosticItem`.

Для matcher уже есть часть инфраструктуры:
1) `load_match_spec_for_dataset()` в `loader.py`;
2) `MatchSpec` в `specs.py`.

Пробел:
1) `MatchSpec` пока минимальный (identity_rules/ignored_fields) и не покрывает runtime-параметры matcher;
2) `MatchDsl`/`MatchEngine` отсутствуют как формальный слой compile/runtime для match.

### 3) Что переиспользуем без изменений (reuse-first)
1) `DeduplicationTransform` как `MatchCore` (не переписывать алгоритм).
2) `MatchingRules`/`FuzzyScoringRules` как runtime-контракт matcher.
3) `MatchUseCase`/`MatchStage` как orchestration/runtime-слой.
4) `scoring.py` как единый модуль ранжирования/threshold/tie.
5) `dsl.loader` как единый вход загрузки dataset-спеки.

### 4) Что добавляем минимально (без второго runtime-пути)
1) Расширяем `MatchSpec` в `dsl/specs.py` до полного покрытия:
   - `identity_rules`,
   - `source_dedup`,
   - `fuzzy`:
     - `blocking_keys`, `comparators`, `weights`,
     - `accept_threshold`, `review_threshold`,
     - `tie_delta`, `max_candidates`, `top_k`, `score_round`.
2) Добавляем `MatchDsl` (compile-layer):
   - `MatchSpec -> MatchingRules`.
3) Добавляем `MatchEngine` (тонкая обвязка):
   - получает `MatchSpec`,
   - через `MatchDsl` создает `MatchingRules`,
   - инициализирует `DeduplicationTransform`.
4) Переключаем `EmployeesSpec.build_planning_bundle()`:
   - с `build_matching_rules()`
   - на `load_match_spec_for_dataset("employees") + MatchDsl.compile()`.

### 5) Что не делаем (анти-дублирование)
1) Не переносим fuzzy/scoring алгоритм в `dsl/ops.py` (это не pure value transform).
2) Не создаем альтернативный matcher-core параллельно `DeduplicationTransform`.
3) Не дублируем decision/dedup в `MatchUseCase`.
4) Не добавляем второй источник истины для match-правил (Python+DSL одновременно как primary).

### 6) Границы ответственности (чтобы не размыть архитектуру)
1) `MatchCore` (`DeduplicationTransform`):
   - только business decision матчинга.
2) `MatchDsl`:
   - только compile DSL -> runtime rules.
3) `MatchEngine`:
   - только stage-runtime wiring (`spec -> dsl -> core`).
4) `MatchUseCase`:
   - batching/flush/lifecycle/report orchestration.

### 7) Технические риски и защита от регрессий
Основной риск:
1) изменение поведения matcher при switch Python rules -> DSL rules.

Контроль:
1) parity-тесты на старом и новом источнике правил:
   - exact match,
   - fuzzy accept/review/reject/tie,
   - source duplicate/conflict.
2) интеграционный тест `import plan` на неизменность downstream-контракта.

### 8) Рекомендации по совместимости diagnostics
Наблюдение:
1) в `dsl/diagnostics.py` используется `record_ref: str | None`.
2) доменный контракт diagnostics ориентирован на `RowRef`.

Рекомендация:
1) перевести DSL diagnostics helper на `RowRef | None`,
2) чтобы у всех стадий был единый traceability-контракт.

### 9) Безопасный порядок cutover (операционный)
1) Расширить `MatchSpec` + заполнить `datasets/employees.match.yaml`.
2) Ввести `MatchDsl` (compile).
3) Подключить DSL-компиляцию в `EmployeesSpec` (feature-flag допустим на переходе).
4) Прогнать parity/regression тесты.
5) После стабилизации удалить `build_matching_rules()` как runtime primary source — закрыто.

### 10) Практические сценарии покрытия matcher (rule + data + expected)
Ниже фиксируются базовые эталонные сценарии для проверки покрытия алгоритма и будущей DSL-конфигурации.

Сценарий A: deterministic exact match
1) Правило:
   - `identity_rules` включает primary key `match_key`,
   - `fuzzy.enabled = false`.
2) Данные:
   - source: `match_key=org1|tab123`,
   - cache: одна запись с тем же `match_key`.
3) Ожидание:
   - `status = MATCHED`,
   - `match_mode = exact`,
   - `score = 1.0`,
   - `reason = identity_exact`.

Сценарий B: source dedup conflict внутри одного батча
1) Правило:
   - `source_dedup.enabled = true`,
   - `on_duplicate = warn`,
   - `on_conflict = error`.
2) Данные:
   - row A и row B имеют один и тот же canonical dedup-key:
     `dataset:identity_primary:identity_value`,
   - fingerprint у строк различается.
3) Ожидание:
   - первая строка проходит,
   - вторая получает `CONFLICT_SOURCE` и `row=None` (hard drop),
   - запись фиксируется в matcher-отчете, но не идет в resolve.

Сценарий C: fuzzy fallback + weighted scoring
1) Правило:
   - `fuzzy.enabled = true`,
   - заданы `blocking_keys`, `comparators`, `weights`,
   - заданы `accept_threshold/review_threshold`.
2) Данные:
   - exact-identity не найден,
   - по blocking keys найдено несколько кандидатов.
3) Ожидание:
   - выполняется ranking кандидатов,
   - если лучший score >= `accept_threshold` -> `MATCHED`,
   - если лучший score < `review_threshold` -> `NOT_FOUND`.

Сценарий D: ambiguity/tie-case
1) Правило:
   - `fuzzy.enabled = true`,
   - задан `tie_delta`.
2) Данные:
   - два лучших кандидата имеют score с разницей меньше `tie_delta`.
3) Ожидание:
   - `status = AMBIGUOUS`,
   - `reason = fuzzy_tie` (или review-путь),
   - `top_candidates` заполнен,
   - downstream не должен интерпретировать результат как executable `create/update`.

## Definition of Done для этапа Match DSL
1) Match поведение задается из dataset-spec, без ручной сборки rules в коде.
2) Добавление нового датасета не требует правок match-core.
3) Все fuzzy/source-dedup параметры декларативны.
4) Тесты покрывают:
   - exact/fuzzy/tie,
   - source-dedup policies,
   - compile validation,
   - backward-compat runtime path.

## Lookup templates (кратко)
Можно поддерживать шаблоны lookup-правил в enrich/match DSL:
```yaml
lookup_templates:
  manager_by_full_name:
    provider:
      name: cache.by_field
      args: {dataset: employees, field: full_name}
    value_path: _id
```

Это сокращает дублирование однотипных lookup-описаний между правилами.
