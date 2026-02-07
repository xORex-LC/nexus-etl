# Dataset DSL idea (черновик)

## Цель
Упростить добавление новых датасетов без переписывания большого количества модулей.

## Идея
Ввести минимальный DSL (YAML/JSON) для описания:
- mapping
- normalize
- enrich
- validate
- (опционально) plan/apply

Движок читает DSL и сам собирает правила. Для нестандартных кейсов использовать `custom` правила, реализованные в коде.

## Единая модель DSL-обвязки для всех стадий
Цель: чтобы **каждая стадия выглядела одинаково архитектурно**, а различалась только типом правил и бизнес-логикой.

### Общая схема (для любой стадии)
1) **StageRules (StageSpec)** — pydantic‑модель DSL правил стадии  
2) **StageDsl** — компилятор DSL → CoreSpec/StageCore  
3) **StageEngine** — DSL‑wrapper/исполнитель (единый интерфейс запуска)  
4) **StageCore** — бизнес‑логика стадии (без YAML/DSL, чистая логика)  
5) (Опционально) **StageReport / StageResolver / StageProviders** — только если у стадии есть специфические сайд‑эффекты

### Почему так
- DSL для всех стадий одинаков по форме (Rules/Dsl/Engine/Core)
- Ядра стадий остаются чистыми и тестируемыми
- DSL можно расширять без переписывания StageCore

## Принципы реализации DSL для `map/normalize/enrich`
Эти принципы фиксируют текущую договорённость и являются ориентирами для перевода остальных стадий.

### 1. Единый каркас стадии
Для каждой DSL-стадии сохраняем одинаковую форму:
- `StageSpec` (Pydantic-модель правил из YAML)
- `StageDsl` (compile: spec -> core-spec/core)
- `StageEngine` (runtime обвязка стадии)
- `StageCore` (бизнес-логика стадии)

Текущие соответствия:
- `MappingSpec -> MapperDsl -> MapperEngine -> MapperCore`
- `NormalizeSpec -> NormalizerDsl -> NormalizerEngine -> NormalizerCore`
- `EnrichSpec -> EnricherDsl -> EnricherEngine -> EnricherCore`

### 2. Жёсткая граница ответственности
- `TransformationEngine`:
  - только исполнение `ops` (pure value transforms);
  - не содержит IO, cache/vault/pending/policy orchestration.
- `StageCore`:
  - orchestration стадии, merge/strictness-политики, принятие решений;
  - работа с зависимостями и side-effects (если это часть стадии).
- `StageDsl`:
  - компоновка spec в executable-конфигурацию core;
  - провайдерный wiring для enrich.

### 3. Диагностика вместо исключений
- Ошибки правил и ops накапливаются как diagnostics (`errors/warnings`) и идут с записью дальше.
- Исключения остаются для truly unexpected/runtime ошибок.
- `on_error` policy правила определяет soft/hard поведение.

### 4. Декларативность dataset-специфики
- Всё, что можно выразить через YAML, выносим в `datasets/*.yaml`.
- Dataset-код в Python допустим только как transitional слой или runtime wiring.
- Именование ops и правил без dataset-специфики (`split_name`, `coalesce`, `default_uuid` и т.д.).

### 5. Проверки sink-контракта
- `map`: структурная/required проверка (не ломая поток лишними hard-fail).
- `normalize`: строгая типизация/nullable-check против sink schema.
- `enrich`: проверяет корректность только в своей зоне ответственности (lookup/generate/secret flow), без дублирования normalize-checks.

### 6. Секреты и match_key
- `match_key` и `secrets` не принадлежат map-стадии.
- Формирование `match_key` и обработка секретов живут в enrich-логике.
- После записи в vault секретные поля очищаются из row; маркер полей хранится в `meta`.

### 7. Reuse-first для новых стадий
Перед добавлением логики в новую стадию:
1) проверяем, есть ли это уже в shared DSL kernel (`ops/helpers/diagnostics`);
2) если это pure transform -> добавляем в `ops`;
3) если нужен IO/policy -> оставляем в `StageCore`.

