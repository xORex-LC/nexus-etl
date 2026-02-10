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

## Связь с Cache DSL / Loader / Sink Specs
Чтобы не смешивать разные домены ответственности, фиксируем:
1) Cache DSL живет отдельным контуром (`docs/Cache_DSL.md`) и использует тот же `domain/dsl/loader.py` как transport+validation entrypoint.
2) Loader под cache расширяется функциями `load_cache_registry_spec/load_cache_dataset_spec/load_cache_sync_spec`, но не выполняет semantic compile/check графа зависимостей.
3) Sink-контракты разделяются:
   - `SinkModelSpec` (модель данных датасета),
   - `SinkStorageSpec` (transport/backend поведение).
4) `plan/apply/cache` используют эти контракты совместно:
   - `SinkModelSpec` для структуры/валидации/диффа,
   - `SinkStorageSpec` для runtime I/O политики.

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
- `match_decision.status`
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

### Принципы миграции Resolve на DSL
1) Для resolver используется та же модель стадий: `ResolveSpec -> ResolveDsl -> ResolveEngine -> ResolveCore`.
2) `ResolveCore` (класс `connector/domain/transform/resolver/resolve_core.py`) остается единственным местом доменных решений.
3) `ResolveEngine` содержит только runtime wiring (`spec -> dsl.compile() -> core`), без бизнес-логики.
4) `ResolveUseCase` содержит только orchestration.
`ResolveUseCase` отвечает за batching/flush, lifecycle, retention cleanup, report I/O.
5) Dataset-правила resolver задаются декларативно в YAML, а не через Python factory.
6) DSL-миграция resolver не должна вносить второй runtime-путь.
Нельзя оставлять `Python rules` и `DSL rules` как два равноправных источника истины.
7) Existing алгоритм `ResolveCore` переиспользуется без переписывания.
Переносятся только источник конфигурации и wiring.
8) Pending replay в `import_plan_service` считается техдолгом до этапа `Plan/Resolve DSL`.
Replay не должен надолго оставаться местом, где принимаются match-like решения в usecase.
9) Diagnostics должны идти единым путем через текущий diagnostics-layer.
Resolver DSL не добавляет ad-hoc ошибок и не обходит каталог кодов.

### Подтвержденный алгоритм миграции Resolve (execution-ready)
1) Источник правил:
   - `datasets/employees.resolve.yaml` является единственным source of truth для resolver-правил.
2) DSL-модель (`ResolveSpec`) покрывает runtime-контракт:
   - `resolve.desired_state`,
   - `resolve.source_ref`,
   - `resolve.diff`,
   - `resolve.merge`,
   - `resolve.secrets`,
   - `resolve.links`.
3) `ResolveDsl.compile(spec)` компилирует только в `ResolveRules + LinkRules` без второго runtime-пути.
4) Runtime settings (`pending_*`, batching/flush) остаются в `Settings` и `ResolveUseCase`.
5) Sink-validation для resolver остается targeted (только по измененным resolver-полям).
6) Pending replay в `import_plan_service` остается техдолгом до этапа `Plan/Resolve DSL`.

### Реализованные built-in блоки Resolve DSL v2
1) `resolve.desired_state.mode=project_fields`:
   - собирает `desired_state` из выбранных полей входной строки.
2) `resolve.source_ref.mode=from_identity`:
   - строит `source_ref` из ключей `Identity`.
3) `resolve.diff.mode=compare_fields`:
   - field-level сравнение `desired` vs `existing` с нормализацией (`none|text|bool`),
   - поддержка alias-полей (`existing`, `output`),
   - поддержка `from_sink` для сборки базового списка diff-полей из sink-спеки
     с последующим override в `resolve.diff.fields` (уменьшает дублирование YAML).
4) `resolve.merge.mode`:
   - `none`,
   - `fill_empty_from_existing` с field-level правилами.
5) `resolve.secrets.mode=by_op`:
   - явные списки секретных полей для `create/update`.

### Какие данные employees используются для resolver-декларации
1) Link-поля (прямо участвуют в resolve):
   - `manager_id`,
   - `organization_id`.
2) Link dedup narrowing:
   - для `manager_id` -> `organization_id`,
   - для `organization_id` -> `code` (из target dataset).
3) Поля `desired_state`, влияющие на diff/update:
   - `email`, `last_name`, `first_name`, `middle_name`,
   - `is_logon_disable`, `user_name`, `phone`,
   - `personnel_number`, `manager_id`, `organization_id`,
   - `position`, `avatar_id`, `usr_org_tab_num`.
4) Secret flow:
   - `password` управляется через `resolve.secrets.by_op`.
5) Identity/source-ref для resolver:
   - `match_key` (primary),
   - `usr_org_tab_num` (доступен как дополнительный identity value при необходимости).
6) Lookup key names в resolve-links:
   - `match_key`, `name`, `_ouid`, `code`.

### Статус реализации Resolve DSL (текущий срез)
Выполнено:
1) Resolve мигрирован на один DSL-driven runtime path (`ResolveSpec -> ResolveDsl -> ResolveEngine -> ResolveCore`).
2) `datasets/employees.resolve.yaml` переведен на v2-структуру (`desired_state/source_ref/diff/merge/secrets/links`).
3) Удален legacy runtime source:
   - `connector/datasets/employees/load/resolve_rules.py`,
   - связанные legacy diff helpers.
4) `EmployeesSpec.build_planning_bundle()` больше не использует strategy registry.
5) `ResolveDsl` больше не содержит dual-path compile ветки.
6) `resolve` тесты обновлены и проходят на v2-конфиге.
7) Resolver-core сохраняет targeted sink-validation для измененных resolver-полей.

Остается техдолг:
1) Pending replay в `import_plan_service` до полного перехода `Plan/Resolve DSL`.

### Resolve DSL v2 — итоги cutover
1) Runtime wiring полностью переключен на `load_resolve_spec_for_dataset() + ResolveDsl.compile()`.
2) Resolver использует один конфигурационный источник (`employees.resolve.yaml`) без python strategy-factory.
3) `ResolveCore` продолжает быть единственным resolver-core (алгоритм не дублируется).
4) `ResolveUseCase` остается orchestration-only (batching/flush/cleanup/report).
5) Targeted sink-validation для resolver-полей включена и покрыта тестами.
6) Pending replay в `import_plan_service` остается отдельным техдолгом до этапа `Plan/Resolve DSL`.

## Актуальная проблема (закрыта): Match DSL
Match-правила переведены с Python-конфига на декларативный `MatchSpec`.

В DSL вынесено:
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
1) Resolve-правила выделены в отдельный DSL path (`employees.resolve.yaml`) и не смешиваются с matcher.
2) Legacy `projector.py` удален:
   - matcher-конфигурация полностью задается через `datasets/employees.match.yaml`,
   - отдельный Python-проектор больше не участвует в runtime-пути.

Что уже ушло после завершения Match DSL:
1) прямой runtime-вызов `build_matching_rules()` из dataset wiring;
2) ручная Python-сборка параметров match как primary source.

Текущее состояние:
1) transitional adapter typed -> legacy statuses удален;
2) fallback dedup policy удален;
3) matcher работает по одному DSL-driven runtime-пути.

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
2) `MatchedRow` переведен на единый typed-контракт:
   - `match_decision` является обязательным полем;
   - downstream (resolve/plan/report) читает только `match_decision.status`.
3) Source dedup-key закреплен как канонический:
   - `dataset:identity_primary:identity_value`
   - transitional fallback по `identity_value` удален.
4) `PlanningBundle` очищен от дублирующего runtime-контракта:
   - удален `matching_rules`;
   - для pending-replay используется `match_spec.match.ignored_fields`.

### Transitional legacy (зафиксировано после текущего шага)
По matcher-потоку (`match -> resolve -> plan`) legacy-ветки удалены:
1) `MatchedRow.match_status` удален.
2) `decision_status_to_match_status()` удален.
3) `source_dedup.fallback_identity_value` и `_fallback` dedup-key удалены.
4) dual runtime path (`PlanningBundle.matching_rules` + `match_spec`) удален.

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
1) П.6 (дубли explainability-полей рядом с `match_decision`) — закрыто:
   - в `MatchedRow` оставлен единый канонический `match_decision`.
2) Legacy runtime fallback на Python-rules — закрыто:
   - runtime-ветка `matcher_use_legacy_rules` удалена.
3) Legacy Python match factory (`connector/datasets/employees/load/matching_rules.py`) — закрыто:
   - файл удален из runtime и из тестового контура;
   - matcher-конфигурация идет только через `datasets/employees.match.yaml` + `MatchDsl`.
4) П.7 (`fallback_identity_value` + fallback dedup-key) — закрыто:
   - fallback удален из `MatchSpec`, `SourceDedupRules` и `MatchCore`.

Пока рано убирать (нужна миграция downstream):
1) Нормализация diagnostic-кодов под `AMBIGUOUS`/`CONFLICT_SOURCE` в отчётной аналитике.

Рекомендуемый порядок снятия legacy (обновленный):
1) Закрыть matcher/runtime legacy (выполнено).
2) Зафиксировать диагностический контракт для новых matcher-статусов.
3) Перейти к DSL-миграции resolver без возврата к dual-контрактам.

Почему так:
1) не ломать текущий `match -> resolve -> plan -> apply` за один проход;
2) перевести DSL и downstream поэтапно;
3) сохранить стабильность отчетов/тестов/exit-policy во время миграции.

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