### 8. Критерий «не переусложнить»
Любая новая абстракция допускается только если:
- уменьшает дублирование в 2+ стадиях;
- упрощает подключение нового dataset через YAML;
- не вводит второй параллельный runtime-путь.

### Минимальные базовые абстракции (псевдокод)
```python
class StageRules(Protocol): ...

class StageCore(Protocol):
    def apply(self, record: TransformableRecord) -> TransformableRecord: ...

class StageDsl(Protocol):
    def compile(self, rules: StageRules) -> StageCore: ...

class StageEngine(Generic[R, C]):
    def __init__(self, rules: R, dsl: StageDsl[R, C]):
        self.core = dsl.compile(rules)

    def execute(self, record: TransformableRecord) -> TransformableRecord:
        return self.core.apply(record)
```

### Соответствие стадий
- **Mapping**
  - MappingRules (DSL)
  - MapperDsl → MapperCore
  - MapperEngine (DSL wrapper)
- **Normalize**
  - NormalizeRules
  - NormalizeDsl → NormalizerCore
  - NormalizerEngine
- **Enrich**
  - EnrichRules
  - EnrichDsl → EnricherCore
  - EnricherEngine  
  - Внутри EnricherCore допускаются сайд‑эффекты (vault, cache, lookups).
- **Validate**
  - ValidateRules
  - ValidateDsl → ValidatorCore
  - ValidatorEngine
- **Match/Resolve (переезд в transform)**
  - MatchRules / ResolveRules
  - MatchDsl / ResolveDsl → MatchCore / ResolveCore
  - MatchEngine / ResolveEngine

## Текущая проблема (Match, transitional)
Сейчас часть доменной логики `match` находится в `MatchUseCase`, а не в `MatchCore`:
- source-batch дедуп (`duplicate/conflict in source`) выполняется внутри use-case;
- это смешивает orchestration и бизнес-правила стадии.

Почему это проблема:
- use-case должен координировать выполнение стадии, а не содержать правила матчинга;
- при добавлении нового dataset придется менять use-case вместо декларативных правил;
- ломается единый принцип `StageSpec -> StageDsl -> StageEngine -> StageCore`.

Целевое состояние:
1) source-batch dedup переносится в `MatchCore` (или отдельную dedup-policy внутри match-ядра);
2) `MatchUseCase` оставляет только orchestration/report;
3) поведение dedup задается dataset-правилами/DSL (`enabled`, `identity_key`, `on_duplicate`, `on_conflict`).

### Зафиксированные решения по переносу source-dedup (до DSL)
1) Политики dedup (`on_duplicate`, `on_conflict`, `enabled`) задаются в dataset-правилах matcher.
   - На текущем шаге это Python-правила (`MatchingRules`), без DSL.
   - DSL-описание этих политик добавляется позже, отдельным этапом.

2) Поведение при source duplicate/conflict:
   - запись должна попадать в match-report с диагностикой;
   - запись не должна идти в resolver;
   - технически это означает `hard-drop` на matcher-стадии (`row=None` после классификации).

3) Канонический dedup-key:
   - основной ключ: `(dataset, identity_primary, identity_value)`;
   - временно допускается fallback на `identity_value`, если `identity_primary` отсутствует;
   - fallback считается transitional-режимом совместимости.

## Текущая проблема (производительность/latency на Match+Resolve)
Сейчас `match` и `resolve` используют stateful-механику, которая в текущем runtime может приводить к накоплению данных:
- в `match` есть source-dedup по identity/fingerprint;
- в `resolve` есть batch-индексы и pending-логика.

Риск:
- при переходе на потоковую доставку (например, RMQ) первые стадии (`map/normalize/enrich`) будут идти стримом,
  а `match/resolve` станут точками задержки и роста памяти.

Краткое решение:
1) Перейти на микро-батчи для `match` и `resolve` (`batch_size + flush_interval_ms`).
2) Вынести состояние между окнами в внешний store:
   - dedup-state (`identity -> fingerprint`, TTL),
   - pending-state/attempts для resolve.
3) Для очередей использовать стабильный partition key по identity, чтобы один identity обрабатывался последовательно.
4) Сохранить idempotency на записи состояния и обработке retry.

## Идея развития Match: Fuzzy + Confidence Scoring
Цель:
- расширить `match` от strict identity-lookup до управляемого сопоставления с оценкой вероятности совпадения.

Что добавляем (минимум):
1) Fuzzy-comparators для строковых полей (после нормализации значений).
2) Weighted scoring (веса полей + агрегированный score).
3) Пороговые решения:
   - `score >= accept_threshold` -> `MATCHED`
   - `review_threshold <= score < accept_threshold` -> `CONFLICT_TARGET` / `NEEDS_REVIEW`
   - `score < review_threshold` -> `NOT_FOUND`

Краткий алгоритм:
1) Candidate generation:
   - сначала exact/blocking-кандидаты по ключам (identity/block keys),
   - затем fuzzy-evaluation только на ограниченном наборе кандидатов.
2) Field scoring:
   - для каждого поля применяем comparator (`exact`, `casefold`, `similarity`),
   - умножаем на вес поля,
   - считаем итоговый score.
3) Decision:
   - выбираем top-1 и top-k кандидатов,
   - применяем thresholds и tie-policy.
4) Output:
   - в результат match передаем `score`, `match_mode`, `decision_reason`, `top_candidates` (ограниченно).

Где хранить правила:
- в dataset DSL (`MatchSpec`):
  - `blocking_keys`
  - `comparators`/`weights`
  - `thresholds`
  - `tie_policy`

План внедрения (поэтапно):
1) MVP: один fuzzy comparator + weighted score + thresholds.
2) Расширить `MatchedRow` метаданными scoring.
3) Перенести source-dedup из use-case в match-core (единая доменная логика стадии).
4) После стабилизации вынести все match-rules в декларативный `MatchSpec`.

### Базовый контракт до DSL (Phase 1)
До декларативного `MatchSpec` фиксируем typed-результат решения матчинга:

1) `MatchDecisionStatus`:
   - `MATCHED`
   - `NOT_FOUND`
   - `AMBIGUOUS`
   - `CONFLICT_SOURCE`
   - `INVALID_INPUT`

2) `MatchCandidate`:
   - `target_id`
   - `identity`
   - `score`
   - `match_mode` (`exact|fuzzy`)
   - `evidence` (опционально)

3) `MatchDecision`:
   - `status: MatchDecisionStatus`
   - `reason_code`
   - `message`
   - `selected`
   - `candidates`
   - `score`
   - `meta`

Зачем это нужно:
- убрать “магические строки” в match-логике;
- зафиксировать единый выходной контракт перед переносом правил в DSL;
- упростить оркестрацию use-case (use-case читает `decision.status`, а не набор ad-hoc проверок).

Переходная совместимость:
- временно допускается адаптер `MatchDecisionStatus -> MatchStatus`,
  чтобы не ломать resolver/plan в одном шаге.
- на этапе миграции `AMBIGUOUS` может временно маппиться в текущий `CONFLICT_TARGET`.

### Канонический dedup-key и fingerprint policy (Phase 1.1)
Что фиксируем как инвариант:
1) Source-dedup выполняется по каноническому ключу:
   - `(dataset, identity_primary, identity_value)`
2) Для сравнения “дубликат/конфликт” используется fingerprint от `desired_state`:
   - fingerprint строится детерминированно,
   - `ignored_fields` задаются dataset-правилами,
   - одинаковый dedup-key + одинаковый fingerprint = duplicate,
   - одинаковый dedup-key + разный fingerprint = source-conflict.