## План следующего этапа (после Match DSL)
Матчер закрыт как DSL-driven стадия. Следующий этап:
1) миграция `resolve` на аналогичную модель (`ResolveSpec -> ResolveDsl -> ResolveEngine -> ResolveCore`);
2) расширение explainability (`top_candidates` -> `evidence`);
3) survivorship rules в resolve-DSL;
4) harmonization diagnostics для новых typed-статусов матчинга.

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
5) Legacy-ветки matcher удалены:
   - нет dual runtime path для правил;
   - нет typed -> legacy adapter;
   - `match_decision` — единственный рабочий контракт результата.

## Результаты детального анализа (matcher migration + DSL kernel)
Этот раздел фиксирует итог двух технических анализов и является опорой для дальнейшей реализации.

### 1) Фактическое состояние matcher (as-is)
Текущий runtime-путь:
1) `connector/datasets/employees/spec.py`:
   - `build_planning_bundle()` использует `load_match_spec_for_dataset(...) + MatchDsl.compile(...)`.
2) `connector/domain/transform/matcher/match_core.py`:
   - уже содержит полноценный `MatchCore`:
     - identity candidate generation;
     - exact-first + fuzzy fallback;
     - weighted scoring + thresholds + tie;
     - source-dedup в ядре.
3) `connector/domain/transform/matcher/match_models.py`:
   - typed match-контракт (`MatchDecision*`) уже внедрен.
4) `connector/datasets/employees/load/matching_rules.py`:
   - удален (legacy runtime path закрыт).

Вывод:
1) бизнес-алгоритм matcher уже в правильном месте (core);
2) source of truth для конфигурации matcher — DSL YAML.

### 2) Фактическое состояние DSL ядра (as-is)
DSL kernel уже стабилен и переиспользуется в map/normalize/enrich:
1) `connector/domain/dsl/specs.py` — pydantic-модели;
2) `connector/domain/dsl/loader.py` — загрузка dataset DSL из `datasets/registry.yml`;
3) `connector/domain/dsl/engine.py` + `registry.py` + `ops.py` — универсальный execution kernel;
4) `connector/domain/dsl/diagnostics.py` — bridge `DslIssue -> DiagnosticItem`.

Для matcher уже есть часть инфраструктуры:
1) `load_match_spec_for_dataset()` в `loader.py`;
2) `MatchSpec` в `specs.py`.

Статус:
1) `MatchSpec` расширен и покрывает runtime-параметры matcher:
   - `identity_rules`, `source_dedup`, `fuzzy` (`blocking_keys`, `comparators`, `weights`, `thresholds`, `tie_delta`, `max_candidates`, `top_k`, `score_round`).
2) `MatchDsl` и `MatchEngine` введены и используются как формальный compile/runtime слой.

### 3) Что переиспользуем без изменений (reuse-first)
1) `MatchCore` как ядро matcher (не переписывать алгоритм).
2) `MatchingRules`/`FuzzyScoringRules` как runtime-контракт matcher.
3) `MatchUseCase`/`MatchStage` как orchestration/runtime-слой.
4) `scoring.py` как единый модуль ранжирования/threshold/tie.
5) `dsl.loader` как единый вход загрузки dataset-спеки.

### 4) Что уже реализовано (без второго runtime-пути)
1) `MatchSpec` расширен в `dsl/specs.py` до полного покрытия matcher.
2) `MatchDsl` реализован (`MatchSpec -> MatchingRules`).
3) `MatchEngine` реализован как тонкая обвязка (`spec -> dsl -> core`).
4) `EmployeesSpec.build_planning_bundle()` переключен на:
   - `load_match_spec_for_dataset("employees") + MatchDsl.compile()`.
5) Legacy factory `connector/datasets/employees/load/matching_rules.py` удален.

### 5) Что не делаем (анти-дублирование)
1) Не переносим fuzzy/scoring алгоритм в `dsl/ops.py` (это не pure value transform).
2) Не создаем альтернативный matcher-core параллельно `MatchCore`.
3) Не дублируем decision/dedup в `MatchUseCase`.
4) Не добавляем второй источник истины для match-правил (Python+DSL одновременно как primary).

### 6) Границы ответственности (чтобы не размыть архитектуру)
1) `MatchCore`:
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
1) Расширить `MatchSpec` + заполнить `datasets/employees.match.yaml` — закрыто.
2) Ввести `MatchDsl` (compile) — закрыто.
3) Подключить DSL-компиляцию в `EmployeesSpec` — закрыто.
4) Прогнать parity/regression тесты — закрыто.
5) Удалить `build_matching_rules()` как runtime primary source — закрыто.

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
   - единый DSL-driven runtime path.

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