Текущее ограничение (transitional):
- сейчас dedup в use-case местами опирается только на `identity_value`,
  что потенциально создаёт коллизии при разных `identity_primary`.

Целевое состояние:
1) dedup-key используется только в каноническом виде (`dataset+primary+value`);
2) логика source-dedup переносится из use-case в match-core;
3) use-case не содержит ad-hoc правил дедупа.

### Ambiguous semantics (Phase 1.2)
Цель:
- отделить неоднозначность матчинга от “жёсткого конфликта”, чтобы fuzzy/scoring имели управляемый контракт.

Правило:
1) `MATCHED`:
   - `score >= accept_threshold`
2) `AMBIGUOUS`:
   - `review_threshold <= score < accept_threshold`
   - либо tie в top-кандидатах при `tie_policy=review`
3) `NOT_FOUND`:
   - `score < review_threshold`

Поведение по стадиям:
1) Matcher:
   - возвращает typed-решение со статусом, score, reason и top-candidates.
2) Resolver:
   - не выполняет обычный resolve-path для `AMBIGUOUS`;
   - формирует диагностику (`MATCH_AMBIGUOUS` / `RESOLVE_SKIPPED_AMBIGUOUS`).
3) Plan:
   - `AMBIGUOUS` не попадает в исполняемые операции (`create/update`);
   - учитывается в отчёте и summary (`ambiguous_count`).
4) Exit policy:
   - ambiguous без hard-errors -> `CONFLICT`;
   - system/runtime ошибки обрабатываются отдельной политикой.

Минимальный план внедрения:
1) Ввести typed-status `AMBIGUOUS` в match-контракт.
2) Добавить в matcher вычисление статуса по thresholds.
3) Прокинуть статус в resolve/plan и исключить ambiguous из executable items.
4) Добавить счётчики/репорт для ambiguous.

### Роль TransformationEngine
**TransformationEngine = универсальный исполнитель ops**.  
Он используется там, где логика стадии сводится к применению операций:
- MapperCore (apply ops к source → row)
- NormalizerCore (apply ops к row)
- EnricherCore (apply ops для allow_if/compute/lookup keys)
Сайд‑эффекты и политики остаются в StageCore, **не в TransformationEngine**.

## Общие helpers/обвязки DSL (минимальный рефактор)
Цель: убрать дублирование между Mapper/Normalize/Enrich, **без изменения логики**.

### Общие функции/классы (кандидаты на вынос)
1) **apply_ops(engine, value, ops) -> (value, issues)**  
   Используется во всех DSL‑стадиях при применении операций.
2) **read_value(record_values, row_values, path)**  
   Унифицированное чтение `record.*` / `row.*` / plain‑fields.
3) **read_value_path(obj, path)**  
   Доступ к вложенным полям (для lookup/value_path).
4) **to_mapping(value)**  
   Приведение dataclass/obj к mapping для нормализации.
5) **append_dsl_issue(...) / append_dsl_issues(...)**  
   Преобразование `DslIssue` → `DiagnosticItem` с учётом `on_error`.

### Где живут сейчас (для ориентира)
- Mapper: `mapper_core.py` (`_resolve_rule_value`, `_read_value`, `_append_issue`)
- Normalize: `normalizer_core.py` (`_append_issue`, `_to_mapping`)
- Enrich: `enricher_dsl.py` (`_read_row_value`, `_read_value_path`, ops apply)

### Использование дальше
Эти helpers **обязательны** для DSL‑стадий (mapping/normalize/enrich/validate/match/resolve).  
Для стадий без DSL‑ops — **опционально** (но желательно ради единого поведения диагностик).

## Общие helpers/обвязки DSL (минимальный рефактор)
Цель: убрать дублирование между Mapper/Normalize/Enrich, **без изменения логики**.

### Общие функции/классы (кандидаты на вынос)
1) **apply_ops(engine, value, ops) -> (value, issues)**  
   Используется во всех DSL‑стадиях при применении операций.
2) **read_value(record_values, row_values, path)**  
   Унифицированное чтение `record.*` / `row.*` / plain‑fields.
3) **read_value_path(obj, path)**  
   Доступ к вложенным полям (для lookup/value_path).
4) **to_mapping(value)**  
   Приведение dataclass/obj к mapping для нормализации.
5) **append_dsl_issue(...) / append_dsl_issues(...)**  
   Преобразование `DslIssue` → `DiagnosticItem` с учётом `on_error`.

### Где живут сейчас (для ориентира)
- Mapper: `mapper_core.py` (`_resolve_rule_value`, `_read_value`, `_append_issue`)
- Normalize: `normalizer_core.py` (`_append_issue`, `_to_mapping`)
- Enrich: `enricher_dsl.py` (`_read_row_value`, `_read_value_path`, ops apply)

### Использование дальше
Эти helpers **обязательны** для DSL‑стадий (mapping/normalize/enrich/validate/match/resolve).  

### Что меняется архитектурно
- Выравниваем naming: `StageRules / StageDsl / StageEngine / StageCore`
- DSL‑слой становится унифицированным и предсказуемым для всех стадий
- Ядра остаются чистыми; DSL — тонкий адаптер

## Область покрытия (80/20)
Типовые правила, которые должны быть доступны декларативно:

### Normalize
- trim, lowercase/uppercase
- regex_replace
- parse_int / parse_bool / parse_date
- default_if_empty

### Enrich
- generate_if_missing (uuid, short id, шаблон)
- lookup (cache, справочники)
- template (строить значение из полей)
- allow_if (условия запуска в виде DSL‑операции)
- lookup templates (preset‑шаблоны для однотипных lookup‑правил)

### Validate
- required
- enum / regex
- range (min/max)
- exists_in (cache lookup)

## Custom rules
Если DSL не покрывает кейс, правило описывается так:
```yaml
enrich:
  rules:
    some_custom_rule:
      type: custom
      handler: my_custom_handler
```
И реализуется в коде, регистрируется в реестре handlers.

## Плюсы
- Быстрое добавление новых датасетов.
- Меньше ручного кода.
- Единый формат описания правил.

## Минусы
- Требует поддержки DSL и движка.
- Сложнее отладка “магии”.
- Полное покрытие всех кейсов невозможно без custom правил.

## Предложенный план внедрения
1) Прототип DSL только для **validation** (самый понятный слой).
2) Добавить normalize‑DSL (типовые преобразования).
3) Добавить enrich‑DSL (генерация/lookup).
4) Оставить возможность custom rules на каждом этапе.

## Пример (сокращённо)
```yaml
dataset: employees
normalize:
  rules:
    email:
      source: email
      type: string
      transform: trim
    organization_id:
      source: organization_id
      type: int
      parse: strict
validate:
  rules:
    - field: email
      required: true
      format: email
    - field: organization_id
      required: true
      type: int
      exists_in: cache.orgs
```

## Следующие шаги
- Зафиксировать минимальный набор правил.
- Оценить трудозатраты на движок.
- Сделать прототип на одном датасете.

## Нерешённые вопросы/проблемы (зафиксировать)
1) **Sink‑модель используется не везде.**  
   Сейчас sink‑schema подключена к map/normalize, но ещё не используется в apply/plan/cache.  
   Это не блокирует DSL map/normalize/enrich, но нужно для полной декларативности.

2) **Нет декларативного SourceSpec.**  
   Нужно описывать источник (db/api/file), формат и все параметры чтения, а не только набор полей.  
   *Эту проблему разбираем отдельно/подробно позже.*

3) **Остаётся кодовая логика, не покрытая ops.**  
   Примеры: сборка match_key, части lookup/merge‑политик, структурная логика маппинга.  
   Нужно решить, что уходит в ops, а что остаётся в StageCore.

4) **Lookup‑deps ещё не полностью декларативны.**  
   Нужна схема “providers registry” + YAML‑описание lookup‑провайдеров, чтобы deps стал универсальным адаптером.

5) **Нет единого post‑validation после enrich.**  
   Нормализация валидирует типы по sink‑схеме, enrich — нет.  
   Нужно решить: валидировать только изменённые поля или весь row при необходимости.

6) **Остатки dataset‑кода.**  
   В `datasets/*/transform` остаются transitional‑модули, которые надо убрать после полной миграции на YAML.

### Детализация реализации по п.3 (граница `ops` vs `StageCore`)
Цель: убрать дублирование и разные механики при сохранении простой архитектуры.

#### Статус (реализация)
- DSL-путь для map/normalize/enrich оставлен единственным runtime-путём.
- Legacy-файлы старого map-пути удалены:
  - `connector/datasets/employees/extract/source_mapper.py`
  - `connector/datasets/employees/extract/mapping_spec.py`
- Тесты, которые ранее брали `SOURCE_COLUMNS` из legacy-модуля, переведены на `load_mapping_spec_for_dataset(...).source_columns`.
- `EmployeesValidationSpec` больше не зависит от legacy `EmployeesMappingSpec` и читает required-поля из `SinkSpec` (только `required` + `nullable=false`).

Что осталось за пределами п.3:
- декларативный `lookup providers` слой (п.4),
- зачистка transitional dataset-кода (п.6).

#### 1. Контракт границы
- В `ops` остаются только pure value-трансформации:
  - вход: значение (или небольшой `dict` значений),
  - выход: значение (и диагностический issue),
  - без IO, без кэша/vault, без batch-state.
- В `StageCore` остаётся orchestration:
  - порядок операций, merge/strictness-политики,
  - работа с зависимостями (`cache`, `providers`, `secret_store`),
  - cross-row/cross-system логика (`match/resolve/pending`).

#### 2. Что переносим в `ops`
- Универсальные преобразования полей:
  - типизация (`to_int`, `to_bool`, `to_float`),
  - строки (`trim`, `lower`, `upper`, `split`, `split_name`),
  - простые композиции (`coalesce`, `concat`, `const`, `copy`),
  - pattern extraction / key-value parse.
- Чистые derive-операции без внешних зависимостей:
  - например, build ключа из уже подготовленных полей, если нет IO и side effects.

#### 3. Что не переносим в `ops`
- Любой lookup в кэш/справочники/внешние репозитории.
- Политики выбора кандидатов и разрешение конфликтов.
- Логику pending-links и batch-index.
- Запись секретов в vault и все операции с хранилищами.
- Финальные решения `create/update/skip/conflict` для planning-части.

#### 4. Пошаговая миграция
1) Для каждой стадии (`mapping`, `normalize`, `enrich`) построить список повторяющихся pure-фрагментов.
2) Вынести только эти фрагменты в `connector/domain/transform/dsl/ops.py`.
3) Оставить orchestration в `mapper_core`/`normalizer_core`/`enricher_core`.
4) Удалить legacy-путь, который дублирует DSL-путь (после тестов).
5) Проверить, что diagnostics и отчёты не меняют семантику.

#### 5. Критерии завершения по п.3
- Нет дублирования pure-трансформаций между `mapping/normalize/enrich`.
- Нет IO-логики внутри `ops`.
- `StageCore` не содержит ручных реализаций уже существующих `ops`.
- Все стадии используют единый путь `StageDSL -> StageCore`, без параллельной legacy-ветки.
- Тесты стадий и e2e-тесты пайплайна проходят без регрессий.

### Детализация реализации по п.4 (declarative providers для lookup)
Цель: убрать датасет-специфичные `deps.*` методы из runtime и перевести lookup/exists на единый декларативный провайдерный слой.

#### 1. Проблема в текущем виде
- `EnricherDSL` вызывает lookup/exists через `getattr(deps, rule.lookup)` и `getattr(deps, rule.exists)`.
- `datasets/*/transform/enrich_deps.py` вынужденно содержит бизнес-методы вида `find_*`.
- DSL остаётся частично декларативным: имя метода в YAML жёстко привязывает runtime к структуре `deps`.

#### 2. Целевая модель
- `deps` = только ресурсы (`cache_repo`, `dictionaries`, `secret_store`, и т.п.), без бизнес-методов lookup.
- DSL указывает не метод `deps`, а `provider` + аргументы.
- Поиск/проверка существования идут через `ProviderGateway`.

#### 3. Архитектурные места (без overengineering)
- `connector/domain/ports/transform/providers.py`
  - контракты: `ProviderRequest`, `ProviderAdapter` (Protocol).
- `connector/domain/transform/providers/`
  - `registry.py`: `ProviderGateway`.
  - `cache_provider.py`: `cache.by_field`, `cache.exists_by_field`.
  - `dictionary_provider.py`: `dictionary.by_key`.
- `connector/domain/transform/enrich/enricher_dsl.py`
  - строит `ProviderRequest` из YAML и вызывает registry.

#### 4. Формат в YAML (минимум)
- Для lookup:
  - `provider.name`
  - `provider.args`
  - `source/sources`, `ops`, `value_path`, `target`
- Для exists:
  - `exists.provider.name`
  - `exists.provider.args`

Пример:
```yaml
lookup:
  - name: manager_id
    target: manager_id
    source: manager_id
    provider:
      name: cache.by_field
      args: {dataset: employees, field: match_key, include_deleted: true}
    value_path: _ouid

generate:
  - name: target_id
    target: target_id
    source: target_id
    ops: [{op: trim}, {op: default_uuid}]
    exists:
      provider:
        name: cache.exists_by_field
        args: {dataset: employees, field: _id, include_deleted: true}
```

#### 5. Пошаговая миграция
1) Ввести provider-контракты и `ProviderGateway`.
2) Реализовать базовые адаптеры: `cache.by_field`, `cache.exists_by_field`, `dictionary.by_key`.
3) Расширить DSL-модели (`ProviderRef`/`ExistsRef`) и валидатор загрузки.
4) Перевести `EnricherDSL` на provider-вызовы через registry.
5) Мигрировать `datasets/*.enrich.yaml` на `provider`-форму.
6) Удалить fallback `getattr(deps, ...)`.
7) Упростить `datasets/*/transform/enrich_deps.py` до resource-container.

#### 6. Критерии завершения по п.4
- В YAML нет ссылок на методы `deps`.
- В `enrich_deps` нет бизнес-методов lookup/exists.
- Lookup/exists выполняются только через `ProviderGateway`.
- Те же провайдеры доступны для других стадий (`match/resolve`) без копирования логики.
- Поведение отчётов и диагностики не изменилось (только источник кандидатов).

#### Статус (реализация)
- Добавлены контракты и runtime-реестр провайдеров:
  - `connector/domain/transform/providers/deps.py`
  - `connector/domain/transform/providers/registry.py`
- `EnricherDsl` переведён на `ProviderGateway` (lookup/exists через registry, без `getattr(deps, ...)`).
- `datasets/employees.enrich.yaml` мигрирован на `exists.provider`.
- `EmployeesEnrichDependencies` заменён на общий `TransformProviderDeps` в доменном слое.
- Тесты enrich/validation/stage обновлены под provider-подход.

#### Статус-апдейт (p.1 / p.2 / p.4)
- `p.1` реализован:
  - введён общий контейнер зависимостей `TransformProviderDeps`;
  - `EmployeesSpec.build_enrich_deps` возвращает `TransformProviderDeps`;
  - dataset-специфичный `enrich_deps` модуль удалён.
- `p.2` реализован:
  - alias `EmployeesEnricherSpec` удалён;
  - `EnricherEngine` получает spec через `load_enrich_spec_for_dataset("employees")`.
- `p.4` реализован:
  - сборка transform-стадий в `connector/datasets/employees/spec.py` разложена на приватные builder-методы;
  - выделен единый `_build_dsl_registry()` для устранения дублирования wiring-кода.
- `p.3` сознательно отложен:
  - `NormalizedEmployeesRow` оставлен как transitional тип;
  - удаление запланировано после перехода потребителей на schema/dict-модель end-to-end.

### Детализация реализации по п.5 (decommission `ValidateStage`)
Цель: убрать `ValidateStage` как отдельный слой/этап и распределить проверки по стадиям transform.

#### 1. Новая целевая схема конвейера
- Было:
  - `extract -> map -> normalize -> enrich -> validate -> match -> resolve -> plan`
- Станет:
  - `extract -> map -> normalize -> enrich -> match -> resolve -> plan`

#### 2. Принцип распределения ответственности
- `Map`: формирование sink-структуры + required по структуре.
- `Normalize`: приведение типов/форматов + sink type/nullability checks.
- `Enrich`: проверки только изменяемых/генерируемых полей и lookup-результатов.
- `Match/Resolve`: cross-row/cross-system валидации (ambiguity, pending, conflicts).

`ValidateStage` не держит уникальной обязательной логики и удаляется, чтобы не дублировать проверки.

#### 3. Что удаляем
1) `ValidateStage` из `StagePipeline` и связанного wiring в bootstrap/use-cases.
2) Отдельный `ValidateUseCase` и CLI-команду `validate`.
3) Спецификацию/адаптеры, которые использовались только этим этапом и не имеют самостоятельной ценности.

#### 4. Что переносим
1) Правила `required/type/format`:
   - в `mapping`/`normalize` DSL и core.
2) Секрет-aware проверки:
   - в `enrich` (`meta.secret_fields`, очистка row после vault).
3) Cross-row проверки:
   - в `match/resolve` (дубликаты, конфликты, pending-links).

#### 5. Пошаговая миграция
1) Перенести обязательные проверки из validation-специки в `mapping/normalize/enrich` (без изменения кодов ошибок).
2) Обновить pipeline сборку:
   - исключить `ValidateStage`,
   - обновить `build_pipeline_context` и use-cases (`match/resolve/import-plan`).
3) Обновить CLI:
   - удалить/переопределить `validate` команду.
4) Удалить неиспользуемые validation-модули после стабилизации тестов.
5) Обновить UML/доки и e2e тесты под новый маршрут данных.

#### 6. Секрет-совместимость
- После enrich секретные поля могут отсутствовать в row.
- Это не считается ошибкой, если поле указано в `meta.secret_fields` и секрет уже отправлен в vault.

#### 7. Критерии завершения по п.5
- В конвейере нет отдельной `validate` стадии.
- Все проверки, ранее блокировавшие поток на validate, корректно срабатывают на соответствующих стадиях.
- `match/resolve/plan` получают только валидный для своих контрактов поток данных.
- Нет регрессий в отчетности и кодах диагностики.

#### Статус (реализация)
- `ValidateStage` удалён из `StagePipeline` и exports стадий.
- `build_pipeline_context` и `import_plan_service` переведены на цепочку `map -> normalize -> enrich`.
- `match`/`resolve` команды и `MatchUseCase` принимают `enriched_source` вместо `validated_source`.
- `DeduplicationTransform` больше не требует `ValidationRow`; используется нейтральный `MatchContext`, собранный из `TransformResult`.
- `validate` CLI и `ValidateUseCase` удалены.

## Lookup templates (кратко)
В enrich можно добавить укороченную форму:
```yaml
enrich:
  lookup_templates:
    manager_by_full_name:
      provider:
        name: cache.by_field
        args: {dataset: employees, field: full_name}
      value_path: _id
      ops: [trim, split_name]
  lookup:
    - name: manager_id
      target: manager_id
      source: manager_full_name
      template: manager_by_full_name
```
При загрузке YAML шаблон разворачивается в полноценное правило.
