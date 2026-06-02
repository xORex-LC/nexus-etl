# Dependency Tree Implementation Plan

Статус: draft  
Последнее обновление: 2026-05-27

## Цель документа

Этот документ фиксирует ход обсуждений, выводы и проектные решения по внедрению в ETL-проект отдельной подсистемы `dependency_tree`.

Документ является рабочим артефактом:
- дополняется по мере обсуждения;
- фиксирует архитектурные решения до начала полной реализации;
- служит опорой для поэтапного внедрения в код.

## Контекст проблемы

В проекте есть сущности с иерархической или зависимой структурой, например `departments`, где:
- `id` — идентификатор текущего узла;
- `parent_id` — ссылка на родительский узел.

Пример цепочки:

`101 -> 56 -> 12 -> 1`

Такие зависимости важны не только для построения структуры, но и для корректного обогащения, матчинга и разрешения конфликтов.

## Зачем нужна подсистема dependency_tree

### 1. Определение порядка расчета

Нельзя корректно вычислять агрегаты или производные атрибуты родительского узла, пока не рассчитаны дочерние узлы.  
Подсистема должна уметь строить строгий порядок обхода и вычисления.

### 2. Выявление циклов

В реальных данных возможны циклические зависимости:
- A зависит от B
- B зависит от A

Подсистема должна обнаруживать такие случаи сразу при построении графа и выдавать диагностируемую ошибку.

### 3. Использование топологии в ETL

Подсистема нужна не только для расчётов, но и для использования иерархии как дополнительного сигнала в обработке данных:
- `enrich`
- `match`
- `resolve`

Пример:

Если есть несколько `departments` с одинаковым названием, матчинга по `name` недостаточно.  
Тогда сравнение можно делать по структурной сигнатуре:
- цепочка предков;
- глубина;
- корневой узел;
- путь до корня;
- комбинированный fingerprint topology.

## Ключевое архитектурное решение

Подсистема `dependency_tree` не должна быть привязана к конкретной стадии ETL.

Она должна быть:
- изолированной;
- независимой от `enrich`, `match`, `resolve`;
- доступной для стадий через DI/runtime context;
- пригодной для повторного использования в других частях проекта.

Иными словами:

Не стадия владеет деревом зависимостей.  
Дерево зависимостей является отдельным domain runtime artifact, который стадии могут использовать.

## Принципы проектирования

### Изоляция

Подсистема должна жить отдельно от stage logic:
- без привязки к конкретной pipeline stage;
- без прямой зависимости от `delivery` и `infra`;
- с чистым domain API.

### Immutable runtime snapshot

После построения дерево должно представляться как неизменяемый snapshot:
- forest/tree;
- lookup-индексы;
- топологический порядок;
- предрасчитанные структурные представления.

### Stage access by capability

Стадии не строят дерево сами.  
Они получают доступ к уже построенному snapshot через:
- `StageExecutionContext`
- `ProviderGateway`
- или отдельный topology provider

### Reusable API

Подсистема должна позволять использовать её:
- для иерархий (`parent_id`);
- для DAG-подобных зависимостей (`depends_on[]`);
- для расчётов порядка;
- для topology-aware matching/disambiguation.

## Предварительная область ответственности подсистемы

Подсистема `dependency_tree` должна уметь:

- строить directed graph / forest из flat records;
- проверять корректность графа;
- обнаруживать:
  - duplicate node ids;
  - missing parent;
  - self-loop;
  - cycle;
- вычислять:
  - `topological_order`;
  - `path_to_root`;
  - `ancestors`;
  - `descendants`;
  - `depth`;
  - `root_id`;
  - `structural_signature`;
  - `topology_fingerprint`;
- предоставлять query API для ETL-стадий.

## Что подсистема не должна делать

На текущем этапе `dependency_tree` не должна:

- отправлять запросы во внешние системы;
- сама решать бизнес-правила `match` или `resolve`;
- быть зашита в DSL operations как просто ещё одна op-цепочка;
- мутироваться по мере прохождения pipeline;
- зависеть от конкретного dataset, например только от `organizations`.

## Предварительное размещение в кодовой базе

Предлагаемое место:

`connector/domain/dependency_tree/`

Возможная структура:

```text
connector/domain/dependency_tree/
  __init__.py
  models.py
  builder.py
  validator.py
  index.py
  service.py
  errors.py
```

Если потребуется порт для внешнего источника topology:

```text
connector/domain/ports/topology/
```

Если потребуется infra-адаптер:

```text
connector/infra/topology/
```

## Предварительные доменные объекты

### Node model

Минимальный узел:

- `node_id`
- `parent_id`
- `payload`

Возможные поля:

- `node_id: str`
- `parent_id: str | None`
- `dataset: str | None`
- `attributes: Mapping[str, Any]`

### Snapshot model

`TopologySnapshot` или `DependencyTreeSnapshot`:

- `nodes_by_id`
- `children_by_id`
- `parent_by_id`
- `roots`
- `topological_order`
- `depth_by_id`
- `path_cache`
- `fingerprints`

### Diagnostics

Нужны явные типизированные ошибки:

- duplicate node id
- parent not found
- self loop
- cycle detected

Они должны интегрироваться с существующим diagnostic layer проекта.

## Предварительное runtime API

Подсистема должна давать вызывающей стороне методы уровня:

- `has_node(node_id)`
- `get_node(node_id)`
- `parent(node_id)`
- `children(node_id)`
- `ancestors(node_id)`
- `descendants(node_id)`
- `path_to_root(node_id)`
- `root_id(node_id)`
- `depth(node_id)`
- `is_ancestor(a, b)`
- `same_branch(a, b)`
- `structural_signature(node_id)`
- `topology_fingerprint(node_id)`
- `topological_order()`

## Как это будет использоваться стадиями

### Enrich

Подсистема может использоваться для вычисления дополнительных topology-derived полей:

- `org_root_id`
- `org_depth`
- `org_path_ids`
- `org_path_names`
- `org_parent_id`
- `org_topology_fingerprint`

Эти поля можно использовать в downstream логике без дублирования tree traversal.

### Match

Подсистема может использоваться для disambiguation, когда одного `name` недостаточно.

Пример стратегии:

1. Найти кандидатов по слабому признаку, например `normalized_name`
2. Сравнить topology:
   - совпадает ли root;
   - совпадает ли parent;
   - насколько близки ancestry chains;
   - совпадает ли topology signature.

### Resolve

Подсистема может использоваться:

- для выбора между несколькими кандидатами связи;
- для topology-aware link resolution;
- для дополнительной валидации ссылок между узлами.

## Предварительное решение по DSL

На текущем этапе не планируется встраивать topology logic прямо в существующие stage DSL spec-файлы.

Предпочтительное направление:

отдельная topology/dependency_tree спецификация.

Возможные варианты:

- `datasets/<dataset>/<dataset>.topology.yaml`
- отдельная секция в registry

Предварительное содержимое topology spec:

- `dataset`
- `node_id_field`
- `parent_id_field`
- `depends_on_fields`
- `natural_key_fields`
- `derived_fields`
- `matching_signatures`

Это позволит сохранить изоляцию:
- topology subsystem имеет свой контракт;
- стадии только ссылаются на него.

## Предварительный путь внедрения

### Phase 1. Domain foundation

Сделать изолированный доменный модуль:

- builder
- validator
- immutable snapshot
- query API

На этом этапе без stage integration.

### Phase 2. Single source support

Поддержать первый практический источник:

- hierarchy `organizations` / `departments`
- данные из cache snapshot или другого runtime source

### Phase 3. Runtime wiring

Подключить подсистему через DI:

- построение snapshot один раз на pipeline run;
- передача snapshot в stage context.

### Phase 4. Enrich integration

Добавить вычисление topology-derived attributes.

### Phase 5. Match integration

Добавить topology-aware candidate disambiguation.

### Phase 6. Resolve integration

Добавить topology-aware link resolution / validation.

### Phase 7. DSL formalization

Добавить отдельную declarative topology spec.

## Предварительные открытые вопросы

1. Что является каноническим источником topology:
   - cache snapshot
   - source dataset
   - dictionary
   - отдельный topology dataset

2. Нужен ли только tree (`parent_id`) или нужно сразу проектировать под DAG (`depends_on[]`)?

3. Где строить snapshot:
   - до запуска pipeline;
   - лениво при первом запросе;
   - в отдельном orchestration step.

4. Нужно ли сохранять topology-derived поля обратно в cache/runtime artifacts?

5. Как описывать topology-aware matching declaratively:
   - отдельной spec;
   - расширением `match.yaml`;
   - отдельной strategy-конфигурацией.

6. Нужно ли поддерживать несколько topology snapshots в рамках одного pipeline run?

## Аналитика: runtime source topology

### Важное различие

В обсуждении зафиксировано важное различие между двумя понятиями:

1. **Подсистема `dependency_tree` как domain service**
2. **Runtime provider, который поставляет данные для построения graph/snapshot**

Сам `dependency_tree` не должен знать, что именно является источником данных:

- source CSV
- cache snapshot
- dictionary
- отдельный topology dataset

Подсистема должна быть source-agnostic и принимать уже нормализованный набор узлов/связей.

То есть вопрос runtime source относится не к domain-механизму дерева как таковому, а к orchestration/runtime wiring:

**кто и когда передаст в `dependency_tree` данные для построения snapshot.**

### Предварительный вывод

`dependency_tree` должен быть изолирован от конкретного источника.

Следствие:

- domain builder/validator/query API работает поверх абстрактного набора `node_id / parent_id / payload`;
- источник данных выносится в отдельный runtime provider / adapter;
- стадии используют уже готовый `TopologySnapshot`, а не сами читают исходные данные для построения дерева.

## Предварительная runtime-модель источников

На текущем этапе обсуждения выделяются два практически полезных topology source:

### 1. Target-side topology

Источник:

- cache snapshot / cache mirror target-системы

Пример:

- иерархия `organizations/departments`, уже отражённая в локальном cache.

Плюсы:

- хорошо согласуется с `match` и `resolve`;
- отражает target reality;
- уже существует отдельный runtime access path через cache ports;
- не требует вмешательства в streaming Extract pipeline.

### 2. Source-side topology

Источник:

- source dataset / входной CSV / отдельный source projection

Пример:

- иерархия подразделений, пришедшая вместе с входными данными.

Плюсы:

- полезно для enrich и topology-aware disambiguation до target-side matching;
- позволяет сравнивать source topology и target topology.

Минусы:

- текущий pipeline читает source построчно;
- для полноценного topology snapshot нужен как минимум отдельный pre-pass по данным;
- это сложнее с точки зрения orchestration и memory model.

## Вопрос: нужно ли фиксировать один "источник истины"

Предварительный вывод:

**на уровне domain subsystem — нет, не нужно.**

Подсистема не должна иметь жёсткую зависимость от одного "источника истины".

Правильнее мыслить так:

- `dependency_tree` умеет строить snapshot из любого набора узлов;
- runtime может создавать один или несколько snapshot:
  - `target topology snapshot`
  - `source topology snapshot`
- stage logic использует нужный snapshot в зависимости от задачи.

Таким образом:

- **domain role одна**
- **runtime providers могут быть разными**

## Как это соотносится с текущим pipeline

Текущий planning pipeline потоковый:

`Extract -> Map -> Normalize -> Enrich -> Match -> ResolveContext -> Resolve`

При этом:

- `Extract` читает source построчно;
- `PipelineOrchestrator` ленивый;
- full buffering сейчас уже есть только в `ResolveContextStage`.

Если topology нужна стадиям во время обработки record-by-record, snapshot должен быть готов **до того, как первый record дойдёт до этих стадий**.

Иначе stage будет работать с неполной topology, а это ломает корректность:

- ancestry chain может быть неполной;
- parent ещё не встречен;
- disambiguation даст нестабильный результат;
- cycle detection не будет завершена.

## Вывод по моменту построения

### Если topology snapshot нужен в `enrich`, `match` или `resolve`

То его нельзя строить "по ходу" основного stream в том виде, как будто он постепенно дозаполняется и уже пригоден для query.

Для корректного использования нужен:

- либо **полностью готовый snapshot до старта stage chain**;
- либо отдельный explicitly documented pre-pass, который завершится до начала потребления основного pipeline stream.

### Следствие

Topology build в runtime следует рассматривать как **отдельный orchestration step**, а не как часть обычного record-by-record stage flow.

## Что это означает для source-side topology

Если topology строится по source dataset, то для Phase 1 нужно принять один из двух подходов:

### Вариант A. Отдельный pre-pass по source

До запуска pipeline:

- открыть source ещё раз;
- прочитать только topology-relevant поля;
- построить snapshot;
- затем запустить основной pipeline отдельно.

Плюсы:

- корректный полный snapshot;
- stage logic остаётся простой;
- topology subsystem не смешивается с Extract/Map pipeline напрямую.

Минусы:

- двойное чтение source;
- отдельный orchestration path;
- дополнительная стоимость на старте run.

### Вариант B. Отдельный topology dataset / source

Topology поступает не из того же потока, что и основной CSV, а из отдельного источника:

- отдельный CSV
- dictionary-like source
- runtime cache

Плюсы:

- меньше вмешательства в основной stream;
- проще lifecycle.

Минусы:

- дополнительный входной артефакт;
- усложнение конфигурации.

### Предварительный вывод

Если нужен source-side topology snapshot, то наиболее чистый путь на раннем этапе:

**делать отдельный pre-pass, а не пытаться встраивать построение дерева прямо в поток `Extract -> Map -> Normalize`.**

## Что это означает для target-side topology

Если topology строится по cache mirror target-системы:

- snapshot можно строить до запуска stage chain;
- source streaming pipeline не ломается;
- runtime orchestration проще;
- topology готова к `match` и `resolve` до первого record.

Это делает target/cache topology лучшим кандидатом для Phase 1.

## Предварительная рекомендация

### Recommendation A

Подсистема `dependency_tree` остаётся source-agnostic.

Она не знает, откуда пришли nodes/edges.

### Recommendation B

Runtime wiring не должно оперировать одним жёстко зашитым "источником истины".

Для Phase 1 предпочтительнее явная двухсторонняя модель:

- `target topology`
- `source topology`

### Recommendation C

Для Phase 1 `cache-backed target topology` остаётся обязательной частью решения, но её **недостаточно** для topology-aware matching, если source не содержит target ids.

Причины:

- source может не знать `organization_id`;
- source hierarchy может приходить как строковые уровни пути;
- topology-aware matching требует сравнить source-side structure и target-side structure.

### Recommendation D

Source-side topology не следует откладывать за пределы Phase 1, если целевой первый use case:

- сопоставление source departments/organizations против target organizations по topology.

Но её следует реализовывать как отдельную capability:

- через pre-pass;
- либо через отдельный topology source;
- либо через source hierarchy projection с synthetic node ids;
- но не как скрытое накопление графа внутри обычного streaming stage.

### Recommendation E

Для обсуждаемого use case разумно принять **асимметричную Phase 1 модель**:

- target-side: полноценный `TopologySnapshot` из cache;
- source-side: минимально достаточное topology representation из source hierarchy path.

Это позволит:

- не требовать target ids в source;
- получить сравнимую topology signature для обеих сторон;
- не переусложнять первую реализацию полным source runtime graph, если он не нужен целиком.

## Предварительные последствия для архитектуры

Вероятно потребуются:

### Domain

- `dependency_tree` builder/query API
- source-agnostic node contract

### Ports

- topology provider port

### Infra

- cache-backed topology provider
- позже source-backed topology provider

### Delivery / runtime orchestration

- explicit snapshot build step before stage chain, если topology требуется pipeline run

## Предварительный открытый технический вопрос

Нужно отдельно решить:

- строим ли topology snapshots всегда в начале run;
- или только если dataset/stage config явно требует topology capability.

Предварительное предпочтение:

**строить только по требованию**, чтобы не добавлять лишнюю стоимость для сценариев, которым topology не нужна.

## Зафиксированные на текущий момент решения

### Decision 1

`dependency_tree` должен быть отдельной подсистемой, а не логикой конкретной стадии.

### Decision 2

Стадии должны использовать подсистему через runtime capability / DI, а не строить graph самостоятельно.

### Decision 3

Подсистема должна работать как immutable runtime snapshot.

### Decision 4

Topology logic не должна быть сведена к набору ad-hoc DSL ops; это отдельная domain capability.

### Decision 5

DSL для topology лучше делать отдельной спецификацией, а не сразу встраивать в stage-specific YAML.

### Decision 6

Первая реализация подсистемы строится по модели `tree-first`, а не `DAG-first`.

Это означает:

- один `node_id`;
- не более одного `parent_id` у узла;
- допускается forest, а не только одно дерево;
- циклы запрещены;
- API Phase 1 ориентирован на иерархические запросы:
  - `ancestors`
  - `descendants`
  - `path_to_root`
  - `root_id`
  - `depth`

### Decision 7

`tree-first` не должен блокировать дальнейший апгрейд подсистемы до общего DAG.

Следствие для проектирования:

- internal models и naming не должны жёстко предполагать, что расширение невозможно;
- validator и builder на Phase 1 могут быть tree-specific;
- public role подсистемы остаётся общей: работа с зависимостями и topology, а не только с деревьями.

### Decision 8

Подсистема `dependency_tree` остаётся **source-agnostic**.

Это означает:

- domain builder/query API не знает, откуда пришли nodes/edges;
- `dependency_tree` не зависит напрямую ни от cache, ни от source CSV, ни от dictionaries;
- ответственность за выбор runtime-источника topology лежит на orchestration/DI-слое.

### Decision 9

Runtime должен сохранять **внутреннюю расширяемость до нескольких topology snapshots**,
но Phase 1 stage-facing contract может быть уже и явнее.

Внутренний runtime/orchestration уровень должен оставаться способен нести больше
одного topology snapshot.

Для Phase 1 базовая двухсторонняя модель такова:

- `target topology`
- `source topology`

Это позволяет:

- не смешивать target reality и source-side hierarchy;
- явно различать обязательные и optional topology inputs.

Дополнительное рабочее уточнение:

- узкий `TopologyProviderPort` с `require_source/require_target/get_source/get_target`
  рассматривается как **осознанный Phase 1 trade-off**;
- он делает stage API прямее и проще для текущего use case;
- но он действительно жертвует OCP на уровне stage-facing port по сравнению с
  fully extensible named-snapshot contract;
- если появится третья обязательная topology сторона, stage-facing port придётся
  расширять или возвращаться к более общему lookup-based contract.

### Decision 10

Если topology должна использоваться стадиями во время обычного streaming pipeline, то соответствующий snapshot должен быть **полностью построен до того, как первый record дойдёт до этих стадий**.

Следствие:

- topology build не встраивается как скрытая побочная логика внутрь обычного `Extract -> Map -> Normalize -> ...` потока;
- source-backed topology для Phase 1 допускается только через отдельный pre-pass или отдельный topology source;
- попытка "постепенно достраивать" topology по ходу stream не считается корректной моделью для query-driven stage logic.

### Decision 11

Для **Phase 1** недостаточно только `cache-backed target topology`.

Чтобы решить основной practical use case topology-aware matching, Phase 1 должен поддержать две стороны сопоставления:

- `target topology` — snapshot по cache mirror target-системы;
- `source topology` или эквивалентное source-side topology representation — на основе source hierarchy.

Причина:

- в source hierarchy часто приходит как набор строковых уровней пути;
- в target те же сущности представлены `organization_id`;
- если построить только target topology, то source-side structural signature сравнивать будет не с чем.

Следствие:

- Phase 1 должен поддержать source-side topology signal;
- source-side representation не обязано использовать target ids;
- допустима асимметричная модель: полный target snapshot + более лёгкое source representation.

## Аналитика: почему target-only Phase 1 недостаточен

Если source содержит hierarchy в виде уровневых строковых колонок, а target использует `organization_id`, то topology-aware matching должен ответить на вопрос:

**какому target node соответствует source path.**

Без source-side topology representation остаются только слабые признаки:

- leaf name;
- отдельные строковые поля без контекста предков.

Этого недостаточно, если:

- названия подразделений повторяются;
- одинаковые leaf names живут в разных ветках;
- source не содержит ids target-системы.

Следовательно, для реального matching нужны две вещи:

1. target topology index
2. source topology signal

## Предварительная модель source-side topology для Phase 1

Если source не содержит явных `id` / `parent_id`, а хранит hierarchy как path columns, это не блокирует реализацию.

Возможен следующий рабочий контракт:

- source hierarchy path собирается из уровней после normalize;
- пустые уровни отбрасываются;
- каждый уникальный path превращается в synthetic tree chain;
- synthetic node id генерируется детерминированно из normalized path;
- parent relation выводится из path prefix.

Пример:

- `Company / Division / Team`
- synthetic leaf id: `company/division/team`
- synthetic parent id: `company/division`

Таким образом:

- source topology можно построить даже без явных source ids;
- topology snapshot остаётся tree-first;
- matching выполняется по path signature source against target, а не по прямому id equality.

## Аналитика: можно ли собирать source topology после Map построчно

В обсуждении рассмотрен отдельный вариант:

- `Extract` читает source построчно;
- `Map` приводит строки к каноническим field names;
- после `Map` отдельный standalone collector/service получает mapped rows и собирает source graph постепенно;
- на промежуточных шагах graph может существовать как набор незавершённых связей / pending edges / orphan candidates.

### Почему идея сильная

У этого подхода есть реальные преимущества:

- graph builder не зависит от сырого CSV layout и работает уже с каноническими mapped field names;
- topology extraction не вшивается в сам `MapStage`, а остаётся отдельной capability;
- можно накапливать diagnostics:
  - missing parent candidate;
  - duplicate synthetic node;
  - malformed hierarchy path;
  - self-loop;
- можно строить source topology без отдельного ручного parser-а поверх сырых колонок.

### Что в этой идее архитектурно корректно

Если формулировать аккуратно, то это не "граф строится внутри stage", а:

- существует отдельный `source topology collector`;
- orchestration подаёт ему mapped rows;
- collector в конце materialize-ит source topology snapshot.

То есть подсистема дерева всё ещё остаётся изолированной.

`MapStage` в этой модели лишь даёт удобную canonicalized форму данных, после которой topology extraction проще и надёжнее.

### Главная проблема

Проблема не в самом incremental build, а в моменте готовности snapshot.

Пока stream не завершён:

- часть родителей может ещё не встретиться;
- часть path chains может быть неполной;
- cycle detection не завершена;
- structural signatures не гарантированно финальны.

Следовательно:

- **collector-after-map хорошо подходит для накопления topology data**
- но **не делает graph готовым для query-driven stage use в том же streaming pass**

если downstream стадии хотят topology уже во время обработки первых записей.

### Что это означает practically

Если `enrich` или `match` должны использовать topology на этой же прогонке source rows, то одного "построчного накопления после Map" недостаточно.

Нужен один из вариантов:

1. Сначала прогнать topology pre-pass до конца и построить source topology snapshot
2. Потом открыть основной pipeline второй раз и использовать уже готовый snapshot

или:

1. После `Map` начать накапливать topology
2. Одновременно буферизовать downstream rows
3. Дождаться завершения topology build
4. Только потом выпустить buffered rows дальше

Второй вариант по сути превращается в скрытый full-buffering barrier и хуже явного pre-pass.

### Вывод по идее "после Map"

Идея полезна, если трактовать её не как "строим topology прямо во время обычного pipeline run", а как:

- **явный source topology bootstrap pass**
- построенный на выходе `Map` или `Map + Normalize(topology fields only)`

В такой форме подход хорош, потому что:

- использует канонические field names;
- не требует парсить сырые source columns на уровне topology subsystem;
- сохраняет изоляцию `dependency_tree`;
- делает source topology детерминированной и диагностируемой.

### Предпочтительная интерпретация для Phase 1

Для Phase 1 предпочтительнее следующая модель:

- не строить source topology из сырых `Extract` rows;
- строить её из **mapped** или **topology-normalized** rows;
- оформлять это как **отдельный bootstrap pass**, а не как побочный эффект основного stage chain.

Возможный flow:

1. `Extract`
2. `Map`
3. optional lightweight `Normalize` только для topology fields
4. `SourceTopologyCollector`
5. build source topology snapshot
6. основной planning pipeline стартует отдельно с готовыми source topology snapshot и target topology snapshot

### Когда идея может быть принята без отдельного pre-pass

Только если topology нужна не в `enrich`/`match` на первых записях, а:

- в поздней batch-oriented стадии;
- или после полного завершения source consumption;
- или для off-line анализа / отчёта.

Для текущего обсуждаемого use case matching departments это условие не выполняется, поэтому hidden incremental build в том же проходе не даёт корректного результата.

## Аналитика: отдельная стадия инициализации до Extract

Рассмотрен ещё один вариант:

- до старта обычного planning pipeline выполняется отдельная runtime initialization stage;
- она полностью читает source;
- строит source topology snapshot;
- сохраняет готовый snapshot в run-scoped artifacts/provider;
- только после этого запускается обычный `Extract -> Map -> Normalize -> Enrich -> Match -> Resolve`.

### Сильные стороны подхода

Этот вариант архитектурно чище, чем hidden accumulation внутри stage chain.

Плюсы:

- topology полностью готова до начала record-by-record обработки;
- `enrich`, `match`, `resolve` получают уже завершённый snapshot;
- lifecycle topology явно отделён от lifecycle обычных stages;
- проще reasoning по корректности, чем при incremental graph build в том же pass;
- snapshot можно сохранить как immutable run-scoped artifact.

Для текущего use case это особенно полезно, потому что:

- topology нужна рано;
- source и target имеют разные формы представления иерархии;
- нельзя полагаться на постепенное "дозревание" graph по ходу stream.

### Главный компромисс

Цена подхода:

- source читается полностью до начала основного pipeline;
- затем source, вероятно, придётся читать ещё раз для обычного ETL-прохода;
- появляется отдельный bootstrap lifecycle step;
- старт run становится дороже по latency.

Это не архитектурная проблема, а явный trade-off:

- **простота и корректность topology**
  против
- **дополнительного чтения source и более долгого старта**

### Ключевой вопрос: из чего именно строить topology в init stage

Есть два подварианта:

#### Вариант A. Чтение raw source напрямую

Initialization stage сама парсит исходный source layout и извлекает hierarchy columns.

Плюсы:

- не зависит от `MapStage`;
- формально выполняется ещё до `Extract`.

Минусы:

- topology bootstrap начинает знать о сырых именах колонок и source layout;
- появляется дублирование логики извлечения полей;
- выше риск расхождения между bootstrap path и основным ETL path.

#### Вариант B. Отдельный bootstrap flow поверх source reader

Initialization stage читает source, но прогоняет записи через ограниченный projection flow:

- source reader
- map
- optional topology-normalize
- source topology collector

Плюсы:

- topology строится уже по каноническим field names;
- меньше риск расхождения с основным ETL;
- можно переиспользовать существующие map/normalize контракты или их подмножество.

Минусы:

- это уже не "голая" init stage, а mini-pipeline до основного pipeline;
- нужно аккуратно ограничить этот bootstrap, чтобы не дублировать весь основной planning chain.

### Предпочтение по архитектуре

Из двух подвариантов предпочтительнее:

- **не raw initialization parser**
- а **explicit topology bootstrap flow**

То есть по смыслу:

- да, topology строится до `Extract` основного pipeline run;
- но строится она не напрямую из сырых колонок, а через ограниченный bootstrap path с canonicalized fields.

### Практический вывод

Для текущего проекта этот вариант выглядит одним из самых сильных кандидатов на Phase 1:

- topology готова заранее;
- основной streaming pipeline не ломается;
- стадии получают только read-only snapshot;
- orchestration остаётся явной и диагностируемой.

Но важно не допустить, чтобы init stage превратилась в скрытую вторую копию всего planning pipeline.

### Предварительная рекомендация по этому варианту

Если выбирать между:

- hidden graph accumulation внутри stage chain;
- инициализацией topology до старта run;

то второй вариант предпочтительнее.

Рабочая форма этого решения:

1. `TopologyBootstrapUseCase` или эквивалентный orchestration step
2. читает source отдельно
3. строит source topology snapshot
4. параллельно или заранее получает target topology snapshot
5. сохраняет оба snapshot в run-scoped artifacts/provider
6. запускает основной planning pipeline

### Открытый вопрос по реализации

Нужно отдельно решить:

- будет ли topology bootstrap всегда читать source дважды;
- или для некоторых source adapters возможен reopen/replay механизм;
- или bootstrap должен работать на отдельном topology-specific input artifact.

## Аналитика: стоит ли объединять pre-run проверки в общую Initialization Phase

В обсуждении поднят более широкий вопрос:

- если для topology уже нужен отдельный startup/bootstrap step,
- возможно, его не стоит делать узкоспециализированным только под `dependency_tree`,
- а лучше оформить как общую `Initialization Phase` приложения.

Это направление выглядит архитектурно сильным.

### Что происходит в runtime сейчас

На текущий момент pre-run проверки и startup work уже существуют, но они распределены по нескольким слоям:

1. **App callback**
   - загрузка settings;
   - `configure_runtime_paths(...)`;
   - `configure_registry_path(...)`;
   - создание `log_dir/report_dir/cache_dir`.

2. **CLI runtime orchestrator**
   - `validate_requirements(...)`;
   - проверка обязательных API settings;
   - проверка dataset existence;
   - проверка source spec и существования source file;
   - проверка доступности cache dir;
   - проверка vault-mode compatibility.

3. **Container resource init**
   - открытие SQLite engines;
   - `ensure_cache_ready(...)`;
   - `ensure_identity_schema(...)`;
   - `ensure_vault_schema(...)`;
   - vault startup guard;
   - init target runtime;
   - init dictionaries backend.

4. **Command / handler level**
   - часть dataset-specific ошибок всплывает при `build_dataset_spec(...)`;
   - DSL/spec ошибки частично проявляются при lazy materialization stages/providers;
   - некоторые runtime failures происходят уже в момент фактического выполнения handler-а.

Итог:

- нужная инициализация в проекте уже есть;
- но она **размазана** по нескольким этапам lifecycle;
- у неё нет единого явного имени и единой модели отчётности.

### Почему общая Initialization Phase выглядит правильно

Если смотреть шире, чем `dependency_tree`, то отдельная Initialization Phase может стать местом для:

- preflight validation config/runtime paths;
- dataset registry / DSL readiness;
- source accessibility checks;
- cache/vault/dictionary readiness;
- optional topology bootstrap;
- optional cache freshness validation;
- будущих run-scoped bootstrap artifacts.

То есть это не "этап ради topology", а **единый pre-run readiness layer**.

### Что важно не перепутать

При этом не всё нужно насильно переносить в Initialization Phase.

Нужно различать три класса работ:

#### 1. Fast fail-fast validation

Проверки, которые должны быстро упасть до старта run:

- settings load/merge errors;
- missing required config values;
- несуществующий dataset;
- несуществующий source file;
- недоступный cache dir.

#### 2. Resource readiness

Проверки и init инфраструктуры:

- открыть SQLite;
- убедиться в схемах;
- поднять target runtime;
- подготовить dictionaries;
- проверить vault startup guard.

#### 3. Expensive optional bootstrap

Тяжёлые операции, которые нужны не всем сценариям:

- source topology build;
- target topology snapshot build;
- cache freshness probes;
- будущие expensive preload/index build tasks.

Именно третий класс не стоит делать безусловным для каждой команды.

### Предварительный вывод

Да, общая `Initialization Phase` имеет смысл.

Но её лучше проектировать как **многошаговый orchestrated lifecycle**, а не как одну монолитную функцию "сделать всё".

Хорошая модель:

- `PreflightValidationStep`
- `ResourceInitializationStep`
- `OptionalBootstrapStep`

Где `dependency_tree` bootstrap ложится в третий шаг.

### Почему это лучше, чем просто "смешать всё вместе"

Если без структуры сложить topology build, config validation, cache checks и resource init в один блок, то получится тяжёлый God-step с размытыми обязанностями.

Если же оформить это как явную phase с внутренними step-контрактами, получится:

- единая точка orchestration;
- понятная диагностика "на каком шаге старт провалился";
- возможность включать/выключать bootstrap capability по command requirements;
- расширяемость под будущие pre-run механизмы.

### Рекомендация для проекта

На данном этапе разумно думать не в терминах:

- "делаем init phase только для topology"

а в терминах:

- "вводим общую Initialization Phase runtime"
- topology bootstrap становится одним из optional initialization tasks

### Предварительная целевая модель

В долгосрочном виде startup lifecycle может выглядеть так:

1. Settings/config load
2. Preflight validation
3. Resource initialization
4. Optional runtime bootstrap
   - topology
   - dictionaries preload
   - future indexes
5. Handler execution
6. Shutdown/finalize

### Важный practical нюанс

`cache refresh` по-прежнему логично оставлять отдельным use case, а не скрытой частью общей initialization phase.

Причина:

- это отдельный сценарий с внешними API calls;
- он дорогой;
- он меняет persisted runtime state;
- не каждая команда должна молча его запускать.

То есть:

- **cache readiness** можно проверять в initialization;
- **cache rebuild/refresh** не стоит автоматически смешивать с обычным startup.

## Обоснование решения tree-first

Почему на первом этапе выбран именно `tree-first`:

- текущий основной use case иерархический (`id + parent_id`);
- disambiguation для `departments/organizations` естественно опирается на путь предков;
- tree-модель проще валидировать и диагностировать;
- tree-модель проще интегрировать в `enrich`, `match`, `resolve`;
- можно быстрее получить рабочий полезный результат без раннего усложнения API и DSL.

Почему не `DAG-first` на первом этапе:

- DAG заметно расширяет контракт узла и усложняет query API;
- потребуется иначе проектировать traversal, signatures и interpretation business rules;
- на текущем наборе задач это добавит сложность раньше, чем появится подтверждённая необходимость.

## Следующие шаги

Ближайший следующий шаг в проектировании:

1. Уточнить domain model Phase 1:
   - node contract для tree-first;
   - forest semantics;
   - diagnostics contract.

2. Зафиксировать канонический runtime source snapshot:
   - cache vs source vs dictionary vs отдельный dataset.

3. Зафиксировать runtime integration point:
   - где snapshot создаётся;
   - как передаётся в stage context.

4. Выделить первый практический use case:
   - disambiguation одинаковых `departments` по topology.

5. После этого подготовить technical design:
   - файлы;
   - классы;
   - порты;
   - DI wiring;
   - тестовая стратегия.

## Decision framing: продолжать поиск вариантов или выбирать

На текущем этапе проектирования уже рассмотрено достаточно вариантов, чтобы **не продолжать широкий поиск новых точек сборки graph**, а перейти к осознанному выбору из ограниченного shortlist.

Причина:

- основные topology lifecycle patterns уже покрыты;
- дальнейший поиск новых вариантов с высокой вероятностью даст лишь вариации уже рассмотренных подходов;
- сейчас важнее выбрать корректную orchestration model, чем собирать ещё больше альтернатив.

Иными словами:

- **пространство решений уже достаточно исследовано**
- дальше нужен **decision narrowing**, а не расширение списка опций

## Полный список реально значимых вариантов

Ниже перечислены не все возможные фантазийные варианты, а те архитектурные формы, которые действительно имеют смысл для проекта.

### Option 1. Lazy build on first use

Граф строится только в момент первого обращения стадии или сервиса к topology capability.

Плюсы:

- нет startup cost, если topology не понадобилась;
- выглядит просто снаружи.

Минусы:

- первый потребитель платит всю стоимость bootstrap;
- сложнее lifecycle и диагностика;
- если источник source-backed, то lazy build всё равно превращается в скрытый pre-pass;
- хуже контролируется момент отказа;
- может неожиданно ломать latency конкретной стадии.

Оценка:

- для проекта как основной вариант слабый.

### Option 2. Incremental build inside main stage chain

Граф постепенно собирается во время обычного streaming pipeline.

Плюсы:

- теоретически одно чтение source;
- не нужен отдельный lifecycle step.

Минусы:

- topology не готова для ранних stage queries;
- появляется скрытый stateful behavior в проходе;
- для корректного query-use нужен hidden buffer/barrier;
- это конфликтует с прозрачностью streaming contract.

Оценка:

- как основной runtime pattern не рекомендован.

### Option 3. Post-Map incremental collector in same pass

Отдельный collector получает mapped rows и накапливает topology в том же проходе.

Плюсы:

- работает на canonicalized fields;
- не зависит от raw source layout;
- сохраняет изоляцию domain graph builder.

Минусы:

- проблема готовности snapshot остаётся;
- для `enrich/match` в том же pass topology всё равно не готова;
- при попытке использовать сразу вырождается в buffer barrier.

Оценка:

- годится только как internal form bootstrap pass, но не как самостоятельная модель основного run.

### Option 4. Dedicated bootstrap pass before main pipeline

До основного planning pipeline выполняется отдельный bootstrap flow, который строит topology, после чего запускается основной поток.

Плюсы:

- topology готова заранее;
- сохраняется чистый streaming contract основного pipeline;
- lifecycle явный;
- хорошо диагностируется;
- stage logic остаётся простой.

Минусы:

- source читается отдельно;
- выше startup latency;
- нужен явный orchestration step.

Оценка:

- один из двух strongest candidates.

### Option 5. Dedicated initialization phase with optional topology bootstrap

Граф строится как часть общей Initialization Phase, где уже живут preflight, resource init и optional bootstrap tasks.

Плюсы:

- единая lifecycle model;
- хорошая extensibility;
- topology bootstrap становится частью общей runtime readiness architecture;
- удобно добавлять future bootstrap tasks.

Минусы:

- требует сначала оформить сам startup lifecycle;
- есть риск переусложнить старт приложения, если сделать слишком общий framework;
- dependency_tree зависит от зрелости initialization orchestration.

Оценка:

- сильнейший long-term architectural вариант.

### Option 6. External precomputed topology artifact

Граф или topology snapshot готовится заранее вне обычного run и потом только подгружается.

Примеры:

- отдельный topology CSV;
- persisted snapshot artifact;
- dictionary-like prebuilt hierarchy source.

Плюсы:

- быстрый startup основного run;
- нет повторного обхода source в обычном execution path.

Минусы:

- появляется дополнительный artifact lifecycle;
- нужен контроль freshness/consistency;
- это скорее deployment/runtime optimization, чем базовая Phase 1 модель.

Оценка:

- не лучший baseline для первой реализации, но хороший future extension.

## Критерии оценки

Для выбора момента сборки graph стоит использовать не интуицию, а фиксированный набор критериев.

### 1. Корректность topology к моменту использования

Если stage делает topology-aware query, snapshot должен быть завершён и валиден.

Это жёсткий критерий. Если вариант его не выполняет, он отпадает независимо от удобства.

### 2. Совместимость со streaming contract

Основной pipeline в проекте ленивый и построчный. Решение не должно тайно превращать его в full-buffering pass.

### 3. Изоляция ответственности

`dependency_tree` не должен затягивать в себя source parsing, stage orchestration и runtime side effects.

### 4. Диагностируемость

Должно быть ясно:

- на каком шаге упал startup;
- построен ли snapshot;
- какой source использовался;
- какие topology diagnostics получены.

### 5. Стоимость внедрения в существующий проект

Нужно учитывать:

- насколько много кода в lifecycle придётся менять;
- затрагивается ли `PlanningPipeline`;
- потребуется ли вводить новые порты/контексты/DI wiring.

### 6. Расширяемость

Решение не должно закрывать путь к:

- нескольким snapshot в одном run;
- source + target topology;
- future DAG upgrade;
- additional bootstrap artifacts.

## Матрица итоговой оценки

Если смотреть на варианты по совокупности критериев, получается такой practical shortlist:

### Tier C. Не брать как baseline

- `Option 1` lazy build on first use
- `Option 2` incremental build inside main chain
- `Option 3` collector in same pass as final runtime model

Почему:

- либо snapshot не готов вовремя;
- либо lifecycle становится скрытым;
- либо streaming contract деградирует неявно.

### Tier B. Допустимы как вторичные расширения

- `Option 6` external precomputed topology artifact

Почему:

- полезно позже;
- но это не лучший старт для Phase 1.

### Tier A. Реальные кандидаты для выбора

- `Option 4` dedicated bootstrap pass before main pipeline
- `Option 5` initialization phase with optional topology bootstrap

Почему:

- topology готова к моменту stage use;
- основной pipeline остаётся чистым;
- lifecycle явный;
- архитектурные обязанности распределяются корректно.

## Итоговая рекомендация

### Короткий ответ

**Продолжать искать новые варианты момента сборки graph уже не нужно.**

Нужно выбирать между двумя сильными моделями:

1. `DedicatedTopologyBootstrapPass`
2. `GeneralInitializationPhase` с optional `TopologyBootstrapStep`

### Более точный выбор

Если цель:

- быстрее внедрить working Phase 1;
- не блокировать разработку `dependency_tree`;
- минимально трогать общий lifecycle;

то pragmatic starting point:

- **сначала выбрать `DedicatedTopologyBootstrapPass`**

Если цель:

- одновременно выстроить правильный startup lifecycle платформы;
- использовать этот механизм не только для topology, но и для будущих bootstrap tasks;

то architectural target:

- **эволюционно прийти к `GeneralInitializationPhase`**

### Рекомендуемая стратегия для проекта

Лучший компромисс не "или-или", а двухшаговая стратегия:

#### Step 1. Tactical baseline

Реализовать topology build как отдельный explicit bootstrap pass.

Это даст:

- быстрый старт реализации;
- минимально достаточную корректную модель;
- независимость `dependency_tree` от полного redesign startup lifecycle.

#### Step 2. Strategic consolidation

После этого встроить bootstrap pass в общую `Initialization Phase`, не меняя domain contract `dependency_tree`.

Это даст:

- единый startup lifecycle;
- reuse для других readiness/bootstrapping задач;
- clean long-term architecture.

## Final recommendation for current design stage

На текущем этапе проектирования стоит зафиксировать следующее:

1. Больше не искать новые generic варианты момента сборки graph.
2. Признать победившей тактической моделью:
   - **explicit source/target topology bootstrap before main pipeline**
3. Параллельно считать стратегической целевой архитектурой:
   - **general Initialization Phase runtime**
4. Дальше обсуждать уже не "когда вообще строить graph", а:
   - какой bootstrap contract нужен;
   - где он живёт;
   - как передаёт snapshot в run-scoped artifacts/provider;
   - как активируется по command requirements.

## Runtime integration contract: hybrid step + service

В отдельном обсуждении уточнён runtime integration contract.

Выбран гибридный подход между:

- bootstrap как отдельный use case / service;
- bootstrap как initialization step внутри runtime orchestration.

### Принцип разделения ответственности

Разделяются две роли:

1. **Runtime orchestration владеет моментом вызова bootstrap**
2. **Bootstrap service/use case владеет логикой построения topology**

То есть:

- в runtime lifecycle появляется `TopologyBootstrapStep`;
- этот step не строит graph сам;
- он вызывает отдельный `TopologyBootstrapService` или `TopologyBootstrapUseCase`;
- результат публикуется как run-scoped topology capability/provider;
- стадии получают topology только как read-only capability.

### Почему не чистый use case-only вариант

- lifecycle run всё равно контролируется delivery/runtime;
- bootstrap нужно увязать с startup checks, container resources и command requirements;
- иначе получится второй orchestration слой рядом с `runtime/orchestrator.py`.

### Почему не чистый runtime-step-only вариант

- runtime слой начнёт владеть предметной логикой topology build;
- orchestration и domain/bootstrap logic смешаются;
- ухудшится SRP и тестируемость.

### Предпочтительная форма runtime artifact

Для Phase 1 предпочтительнее использовать явный run-scoped carrier, а не map
по string keys.

Пример:

```python
@dataclass(frozen=True)
class TopologyRunArtifacts:
    source_snapshot: TopologySnapshot | None
    target_snapshot: TopologySnapshot | None
    metadata: TopologyBuildMetadata
```

Такой carrier:

- лучше выражает двухстороннюю Phase 1 модель;
- уменьшает риск конкурирующих string-based contracts;
- остаётся внутренним orchestration artifact, а не stage-facing API.

### Утверждённый DI placement

Зафиксировано решение:

- topology не должна доставляться через mutable slot в `AppContainer`;
- bootstrap строит run-scoped artifacts/provider внутри handler после resolve
  dataset/topology spec и до materialization pipeline;
- pipeline assembly получает topology dependency уже после успешного bootstrap;
- stages читают topology через scoped execution context.

Причина выбора:

- bootstrap выполняется на уровне runtime orchestration, а не внутри pipeline;
- topology artifact может понадобиться не только stage wiring, но и другим run-scoped runtime consumers;
- это лучше согласуется с уже существующим `StageExecutionContext`;
- уменьшается скрытый mutable state composition root.

### Предпочтительная форма bootstrap contract

```python
@dataclass(frozen=True)
class TopologyBootstrapRequest:
    pipeline_dataset: str
    topology_dataset: str | None
    run_id: str
    require_source_topology: bool
    require_target_topology: bool


@dataclass(frozen=True)
class TopologyBootstrapResult:
    artifacts: TopologyRunArtifacts | None
    errors: tuple[DiagnosticItem, ...]
    warnings: tuple[DiagnosticItem, ...]
```

Утверждённое уточнение:

- `TopologyBootstrapResult` не использует один общий tuple `diagnostics`;
- bootstrap boundary явно разделяет:
  - `errors`
  - `warnings`
- при наличии фатальных ошибок bootstrap result должен содержать `artifacts=None`.

Семантика:

- `errors` => bootstrap прерывает дальнейший handler path;
- `warnings` допустимы вместе с валидными `artifacts`;
- partial success допустим только если topology snapshot целостный и пригодный для query.

Дополнительно утверждено по request contract:

- внешний orchestration boundary использует один `TopologyBootstrapRequest`;
- этот request остаётся lightweight routing/activation object;
- `TopologyBootstrapRequest` не должен нести topology policy/strictness semantics;
- `topology_dataset is None` означает: использовать `pipeline_dataset`.
- нормализация `topology_dataset is None -> pipeline_dataset` должна происходить в одном месте внутри bootstrap orchestration/use case boundary.

Принятый shape:

```python
@dataclass(frozen=True)
class TopologyBootstrapRequest:
    pipeline_dataset: str
    topology_dataset: str | None
    run_id: str
    require_source_topology: bool
    require_target_topology: bool
```

Утверждено также внутреннее разделение build paths:

- orchestration-level request остаётся единым;
- внутри bootstrap use case source и target build path получают отдельные специализированные request-объекты.

Пример:

```python
@dataclass(frozen=True)
class SourceTopologyBuildRequest:
    pipeline_dataset: str
    topology_dataset: str
    run_id: str


@dataclass(frozen=True)
class TargetTopologyBuildRequest:
    pipeline_dataset: str
    topology_dataset: str
    run_id: str
```

Причина выбора:

- lifecycle boundary остаётся простой для runtime orchestration;
- source и target topology build paths могут эволюционировать независимо;
- request не превращается в giant object с взаимоисключающими полями и policy drift.

Что не входит во внешний `TopologyBootstrapRequest`:

- topology policy / strictness flags;
- raw source paths;
- topology field names;
- report/log concerns.

### SourceTopologyProjection contract

Для source-side bootstrap утверждён отдельный projection boundary между source/bootstrap orchestration и domain `dependency_tree` builder.

Базовый ingestion contract для `Phase 1`:

```python
@dataclass(frozen=True)
class SourceTopologyCanonicalPath:
    canonical_segments: tuple[str, ...]
```

Причины выбора:

- domain builder в baseline не должен зависеть от количества исходных строк и от
  row-level duplicates;
- `canonical_segments` — минимальный стабильный контракт для prefix-based hierarchy build;
- projection layer не должен вычислять synthetic node ids или parent ids;
- projection layer не должен протаскивать raw source rows в domain.

Если adapter-у нужен trace/diagnostic envelope, он может дополнительно использовать
внутренний DTO:

```python
@dataclass(frozen=True)
class SourceTopologyProjectionTraceRow:
    row_ref: RowRef | None
    display_segments: tuple[str, ...]
    canonical_segments: tuple[str, ...]
```

Но этот DTO не считается обязательным builder contract.

Что делает projection layer:

- читает source через canonicalized bootstrap path;
- выбирает только topology-relevant hierarchy fields;
- нормализует значения сегментов пути;
- отбрасывает пустые сегменты;
- делает `distinct` canonical paths;
- отдаёт builder-у canonical batch.

Что остаётся в domain topology builder:

- generation synthetic node ids из path prefixes;
- parent derivation из path prefixes;
- duplicate/orphan/self-loop/cycle handling;
- topology diagnostics, зависящие от graph semantics;
- final `TopologySnapshot` assembly.

Архитектурное ограничение:

`SourceTopologyProjection` утверждён как dedicated lightweight bootstrap projection. Он:

- не является raw source parsing shortcut;
- не дублирует parser поверх оригинальных CSV-колонок;
- не требует replay полного main mapping pipeline.

Отклонённые альтернативы для `Phase 1`:

- projection row с уже вычисленными `node_key` / `parent_key`;
- raw source rows как direct input в domain builder;
- full main mapping replay как обязательный projection contract.

Дополнительные уточнения:

- `leaf_name` отдельно не хранится, потому что выводится из последнего непустого path segment;
- raw path string не включается в baseline DTO для `Phase 1`;
- если позже понадобятся source-side metadata, DTO можно расширить, но baseline остаётся path-centric.

### SourceTopologyProjection pipeline

Для `Phase 1` утверждён следующий pipeline source-side topology bootstrap:

```text
TopologyBootstrapUseCase
  -> resolve topology projection config
  -> topology source projection adapter
  -> optional vectorized canonicalization / dedup
  -> distinct canonical path batch (+ optional trace rows)
  -> SourceTopologyBuilder
  -> TopologySnapshot
```

Что уже считается принятым:

- bootstrap orchestration получает уже normalized `TopologyBootstrapRequest`;
- source-side bootstrap должен переиспользовать тот же source config contract, что и основной runtime,
  но не обязан переиспользовать тот же reader implementation;
- если source представляет собой CSV и topology использует только hierarchy path columns,
  предпочтительна отдельная infra-проекция на Polars вместо построчного mini-pipeline;
- projection mapper выделяет только topology-relevant hierarchy fields и задаёт их порядок;
- topology path normalizer отвечает за canonicalization path segments;
- domain builder — первый компонент, который имеет право знать graph semantics.

### Граница ответственности по шагам

#### 1. Resolve topology projection config

Bootstrap use case сначала получает topology-specific projection description:

- какие source fields участвуют в hierarchy path;
- в каком порядке сегменты составляют path;
- какие normalization rules допустимы для topology path.

Утверждённый вывод:

- bootstrap не должен зависеть от полного `mapping.yaml` как от обязательного runtime contract;
- но и не должен скатываться в raw-column parsing без явного topology projection description.

#### 2. Source reader

Source topology bootstrap должен использовать тот же source configuration contract, что и
основной ETL runtime, но может иметь отдельный projection-oriented reader/adapter.

Утверждено:

- не создавать отдельный ad-hoc CSV parser вне уже принятых infra-технологий проекта;
- source projection adapter не должен знать graph semantics;
- для CSV-backed source допустим и предпочтителен отдельный Polars-based projection reader,
  если он работает только с topology-relevant columns;
- raw row reader основного pipeline не должен становиться обязательным runtime contract
  для topology bootstrap.

#### 3. Projection mapper

Projection mapper — отдельная логическая ответственность внутри bootstrap flow.

Он:

- выделяет topology-relevant hierarchy values;
- не строит graph;
- не вычисляет synthetic ids;
- не обязан быть полноценной main-pipeline stage;
- может быть реализован как columnar projection step, а не как Python object mapper на каждую row.

Утверждённый вывод:

- нужен bootstrap-local projection component;
- не требуется replay полного `MapStage`;
- raw parsing inside domain builder отклонён.

#### 4. Topology path normalizer

`TopologyPathNormalizer` — отдельная responsibility, даже если реализация окажется лёгкой.

Он отвечает за:

- trim;
- blank segment collapse/removal;
- case/canonical form normalization;
- другие topology-specific normalization rules, если они будут разрешены позже.

Утверждённый вывод:

- canonicalization path segments — не responsibility source reader;
- canonicalization path segments — не responsibility domain graph builder.

#### 5. Projection row emission

После normalize/dedup flow baseline path отдаёт:

```python
@dataclass(frozen=True)
class SourceTopologyCanonicalPath:
    canonical_segments: tuple[str, ...]
```

Инварианты:

- `canonical_segments` уже canonicalized;
- blank segments уже removed;
- duplicates уже collapsed до builder ingestion;
- `node_id` / `parent_id` ещё не вычислены.

Если нужен row-level trace для diagnostics, он остаётся adapter-local side artifact и
не становится обязательным входом domain builder.

#### 6. Domain builder ingestion

`SourceTopologyBuilder` получает distinct canonical paths и уже внутри domain делает:

- synthetic node id generation;
- parent derivation from path prefixes;
- duplicate path aggregation;
- graph-level diagnostics;
- snapshot assembly.

Утверждённый вывод:

- builder — первый слой, который знает graph semantics;
- projection path не должен знать policy synthetic key derivation.

#### 7. Execution and buffering model

Topology bootstrap не обязан имитировать основной row-by-row streaming path.

Допустимы две формы source projection path:

- lazy row iterator для не-columnar или нестандартных source adapters;
- vectorized columnar projection для CSV-backed source, если это позволяет сократить I/O и
  количество промежуточных Python-объектов.

Для текущего topology use case более предпочтительной считается вторая форма:

- выбрать только hierarchy path columns;
- выполнить узкую canonicalization векторно;
- сделать `distinct` canonical paths до входа в domain builder;
- затем построить parent/child relations уже в domain.

`SourceTopologyBuilder` остаётся допустимым stateful terminal step, который буферизует topology state на весь bootstrap pass.

Причина:

- topology graph нельзя построить без накопления topology state;
- buffering разрешён, если он локализован в builder или в узкой infra-проекции и явно осознан как part of bootstrap lifecycle;
- при columnar projection буферизуется не весь row flow, а только topology-relevant subset данных.

### Что уже отклонено на уровне pipeline design

- `SourceTopologyProjection` как обычная stage основного main pipeline;
- raw source rows как direct input в builder;
- projection layer, вычисляющий `node_key` / `parent_key`;
- обязательный replay полного `MapStage` как projection contract.

### Что остаётся открытым после этих решений

- точный shape topology projection config/spec;
- точный набор допустимых normalization rules;
- empty-path / malformed-path policy;
- placement конкретных projection/builder-support classes по файлам.

### Topology DSL artifact

По итогам обсуждения утверждено, что topology для dataset должна оформляться как отдельный DSL-артефакт, а не как скрытое расширение `mapping.yaml`.

Предпочтительный артефакт:

- `datasets/<dataset>/topology.yaml`

Утверждённые выводы:

- topology не встраивается внутрь existing transform-stage DSL;
- topology не должна жить как ad-hoc config вне DSL loading pipeline;
- topology оформляется как отдельный DSL sublayer рядом с transform DSL, но с другим runtime lifecycle.

### Как topology связывается с registry

Принята двухуровневая модель:

- `registry.yaml` отвечает за capability/discovery-level signal: dataset topology-aware и topology spec существует;
- `topology.yaml` отвечает за detailed declarative behavior.

То есть:

- `registry.yaml` отвечает на вопрос: доступна ли для dataset topology capability;
- `topology.yaml` отвечает на вопрос: как именно строится hierarchy projection и canonicalization path.

Утверждённое ограничение:

- необходимость topology build для dataset не должна определяться только хардкодом command handlers;
- dataset-level declaration должна существовать в registry/spec layer.

### Что должно жить в `topology.yaml`

Без фиксации полного финального shape уже согласовано, что именно `topology.yaml` является местом для:

- source hierarchy fields;
- порядка path segments;
- topology-specific normalization declaration;
- будущих topology policies, если они будут вынесены в spec.

Это сознательно не должно жить:

- во внешнем `TopologyBootstrapRequest`;
- в raw Python wiring;
- в `mapping.yaml` как скрытая побочная секция.

### Предпочтительный `topology.yaml` shape

Для Phase 1 topology DSL стоит зафиксировать как отдельный Pydantic-backed artifact
с двумя независимыми секциями:

- `canonicalization`
- `source`
- `target`

`canonicalization` отвечает за shared segment-level normalization contract.

`source` отвечает только за source-side hierarchy projection contract.

Минимальный shape:

```yaml
dataset: dataset_name

topology:
  canonicalization:
    ops:
      - op: trim
      - op: lower
      - op: regex_replace
        pattern: "\\s+"
        repl: " "
      - op: compact
  source:
    mode: path_columns
    path_columns:
      - field: level_1_name
      - field: level_2_name

  target:
    mode: adjacency_list
    node_id_field: _ouid
    parent_id_field: parent_id
    target_label_field: name
    payload_target_id_field: _id
```

Что обязательно фиксируется:

- `path_columns` для source; порядок задаётся порядком YAML list;
- `node_id_field / parent_id_field` для target;
- `target_label_field` для target-side canonicalizer input;
- `payload_target_id_field`, если graph node id и payload write-id различаются;
- shared whitelist canonicalization ops на top-level `topology.canonicalization`.

### Whitelist canonicalization ops

Для Phase 1 рекомендуется зафиксировать только deterministic baseline ops:

- `trim`
- `lower`
- `compact`
- `regex_replace`

Почему именно так:

- они достаточно выразительны для canonical path cleanup;
- хорошо сочетаются с Polars expression API;
- не требуют раннего ухода в Python UDF;
- снижают риск превратить topology bootstrap во второй `NormalizeStage`.

Дополнительное уточнение:

- `coalesce` не входит в segment-level canonicalization whitelist;
- dual-form contract обязателен: один rule-set должен компилироваться и в Polars-expression plan
  для bootstrap, и в Python callable plan для row-level lookup / target label normalization.

Сознательно не включаются в Phase 1 baseline:

- произвольные Python UDF
- сложные cross-column transforms
- неограниченные user-defined operations

Почему canonicalization должен жить на общем уровне, а не внутри `source`:

- shared canonicalizer уже принят как один contract для source bootstrap, row-level source lookup и target hierarchy ingest;
- если canonicalization вложен только в `source`, target-side reuse становится неявной конвенцией, а не частью schema;
- если target-side canonicalization не происходит, `lower/trim` source path labels перестанут сходиться с raw target `name`.

Поэтому `target.target_label_field` должен трактоваться как raw input в тот же compiled canonicalizer,
который применяется к source path segments.

### Registry binding

Registry должен фиксировать не только stage specs, но и topology capability.

Предпочтительный block:

```yaml
datasets:
  dataset_name:
    topology:
      enabled: true
      spec: dataset_name.topology.yaml
```

Семантика:

- `enabled` = topology capability доступна для dataset;
- `spec` = где лежит declarative topology contract;
- реальное включение bootstrap всё равно определяется activation policy/requirement resolver.

Это как раз закрывает activation-условие №1:

- dataset topology capability declared in registry.

### Example for `organizations`

Для `organizations` target section уже можно считать concrete baseline, потому что
cache schema известна:

- `node_id_field: _ouid`
- `parent_id_field: parent_id`
- `target_label_field: name`

Source section для `organizations` в текущем шаблоне следует считать illustrative,
а не окончательной привязкой к текущему `source/source.yaml`, потому что текущий
organizations source сейчас не несёт готовый ordered path-columns contract.

Практический вывод:

- template `datasets/organizations/organizations.topology.yaml` можно держать уже сейчас;
- при реализации source-side topology его `source.path_columns` должны быть привязаны к
  реальным hierarchy columns конкретного source dataset или topology source.

### Topology как отдельный DSL sublayer

Утверждённая модель:

- topology должна использовать те же общие DSL-принципы, что и остальные declarative артефакты проекта:
  - Pydantic spec;
  - loader/validator;
  - compiler;
  - executable compiled topology projection.

При этом topology bootstrap:

- не является обычной streaming stage chain;
- не должен моделироваться как ещё одна стадия `Extract -> Map -> Normalize -> ...`;
- имеет собственный bootstrap lifecycle и output contract (`TopologySnapshot`, а не обычный row contract).

### Применимость библиотек

Ниже зафиксировано предпочтительное использование уже доступных библиотек и stdlib
инструментов для topology-подсистемы, чтобы не дублировать готовые механизмы.

#### 1. Polars

Polars должен использоваться там, где topology bootstrap имеет дело с tabular source-side
projection.

Предпочтительный scope применения:

- только `infra/` слой;
- чтение source CSV для topology bootstrap отдельным projection adapter;
- выбор только hierarchy path columns;
- узкая canonicalization path segments через expression API;
- `distinct` / `unique` canonical paths до передачи данных в domain builder.

Почему это предпочтительно:

- снимает необходимость гонять весь source через построчный mini-pipeline ради нескольких path columns;
- уменьшает количество domain-ingestion объектов за счёт `distinct` canonical paths;
- делает source-side topology build ближе к `O(distinct paths)`, а не к `O(all rows)` по числу domain-ingestion объектов;
- оставляет Polars внутри допустимой архитектурной границы проекта.

Практический вывод:

- source topology bootstrap не должен быть жёстко привязан к текущему `CsvRecordSource`;
- ему нужен отдельный infra projection adapter, который использует тот же source config contract,
  но может исполняться более эффективно;
- topology normalization whitelist желательно ограничить операциями, которые хорошо выражаются
  через Polars expressions.

Предпочтительные topology ops для такого пути:

- `trim`
- `lower`
- `compact`
- `regex_replace`

Сознательно не включаются в segment-level canonicalizer:

- `coalesce`
- cross-segment concat
- произвольный null-fallback вне projection layer

С осторожностью:

- `transliterate`
- произвольные Python UDF
- сложные cross-column business transforms

Они возможны, но ухудшают vectorization и не должны становиться baseline Phase 1.

#### 2. Pydantic

Pydantic должен использоваться только на trust boundaries topology-подсистемы, а не внутри
runtime graph/query моделей.

Предпочтительный scope применения:

- `topology.yaml` spec models;
- registry-level topology capability declaration;
- topology compiler input/output models, если они пересекают DSL boundary;
- validate/load шаги bootstrap-конфигурации.

Не рекомендуется использовать Pydantic для:

- `TopologyNode`
- `TopologySnapshot`
- query/runtime services
- внутренних builder accumulators
- `SourceTopologyCanonicalPath` и optional trace DTO, если они остаются внутренними trusted объектами

Почему:

- topology snapshot живёт в hot runtime path и должен оставаться лёгким immutable domain object;
- повторная валидация уже доверенных внутренних данных не даёт полезной защиты;
- dataclass лучше соответствует current project rule: boundary data validated by Pydantic,
  internal domain state represented plain Python objects.

Практический вывод:

- topology DSL/spec layer — Pydantic;
- topology runtime/domain layer — frozen dataclass / plain classes;
- если нужен строгий boundary between infra projection and domain builder, лучше добавить
  узкий compiler/mapper contract, а не валидировать каждый runtime row через Pydantic.

#### 3. graphlib

`graphlib` из stdlib полезен, но не заменяет topology snapshot subsystem целиком.

Что он закрывает хорошо:

- topological ordering;
- cycle detection;
- базовую DAG/tree validation при наличии mapping `node -> predecessors`.

Чего он не закрывает:

- `children_by_id`;
- `parent_by_id`;
- `ancestors` / `descendants`;
- `path_to_root`;
- `root_id`;
- topology-aware query API.

Предпочтительное применение:

- использовать `TopologicalSorter` в validator/build step для проверки cycle-free topology и получения topological order;
- не строить поверх него stage-facing runtime API напрямую;
- не смешивать `graphlib` usage с source/target projection responsibility.

Практический вывод:

- `graphlib` должен упрощать validator/builder internals;
- но custom `TopologySnapshot` и индексная модель всё равно остаются необходимыми;
- этот же подход потенциально применим и к уже существующему `CacheDependencyGraph`, если
  проект решит унифицировать алгоритмы dependency ordering.

#### 4. hashlib

`hashlib` уже используется в проекте для стабильных fingerprints и хорошо подходит для topology.

Предпочтительный scope применения:

- deterministic synthetic node ids для source-side topology;
- fingerprint normalization contract/version;
- snapshot provenance metadata;
- structural signatures, если они действительно нужны consumer-ам.

Предпочтительные правила:

- не использовать Python `hash()`;
- строить hash только от canonicalized и детерминированно сериализованного payload;
- version/namespace prefix включать в hashing contract;
- display path никогда не использовать как единственный ID contract.

Практический вывод:

- `node_id` может быть derived как `sha256` от canonical segments + normalization version;
- `parent_id` должен вычисляться от canonical prefix тем же способом;
- metadata вроде `topology_normalization_version` и `source_file_fingerprint` естественно
  ложатся в уже существующий fingerprint-style проекта.

### Повторное чтение и повторная узкая нормализация

По итогам обсуждения это признано допустимым и осознанным trade-off.

Что повторяется:

- повторное чтение source;
- повторное извлечение hierarchy fields;
- отдельная узкая topology-normalization этих полей;
- затем основной pipeline снова выполняет `Map/Normalize` для полного row flow.

Утверждённый вывод:

- это не считается архитектурной ошибкой само по себе;
- это приемлемая цена за готовый topology snapshot до старта main pipeline;
- topology normalization должна оставаться узкой и дешёвой, а не вырождаться во второй `NormalizeStage`;
- при отдельной Polars-based source projection это должно выглядеть как повторный projection pass
  по ограниченному числу колонок, а не как повторение всего object-level transform flow.

### Как ограничивать дублирование

Согласовано следующее направление:

- topology normalizer использует узкий whitelist deterministic ops;
- topology normalization rules описываются отдельно и явно;
- они не обязаны совпадать 1:1 с полным `NormalizeStage`;
- цель — не убрать дублирование любой ценой, а не дать ему расползтись в полноценный второй transform flow.

### Куда передавать результат

Предпочтительно не класть topology напрямую в mutable `PipelineRunContext`, а передавать её как capability/provider path:

- через `StageExecutionContext`.

Причина:

- topology snapshot — это read-only runtime capability;
- концептуально она ближе к execution context, чем к mutable per-run mechanics.

Утверждённое уточнение:

- stages не получают `TopologyRunArtifacts` напрямую;
- stages получают узкий `TopologyProviderPort`;
- `TopologyRunArtifacts` остаётся внутренним run-scoped artifact.

Причины:

- слабее связность stage API;
- `TopologyRunArtifacts` может эволюционировать без влияния на stages;
- это лучше соответствует hexagonal pattern проекта.

Утверждённый provider contract:

```python
class TopologyProviderPort(Protocol):
    def require_source(self) -> TopologySnapshot: ...
    def require_target(self) -> TopologySnapshot: ...
    def get_source(self) -> TopologySnapshot | None: ...
    def get_target(self) -> TopologySnapshot | None: ...
```

Дополнительное уточнение после ревизии:

- `TopologyProviderPort` должен оставаться snapshot-only;
- `TopologyRunArtifacts.metadata` не должна напрямую протекать в stage-facing API;
- если freshness/readiness влияет на `MatchStage`, это должно делаться через
  dedicated consumer adapter (`TopologyMatchService`), а не через generic metadata getter на provider.

Дополнительно принято:

- stages не должны зависеть от raw string names topology snapshots;
- `require_*()` должен выбрасывать typed exception, если обязательный snapshot не доступен;
- `get_*()` остаётся для optional topology consumers;
- именованные snapshots допустимы только как internal orchestration detail, если они вообще понадобятся внутри runtime layer.

Это решение нужно трактовать как:

- **расширяемость остаётся на internal runtime/orchestration уровне**;
- **явность и простота выбраны на stage-facing boundary уровня Phase 1**.

Пример:

```python
class TopologyNotAvailableError(Exception):
    ...
```

### Activation model

Bootstrap не должен быть always-on для всех команд.

Предпочтительная модель:

- on-demand activation by command requirements;
- базовые флаги:
  - `requires_topology`
  - `requires_source_topology`
  - `requires_target_topology`

Утверждённое уточнение:

- dataset/topology spec определяет, что topology capability существует и доступна для датасета;
- command requirements определяют, нужно ли реально активировать bootstrap в конкретной команде.

Иными словами:

- **spec says available**
- **command says needed**

После дополнительной ревизии эта мысль фиксируется жёстче:

- решение должно приниматься в одном `TopologyRequirementResolver`;
- command name сам по себе не является достаточным источником истины;
- checkpoint, dataset topology capability и compiled match policy должны
  рассматриваться вместе.

Рабочая activation matrix для текущих команд:

| Command / checkpoint | require_source_topology | require_target_topology | Комментарий |
|---|---:|---:|---|
| `mapping` | `False` | `False` | checkpoint до `Match` |
| `normalize` | `False` | `False` | checkpoint до `Match` |
| `enrich` | `False` | `False` | topology consumer ещё не включён |
| `match` | `True`* | `True`* | первый topology consumer |
| `resolve` | `True`* | `True`* | upstream включает `Match` |
| `import plan` | `True`* | `True`* | full planning pipeline включает `Match` |
| `import apply` | `False` | `False` | работает по `plan.json` |
| cache/vault/admin commands | `False` | `False` | не используют planning pipeline |

\* только если dataset/spec и compiled match policy реально требуют topology-aware matching.

### Working conclusion

Предпочтительный runtime integration contract:

- не строить topology в `PlanningPipeline.open()`;
- не делать lazy build on first use;
- использовать hybrid model:
  - runtime step владеет lifecycle;
  - bootstrap service/use case владеет построением;
  - стадии читают только capability.

Дополнительно утверждено:

- run-scoped topology capability/provider wiring в текущем кодовом контуре должно происходить
  **внутри handler**, после resolve `dataset_spec` / catalog и до materialization
  `planning_pipeline()`;
- bootstrap request должен различать:
  - `pipeline_dataset`
  - `topology_dataset: str | None`
- bootstrap failures short-circuit handler execution и должны маппиться в тот же report/runtime boundary, что и другие pre-handler failures.

Практическое следствие для реализации:

- отказ от mutable container override сам по себе не даёт готового wiring path;
- нужно либо научить `planning_pipeline`/pipeline assembly принимать topology provider
  как явный composition input;
- либо ввести эквивалентный handler-scope wiring механизм на уровне pipeline sub-container;
- текущий precedent для handler-scope override уже существует на dictionaries path,
  и topology integration должна учитывать этот реальный lifecycle, а не абстрактную
  фазу "до handler".

## Дополнительные рабочие уточнения после архитектурной ревизии

> Этот раздел фиксирует **рабочие рекомендации** для следующей версии плана.
> Они считаются предпочтительным направлением для дальнейшей проработки, но
> не помечаются здесь как окончательный ADR-контракт.

### 1. Phase 1 должна оставаться tree-first

На данном этапе не рекомендуется делать универсальную подсистему, одинаково
покрывающую:

- обычную hierarchy-модель `parent_id`;
- и произвольный DAG через `depends_on[]`.

Причина:

- practical use case Phase 1 — hierarchy-aware matching подразделений;
- tree-инварианты проще валидировать и объяснять;
- ранняя универсализация почти наверняка усложнит builder, validator,
  diagnostics и runtime contracts без немедленной пользы.

Рабочее уточнение:

- в Phase 1 целевой доменный контракт должен быть **hierarchy topology**;
- builder и validator могут быть tree-specific;
- public naming подсистемы может оставаться нейтральным к будущему DAG-расширению;
- отдельный generic DAG-контракт имеет смысл обсуждать только в следующей фазе,
  отдельным решением.

Следствие:

- `root_id`, `depth`, `path_to_root`, `ancestors`, `children`, `topology signature`
  остаются в scope Phase 1;
- support для `depends_on[]` и multiple parents не входит в базовую реализацию Phase 1.

### 2. Runtime delivery лучше строить через stage capability, а не через mutable container override

После дополнительной ревизии более предпочтительной признана следующая модель:

- bootstrap строит run-scoped topology artifacts;
- pipeline assembly получает их как вход runtime composition;
- stages читают topology через `StageExecutionContext`;
- stages зависят от узкого `TopologyProviderPort`.

Это предпочтительнее, чем поздняя мутация composition root, потому что:

- лучше согласуется с уже существующим `StageExecutionContext`;
- уменьшает скрытый mutable state в lifecycle запуска;
- проще тестируется;
- лучше удерживает hexagonal boundary между orchestration и stage execution.

Рабочее уточнение:

- topology не должна доставляться в stages через общий mutable container slot;
- `TopologyRunArtifacts` или аналогичный carrier может существовать внутри run-scoped orchestration layer;
- stage boundary должна видеть только provider port.

Предпочтительный provider contract для дальнейшей детализации:

```python
class TopologyProviderPort(Protocol):
    def require_source(self) -> TopologySnapshot: ...
    def require_target(self) -> TopologySnapshot: ...
    def get_source(self) -> TopologySnapshot | None: ...
    def get_target(self) -> TopologySnapshot | None: ...
```

Эта форма сейчас выглядит сильнее, чем string-based lookup по именам snapshot для
основного Phase 1 use case, потому что:

- прямее выражает ожидаемые source/target capabilities;
- уменьшает количество branching в consumer-коде;
- делает отсутствие обязательной topology capability явным boundary contract.

При этом source/target distinction остаётся частью internal runtime composition,
но не становится string-based публичным API для stages.

### 3. Source-side synthetic ids не должны быть буквальным path string

В обсуждении path вида:

- `company/division/team`

полезен как человекочитаемая structural form, но слаб как runtime identifier.

Основные риски:

- коллизии после canonicalization;
- зависимость от выбранного delimiter;
- сложность escape/serialization;
- неявная зависимость от версии normalization rules;
- смешение display-path и matching-path semantics.

Рабочее уточнение:

- нужно разделить:
  - `display_segments`
  - `canonical_segments`
  - `opaque synthetic node_id`
- primary key snapshot не должен совпадать с raw string path;
- synthetic `node_id` должен вычисляться детерминированно из canonical path и версии normalization contract;
- parent relation должна строиться от canonical path prefixes, а не от display labels.

Предпочтительный trace/projection DTO, если adapter-у нужна row-level diagnostics
поверх canonical batch:

```python
@dataclass(frozen=True)
class SourceTopologyProjectionRow:
    row_ref: RowRef | None
    display_segments: tuple[str, ...]
    canonical_segments: tuple[str, ...]
```

Это даёт:

- отделение UX/debug representation от matching representation;
- более устойчивый идентификатор;
- возможность безопасно менять display normalization отдельно от canonical matching contract;
- при этом builder baseline всё равно должен оставаться `distinct canonical path batch`,
  а не обязательный поток row-level DTO.

### 4. Bootstrap flow должен быть узким и не превращаться во второй planning pipeline

Это один из главных практических рисков дальнейшей реализации.

Принятое рабочее ограничение:

- bootstrap flow допускает только topology-нужные шаги;
- он не должен тянуть в себя enrich/match/resolve semantics;
- он не должен вырастать во второй полноценный `Map -> Normalize -> ...` pipeline.

Предпочтительная форма для Phase 1:

1. `Extract`
2. topology projection
3. topology normalization
4. topology collector / builder
5. materialize snapshot

Дополнительно:

- projection layer не вычисляет graph semantics;
- builder не знает source CSV layout;
- topology normalization остаётся отдельным узким контрактом;
- topology flow должен быть декларативно описываемым отдельно, а не прятаться
  внутри полного main pipeline DSL.

Рабочее направление:

- использовать отдельный `topology.yaml`;
- разрешить в topology normalization только узкий whitelist deterministic ops;
- не делать topology bootstrap “полным replay” всех main transform rules.

### 5. Нужен отдельный diagnostics/reporting boundary для topology bootstrap

Если bootstrap topology падает, это не должно выглядеть как случайная ошибка
в середине `enrich` или `match`.

Поэтому рекомендуется заранее зафиксировать отдельный boundary:

- отдельный bootstrap-specific `DiagnosticStage`;
- отдельные topology diagnostic codes;
- отдельный report context block для topology bootstrap.
- topology-specific коды должны жить в core catalog, а не в локальных строковых константах bootstrap implementation.

Предпочтительные классы ошибок для дальнейшей фиксации:

- `TOPOLOGY_SOURCE_PATH_EMPTY`
- `TOPOLOGY_DUPLICATE_NODE`
- `TOPOLOGY_PARENT_MISSING`
- `TOPOLOGY_CYCLE_DETECTED`
- `TOPOLOGY_NORMALIZATION_CONFLICT`
- `TOPOLOGY_TARGET_EMPTY`
- `TOPOLOGY_TARGET_STALE`
- `TOPOLOGY_SNAPSHOT_NOT_AVAILABLE`
- `TOPOLOGY_SOURCE_TARGET_INCOMPATIBLE`

Что это даст:

- fail-fast diagnostics до старта main handler flow;
- понятную операционную картину в отчётах;
- отсутствие смешения bootstrap failures со stage-local row diagnostics.

### 6. Нужно заранее учитывать drift и provenance source/target topology

Дополнительный риск, который стоит зафиксировать уже сейчас:

- source topology и target topology могут быть построены из разных по времени
  состояний данных;
- cache mirror target-системы может быть stale;
- matching начнёт сравнивать topology snapshots, относящиеся к разным версиям мира.

Рабочее уточнение:

- topology artifacts должны нести provenance metadata;
- bootstrap/report boundary должен сохранять fingerprint/ревизию source и target inputs;
- freshness cache-backed target topology должна быть проверяемой политикой,
  а не неявным допущением.

Минимально полезные metadata:

- `source_file_fingerprint`
- `cache_snapshot_revision`
- `built_at`
- `dataset_name`
- `topology_normalization_version`

### 7. Snapshot Phase 1 не должен быть перегружен тяжёлыми предрасчётами

Не рекомендуется на старте materialize-ить всё подряд:

- полные `descendants` для всех узлов;
- несколько вариантов fingerprints “на будущее”;
- лишние глобальные caches без подтверждённого consumer use case.

Предпочтительная модель:

- держать минимально достаточные индексы для Phase 1 matching/query use case;
- дополнительные представления считать only-if-needed;
- тяжёлые derived indexes добавлять только после появления реального downstream consumer.

Практически это означает:

- `nodes_by_id`, `parent_by_id`, `children_by_id`, `roots` остаются базой;
- path-based indexes допустимы, если они прямо нужны matching/disambiguation;
- всё остальное должно проходить отдельную проверку на реальную необходимость.

### 8. Сравнение source и target topology лучше описывать через explicit comparison ladder

Один “магический fingerprint” не должен становиться единственной semantics
topology-aware matching.

Предпочтительное рабочее направление:

- сравнение выполнять по явной лестнице сигналов;
- match report должен отражать, какой именно topology signal сработал;
- ambiguous outcome должен быть объяснимым оператору.

Базовая comparison ladder для дальнейшей проработки:

1. exact canonical path equality
2. exact leaf + parent chain equality
3. exact leaf + root + depth
4. ambiguous / no topology confirmation

Это даёт:

- более прозрачную отладку;
- меньше “магии” в disambiguation;
- лучшее качество explainability в diagnostics/reporting.

### 9. Нужен один симметричный canonicalization contract для source bootstrap, row-level lookup и target topology

Это один из главных незакрытых рисков корректности.

Если отдельно проектировать:

- source bootstrap normalization;
- row-level source topology lookup внутри `MatchStage`;
- target-side hierarchy label normalization;

то можно получить формально совместимые snapshots и при этом несовместимые
matching keys.

Предпочтительное решение:

- компилировать один `CompiledTopologyCanonicalizer` из `topology.yaml`;
- применять его одинаково к segment-level representation, а не к raw storage layout;
- не разрешать `match.yaml` переопределять canonicalization rules;
- фиксировать `topology_normalization_version` в metadata обоих snapshots.

Это означает следующее разделение:

- `topology.yaml` отвечает за:
  - hierarchy field mapping;
  - target label extraction mapping;
  - segment ordering;
  - canonicalization rules;
- `match.yaml` отвечает только за:
  - включение topology signal;
  - момент применения;
  - policy на missing topology;
  - comparison ladder.
- `resolve.yaml` должен отвечать за:
  - включение topology-backed link resolution;
  - target FK field (`organization_id` и аналоги);
  - policy на missing/ambiguous topology;
  - comparison ladder для resolve-side link decision.

Минимальный boundary shape стоит зафиксировать заранее, чтобы не оставить это
"додумыванием при реализации":

```python
class ResolveTopologyLinkSpec(DslBaseModel):
    enabled: bool = False
    field: str
    on_missing_topology: Literal["pending", "hard_error", "skip"] = "pending"
    on_ambiguous_topology: Literal["pending", "hard_error", "skip"] = "pending"
    comparison_ladder: list[str] = Field(default_factory=list)
```

И в `ResolveBlock`:

```python
topology_link: ResolveTopologyLinkSpec | None = None
```

Практический смысл такого shape:

- `field` жёстко привязывает topology-backed resolve к конкретному FK field;
- `on_missing_topology` и `on_ambiguous_topology` не смешиваются с legacy `on_unresolved`;
- `comparison_ladder` для resolve-side решения может эволюционировать независимо от match-side policy;
- `TopologyRequirementResolver` получает формальный сигнал из DSL, а не из ad-hoc Python wiring.

Это нужно не только для полноты DSL, но и для activation:

- `TopologyRequirementResolver` не должен смотреть только на `match.yaml`;
- он должен активировать bootstrap и при topology-aware match, и при topology-backed resolve link policy.

Симметрия должна обеспечиваться в трёх точках:

1. source bootstrap projection
2. row-level source topology locator в `MatchStage`
3. target hierarchy ingest / label normalization

Рабочий контракт:

```python
class CompiledTopologyCanonicalizer(Protocol):
    def canonicalize_segments(self, segments: tuple[str, ...]) -> tuple[str, ...]: ...
```

Почему это важно:

- исключает дрейф source/target matching contract;
- не протаскивает stage-specific logic в builder;
- оставляет `dependency_tree` нейтральным к DSL/storage layout;
- делает provenance и diagnostics проверяемыми.

Дополнительное уточнение:

- source path-ingest после `distinct canonical paths` считается acyclic-by-construction;
- target id-ingest требует отдельной cycle validation;
- shared canonicalizer не отменяет различие validator semantics для source и target.

### 10. Первый topology consumer в Phase 1 должен быть оформлен как MatchStage adapter, а не как “graph inside stage”

Да, практическая проблема именно в том, как stage будет использовать topology-derived
данные. Но правильная форма решения не “подключить graph к любой стадии”, а выделить
первого consumer-а и зафиксировать consumer boundary.

Для Phase 1a таким consumer-ом должен быть `MatchStage`.

Разделение ответственности:

- `dependency_tree`:
  - строит snapshot;
  - валидирует hierarchy;
  - хранит индексы;
  - отвечает на generic topology queries;
- `TopologyMatchService`:
  - интерпретирует topology signal для match use case;
  - принимает row-level source locator и target candidates;
  - возвращает topology evidence / refinement result;
- `MatchCore`:
  - не делает graph traversal сам;
  - не знает storage деталей snapshot;
  - вызывает topology consumer как дополнительный disambiguation step.

Предпочтительный flow:

```text
MatchCore
  -> existing identity/fuzzy candidate discovery
  -> build source topology locator from current row via CompiledTopologyCanonicalizer
  -> TopologyMatchService.compare(...)
  -> merge topology evidence into MatchDecision
```

Что это даёт:

- graph остаётся изолированным от stage internals;
- topology можно подключать к другим стадиям позже отдельными решениями;
- первый topology-aware use case получает чёткий consumer contract вместо “доступа к graph вообще”.

Но этот consumer boundary сам по себе не закрывает write-path для foreign key scenarios.

Если topology нашла соответствующий target org node, этого ещё недостаточно для
`plan/apply`, потому что downstream pipeline строится не из `MatchDecision`, а из
`ResolvedRow`, который затем сериализуется в `PlanItem`.

Следствие:

- topology evidence в `MatchDecision.meta` может использоваться для explainability;
- topology evidence в `MatchDecision.meta` не должно становиться каналом доставки final FK value;
- final topology-derived FK должен materialize-иться только через `ResolveStage`.

Рабочая модель write-path:

```text
source hierarchy columns
  -> source canonical path
  -> target topology path match
  -> topology-backed link resolution
  -> desired_state["organization_id"]
  -> ResolvedRow
  -> PlanItem
  -> plan.json
  -> apply
```

Это важно зафиксировать отдельно, чтобы не возникла ложная модель
"topology-aware match уже закрывает employee/org use case".

### 10a. Employee-like datasets требуют второго consumer-а в ResolveStage

Если primary entity pipeline — `organization`, topology-aware `MatchStage` действительно
может быть natural first consumer.

Если primary entity — `employee`, а `organization_id` является foreign key, topology нужна
в первую очередь не для match employee record, а для вычисления link-field value.

Поэтому для employee-like datasets нужно отдельно фиксировать:

- `MatchStage` — Phase 1a, tactical first consumer;
- `ResolveStage` — обязательный Phase 1b consumer для topology-backed link propagation.

Здесь важно не смешать две разные задачи:

- entity match: "кто эта запись в target?";
- FK resolution: "какой target organization id нужно записать в payload?".

Обе задачи могут использовать один и тот же topology runtime/provider, но не должны быть
смешаны в одном stage contract.

### 10b. Query API должен быть формальным contract-ом, а не "словари + prose"

`nodes_by_id / parent_by_id / children_by_id / roots` недостаточно фиксировать как набор
полей snapshot. Для stage-facing и consumer-level logic нужен отдельный `TopologyQueryPort`.

Минимальный baseline:

```python
class TopologyQueryPort(Protocol):
    def get_node(self, node_id: str) -> TopologyNode | None: ...
    def require_node(self, node_id: str) -> TopologyNode: ...
    def parent_id(self, node_id: str) -> str | None: ...
    def children_ids(self, node_id: str) -> tuple[str, ...]: ...
    def ancestors(self, node_id: str) -> tuple[str, ...]: ...
    def descendants(self, node_id: str) -> tuple[str, ...]: ...
    def path_to_root(self, node_id: str) -> tuple[str, ...]: ...
    def depth(self, node_id: str) -> int: ...
    def root_id(self, node_id: str) -> str: ...
    def canonical_path(self, node_id: str) -> tuple[str, ...]: ...
    def structural_signature(self, node_id: str) -> str: ...
```

Почему это блокер:

- comparison ladder без `canonical_path(...)` и `structural_signature(...)` остаётся prose-only;
- `MatchStage`/`ResolveStage` иначе начнут читать raw indices напрямую;
- builder/query responsibilities снова начнут смешиваться.

### 10c. Target-read seam должен быть отделён от readiness evaluator

`TopologyTargetReadinessEvaluator` оценивает состояние, но не должен подменять собой target
data access. Нужен отдельный `TopologyTargetReadPort`.

Минимальный baseline:

```python
class TopologyTargetReadPort(Protocol):
    def read_hierarchy(self, dataset: str) -> Iterable[TargetHierarchyRow]: ...
    def read_snapshot_metadata(self, dataset: str) -> TargetHierarchyReadMeta: ...
```

И `TopologyFreshnessPolicy`:

```python
class TopologyFreshnessPolicy(DslBaseModel):
    mode: Literal["none", "max_age", "revision_required"] = "none"
    max_age_seconds: int | None = None
    require_revision: bool = False
```

Это нужно, чтобы:

- topology builder читался через один cache seam;
- `cache_snapshot_revision` и `refreshed_at` имели определённый источник;
- freshness не оставалась "ссылкой на будущую policy без shape".

### 10d. Diagnostics topology должны жить в core catalog

`TOPOLOGY_*` не должны оставаться просто строками в документации.

Нужен baseline:

- `DiagnosticStage.TOPOLOGY_BOOTSTRAP`;
- `CatalogEntry(... -> SystemErrorCode -> severity)` для каждого `TOPOLOGY_*`;
- bootstrap short-circuit через обычный `CommandResult.primary_code()`, а не через отдельную exit-scale.

Это устраняет два риска:

- topology не обходит общую diagnostics taxonomy;
- bootstrap exit semantics остаются совместимыми с проектной stop/exit policy.

Минимальный row-level contract:

```python
@dataclass(frozen=True)
class SourceTopologyLocator:
    canonical_segments: tuple[str, ...]
```

Минимальный match-side service:

```python
class TopologyMatchService(Protocol):
    def compare(
        self,
        source_locator: SourceTopologyLocator,
        target_candidate_ids: tuple[str, ...],
    ) -> TopologyMatchResult: ...
```

При этом topology не должна заменять existing matcher.

Предпочтительная семантика:

- сначала обычный candidate discovery;
- topology применяется как refinement/disambiguation layer;
- topology-aware outcome должен быть explainable в diagnostics/reporting.

Это означает, что `MatchDecision`/`MatchedRow` должны нести по крайней мере:

- `topology_match_mode`
- `topology_reason`
- `topology_evidence`

Дополнительно имеет смысл заранее зафиксировать fail-fast rules:

- если `require_target_topology=True` и target snapshot пуст, bootstrap должен завершаться ошибкой;
- если target topology stale по freshness policy, это тоже bootstrap/readiness failure, а не тихий downgrade;
- topology-specific diagnostics должны жить в bootstrap boundary, а не растворяться в поздних match anomalies.

### 11. Target topology readiness лучше выделять в отдельный evaluator, а не размазывать по bootstrap builder и MatchStage

Проблема не в том, что target snapshot просто “может быть пустым”.

Проблема в том, что readiness decision использует сразу несколько классов фактов:

- snapshot вообще собран или нет;
- snapshot пустой или непустой;
- cache mirror свежий или stale;
- metadata source/target совместима или нет;
- topology capability обязательна для текущей команды или optional.

Если это размазать:

- частично в target builder;
- частично в runtime bootstrap orchestration;
- частично в `MatchStage`;

то получится неявная и труднотестируемая policy.

Предпочтительное решение:

- выделить `TopologyTargetReadinessEvaluator`;
- вызывать его после target snapshot build и до wire provider в pipeline;
- не делать readiness responsibility частью `TopologySnapshot`;
- не перекладывать readiness logic на topology consumer stage.

Минимальный вход evaluator-а:

- `target_snapshot`
- `TopologyBuildMetadata`
- cache status facts
- cache drift facts
- `require_target_topology`

Минимальный выход:

```python
@dataclass(frozen=True)
class TopologyTargetReadinessResult:
    is_ready: bool
    errors: tuple[DiagnosticItem, ...]
    warnings: tuple[DiagnosticItem, ...]
    details: Mapping[str, Any]
```

Почему это оптимально:

- соблюдает SRP;
- позволяет переиспользовать уже существующий cache vocabulary проекта;
- удерживает fail-fast decision в orchestration boundary, а не в graph/query domain;
- легко тестируется как чистый evaluator.

Предпочтительная policy matrix:

1. `required + snapshot missing` -> error
2. `required + snapshot empty` -> error
3. `required + stale target topology` -> error
4. `optional + degraded readiness` -> warning или capability skip по policy, но не silent success

Практический preventive guardrail:

- readiness evaluator не должен сам инициировать `cache refresh`;
- readiness evaluator только классифицирует состояние;
- mutating remediation остаётся отдельным use case.

### 12. Ingestion contract нужно жёстко разделить на builder ingress и trace envelope

Текущая двусмысленность возникает потому, что один DTO пытается одновременно быть:

- domain ingress contract;
- traceability envelope;
- diagnostics payload.

После `distinct canonical paths` это уже разные сущности.

Оптимальное решение:

- builder baseline = `SourceTopologyCanonicalPath`
- optional diagnostics envelope = `SourceTopologyProjectionTraceRow`

То есть:

```python
@dataclass(frozen=True)
class SourceTopologyCanonicalPath:
    canonical_segments: tuple[str, ...]


@dataclass(frozen=True)
class SourceTopologyProjectionTraceRow:
    row_ref: RowRef | None
    display_segments: tuple[str, ...]
    canonical_segments: tuple[str, ...]
```

Ключевая идея:

- domain builder не должен зависеть от row-level duplicate semantics;
- trace DTO не должен silently стать обязательным builder input;
- Polars adapter может держать trace side-channel отдельно от canonical batch.

Почему это эффективнее:

- builder contract остаётся маленьким и стабильным;
- dedup до builder становится естественным и безопасным;
- source-side path build ближе к `O(distinct paths)`;
- traceability не теряется, но перестаёт загрязнять domain ingress.

Превентивный guardrail:

- не делать builder метод с polymorphic входом “`canonical batch | trace rows`”;
- если нужен fallback для non-Polars adapter, он всё равно должен приводить данные к одному canonical batch contract.

### 13. Validator semantics source и target нужно фиксировать как сознательно асимметричные

Здесь важно не пытаться “выровнять” source и target искусственно.

Source ingest и target ingest реально разные:

- source: canonical path batch, parent derivation по prefix, cycles невозможны by-construction;
- target: explicit `node_id -> parent_id`, возможны missing parent, self-loop, cycle.

Лучшее решение для проекта:

- не один универсальный builder/validator;
- а два ingress-specific builder-а с общим snapshot assembly слоем.

Предпочтительная модель:

- `SourcePathTopologyBuilder`
- `TargetHierarchyTopologyBuilder`
- `TopologySnapshotAssembler`

Source-side validator должен проверять:

- empty path
- malformed segment sequence
- canonicalization conflicts
- duplicate canonical path policy

Target-side validator должен проверять:

- duplicate node ids
- missing parent
- self-loop
- cycle detection через `graphlib.TopologicalSorter`

Почему это оптимально:

- отражает реальные data contracts;
- не тащит лишнюю graph validation в source path ingest;
- не ослабляет target-side safety ради “общности”;
- лучше соответствует OOP/SRP и будущему unit testing.

Превентивные меры против новых проблем:

- общий слой должен начинаться только после ingress validation;
- shared code допустим в assembly/indexing/query, но не в ingest semantics;
- в документации и коде не использовать формулировку “source-agnostic builder”, если внутри остаются target-only checks.

### 14. Risk matrix для этих трёх решений

#### Риск: readiness policy расползётся по нескольким слоям

Последствие:

- inconsistent fail-fast behavior;
- трудно воспроизводимые match anomalies;
- смешение cache проблем и topology проблем.

Превентивный обход:

- отдельный readiness evaluator;
- отдельный bootstrap diagnostic stage;
- один decision point до pipeline materialization.

#### Риск: row-level trace снова станет обязательным builder input

Последствие:

- ломается `distinct canonical path` baseline;
- растёт число Python-объектов;
- builder начинает зависеть от trace semantics.

Превентивный обход:

- разделить domain ingress и diagnostics envelope;
- зафиксировать canonical batch как единственный baseline contract;
- отдельными тестами проверить, что builder принимает только canonical path objects.

#### Риск: универсальный builder размоет validator semantics

Последствие:

- source path ingest получает лишнюю сложность;
- target hierarchy validation становится неполной;
- документация и реализация расходятся.

Превентивный обход:

- два ingress builder-а;
- отдельные unit tests для source/target validation rules;
- общий код только после validated ingress boundary.

### 15. Metadata gap лучше закрывать usability-context, а не раздуванием provider port

Сама проблема валидная: `TopologyRunArtifacts` уже содержит metadata, а stage-facing
provider её не отдаёт.

Но прямое решение вида:

- `provider.get_metadata()`

в текущей архитектуре слабое, потому что:

- stage layer начнёт видеть orchestration/provenance policy;
- `MatchCore` или другие consumers быстро начнут самостоятельно интерпретировать freshness;
- provider превратится во второй runtime context carrier.

Предпочтительное решение:

- `TopologyProviderPort` остаётся snapshot-only;
- metadata остаётся внутри `TopologyRunArtifacts`;
- `TopologyTargetReadinessEvaluator` вычисляет readiness/usability;
- `TopologyMatchService` получает usability context как dedicated consumer input.

Это означает, что match-time degraded behavior можно выразить без утечки metadata в stage API.

Превентивные guardrails:

- не добавлять generic `get_metadata()` в provider на Phase 1;
- если позже появится второй реальный metadata consumer, выделить отдельный port,
  а не перегружать snapshot provider;
- `TopologyBuildMetadata` не должна хранить policy flags вроде `is_usable_for_match`.

### 16. Doc-completeness нужно понимать как semantic completeness, а не только наличие dataclass

После последних фиксаций `TopologyNode` и `TopologyBuildMetadata` уже определены рядом
с интерфейсами. Но этого недостаточно, если не описать их semantic boundary.

Что должно быть явно зафиксировано:

- `TopologyNode`:
  - node-level label + relation contract;
  - не место для derived query facts;
- `TopologyBuildMetadata`:
  - provenance/build facts;
  - не readiness state;
  - не stage-consumer policy object.

Почему это важно:

- иначе metadata и node contract начнут обрастать лишней operational семантикой;
- появится соблазн складывать туда `depth`, `root_id`, `is_stale`, `usable_for_match`
  и другие разнородные поля.

Превентивный guardrail:

- derived query facts держать в query layer;
- readiness держать в readiness result;
- provenance держать в metadata;
- не смешивать эти слои в одном dataclass.

### 17. Logging model сервиса: полная событийная модель + pluggable seam

Текущее логирование приложения слабое, и опираться на него нельзя. Фактическое состояние:

- `structlog` есть в зависимостях, но **не подключён**;
- `infra/logging/setup.py` — stdlib `logging`, плоский форматтер `runId=… comp=… msg=…`,
  единственная точка `log_event(logger, level, run_id, component, message)`;
- структурных полей всего два (`runId`, `component`) + свободный текст.

Принятое направление: **не мигрировать все слои сейчас**, а спроектировать полную событийную
модель topology за **одним инжектируемым seam**, который позже подключается к общей точке
логирования сменой одного адаптера.

Это не отменяет уже принятую observability-политику проекта:
[OBSERVABILITY-DEC-001](../adr/observability/OBSERVABILITY-DEC-001-structlog-as-standard.md)
фиксирует `structlog` как целевой стандарт для нового кода. Значит topology logging должен
сохранить forward-compatible seam: transitional legacy adapter сейчас, structured adapter потом.

#### Архитектура (один backend-seam, domain чист)

```
domain/dependency_tree/ports.py
    TopologyTracePort(Protocol)        # DEBUG node/path/cycle trace; default NullTopologyTrace (no-op)
usecases/topology/observability.py
    TopologyLogEvent(str, Enum)        # каталог событий (без ad-hoc строк)
    TopologyEventSink(Protocol)        # ЕДИНСТВЕННЫЙ seam: emit(level, event, **fields) + enabled(level)
    TraceToSink(TopologyTracePort)     # domain-trace -> sink.emit(DEBUG, ...)
infra/logging/topology_sink.py
    LegacyLogEventSink(TopologyEventSink)   # СЕГОДНЯ: transitional adapter, logfmt в message через log_event
    StructuredEventSink(TopologyEventSink)  # ПОТОМ: preferred adapter против общей structured-точки
```

Принципы:

- domain зависит только от `TopologyTracePort`-абстракции, не от logging backend (`lint-imports` зелёный);
- INFO-сводки логирует use-case из возвращённых builder-фактов; DEBUG-трассировка идёт через trace-порт;
- весь сервис пишет через `TopologyEventSink`; переезд на общую точку = новый адаптер + одна DI-строка.
- `LegacyLogEventSink` не становится новым стандартом логирования; это только временный мост к текущему runtime.

#### Сегодняшний рендеринг без правки общей модели

`comp` в текущей модели уже есть, поэтому topology получает namespace `comp=topology` сразу:

```
INFO runId=... comp=topology msg=event=topology.target.build.finish node_count=120 root_count=4 duration_ms=8 normalization_version=v1
```

#### Полная событийная модель

Важно: `TopologyLogEvent` — это **не второй diagnostics catalog**.

- `event` отвечает за observability category и greppable phase name;
- `diag_code` остаётся главным error key и должен совпадать с diagnostics/reporting taxonomy;
- если событие отражает ошибку, оно обязано нести уже существующий `diag_code`, а не придумывать параллельный error namespace.

**Bootstrap (orchestration)**

| event | lvl | поля |
|---|---|---|
| bootstrap.start | INFO | dataset, topology_dataset, require_source, require_target, activation_source |
| bootstrap.finish | INFO | duration_ms, built_sides, status(ok\|warn\|error), errors, warnings |
| bootstrap.skipped | DEBUG | reason=not_required |
| bootstrap.short_circuit | ERROR | diag_code, side |

**Spec + canonicalizer**

| event | lvl | поля |
|---|---|---|
| spec.loaded | INFO | spec_path, source_mode, target_mode, path_columns |
| spec.load_failed | ERROR | diag_code, spec_path |
| canonicalizer.compiled | INFO | ops_count, ops, normalization_version |
| canonicalize.op_applied | DEBUG | op, sample_in, sample_out (sampled) |

**Target build (cache adjacency)**

| event | lvl | поля |
|---|---|---|
| target.build.start | INFO | node_id_field, parent_id_field, target_label_field |
| target.read | DEBUG | rows_read, cache_table, cache_snapshot_revision |
| target.node_ingested | DEBUG·trace | node_id, parent_id, canonical_name |
| target.cycle_check | DEBUG | algo=graphlib, nodes, has_cycle |
| target.parent_missing | WARN/ERROR | node_id, parent_id, diag_code=TOPOLOGY_PARENT_MISSING |
| target.cycle_detected | ERROR | cycle_sample, diag_code=TOPOLOGY_CYCLE_DETECTED |
| target.build.finish | INFO | node_count, root_count, max_depth, duration_ms |

**Source build (polars projection)**

| event | lvl | поля |
|---|---|---|
| source.build.start | INFO | adapter=polars, path_columns |
| source.projection | DEBUG | rows_scanned, columns_selected, lazy=true |
| source.canonical_paths | INFO | raw_paths, distinct_paths, dropped_blank, collisions |
| source.path_ingested | DEBUG·trace | canonical_segments, synthetic_node_id, synthetic_parent_id |
| source.collision | WARN | canonical, display_variants, kept_display |
| source.build.finish | INFO | node_count, root_count, max_depth, duration_ms |

**Readiness**

| event | lvl | поля |
|---|---|---|
| readiness.evaluated | INFO | side=target, is_ready, decision, freshness_present, age |
| readiness.empty | ERROR | diag_code=TOPOLOGY_TARGET_EMPTY |
| readiness.stale | ERROR/WARN | diag_code=TOPOLOGY_TARGET_STALE, age, threshold, degraded |
| readiness.metadata_missing | WARN | degraded_to(warn\|error) |
| incompatible | ERROR | diag_code=TOPOLOGY_SOURCE_TARGET_INCOMPATIBLE, source_version, target_version |

**Provider wiring + Match consumer**

| event | lvl | поля |
|---|---|---|
| provider.wired | INFO | sides_available, stage_targets=[match] |
| provider.snapshot_not_available | ERROR | side, diag_code=TOPOLOGY_SNAPSHOT_NOT_AVAILABLE |
| match.enabled | INFO | apply_on, comparison_ladder, on_missing_topology |
| match.compare | DEBUG | row_ref, source_canonical_segments, target_candidates |
| match.resolved | DEBUG | row_ref, matched_target_id, mode(ladder rung), is_ambiguous, evidence_keys |
| match.ambiguous | DEBUG | row_ref, candidate_count |
| match.summary | INFO | compared, resolved, ambiguous, by_mode{exact_path,…} |

#### Политика уровней

- **INFO** — lifecycle-переходы + агрегаты (counts, duration, version, readiness decision, match summary), без per-row данных;
- **DEBUG** — per-node/per-path ingest, derivation synthetic id, per-op canonicalize sample, cycle-check, per-row match compare с рунгом ladder + evidence; только через trace-порт;
- **WARNING** — stale-degraded-to-warn, collision, malformed path, missing freshness metadata, `on_missing_topology=skip`;
- **ERROR** — фатальные bootstrap-диагностики → short-circuit.

#### Guardrails

- PII/объём: INFO — только агрегаты; DEBUG — нормализованные `canonical_segments`/synthetic id, сырые display-labels сэмплированно; для больших source — сэмплинг `source.path_ingested` + всегда агрегат `source.canonical_paths`;
- производительность: DEBUG-payload строится только при `enabled(DEBUG)` / no-op trace;
- diagnostics/reporting: события несут тот же `diag_code`; `match.summary`/`*.build.finish` — feed для reporting (§12), без дублирования источника метрик.

#### Точка стыковки с общей моделью

`TopologyEventSink` — контракт стыковки. Сегодняшняя точка интеграции —
`LegacyLogEventSink` поверх `log_event`; при доведении общей observability-модели по
`OBSERVABILITY-DEC-001` preferred adapter-ом должен стать `StructuredEventSink`.
Подключение к общей structured-точке позже = один адаптер + одна DI-строка, без изменений в
`domain/dependency_tree`, `usecases/topology` и match-service.

#### Console output / `--quiet` (оператор на экране)

Поправка терминологии: логи идут в `stdout`/`stderr`, не в `stdin`.

Текущее поведение по коду:

- `create_command_logger` вешает только `FileHandler` → логи (`log_event`) идут **только в файл**;
- оркестратор делает `sys.stdout = TeeStream(original_stdout, StdStreamToLogger(...))` →
  человекочитаемый вывод presenters **копируется в файл**, но логи на экран не льются.

То есть разделение «экран = presenters, файл = логи + копия экрана» уже есть и является
правильным default'ом. Вывод логов на терминал — это **opt-in зеркало**, а не поведение по умолчанию.

Две ортогональные оси (не сводить в один флаг):

1. verbosity human-вывода — `--quiet` (тихо = только ошибки на `stderr`);
2. зеркалирование логов на консоль — отдельный `--log-console` / `-v` со своим уровнем.

Правила:

- файл — всегда канонический полный лог, не зависит от флагов;
- экран оператора — presenters; зеркало логов по умолчанию выключено;
- зеркало логов — на `stderr` (чтобы не пачкать `stdout`/пайпы);
- precedence: CLI-флаг > config (`observability.*`) > default;
- `--quiet` никогда не глушит фатальные ошибки.

Обязательная защита от петли `TeeStream`:

- console-`StreamHandler` логов пишет в `original_stdout` / `original_stderr`
  (оркестратор их сохраняет), **в обход** теированного `sys.stdout`;
- иначе: log-record → `TeeStream` stdout → `StdStreamToLogger` → тот же logger →
  console-handler → … рекурсия;
- маршруты после фикса: presenters → теированный stdout → файл; логи → `original stderr` → экран.

Размещение и переиспользование:

- console-handler и ось `--quiet` вводятся сегодня в `create_command_logger` / runtime-слое как
  **общий механизм** (handler-concern), а не в topology;
- `TopologyEventSink` и сервис не меняются — они пишут в logger, а разводку по
  файл/консоль решают handlers;
- topology — лишь первый потребитель; при доведении общей модели логирования до единой
  этот же routing policy должен переехать в общую command logging bootstrap point без
  изменения topology seam.

### 18. Полная тест-матрица

Заземление в §9 проекта и testing-конвенциях: markers обязательны, `tmp_path` для I/O,
mock только на портах (Protocols), real SQLite/polars в integration, никаких prod-артефактов.
Domain builder/validator — **без моков** (чистые, кормим synthetic). Мокаем только порты.

#### Unit — domain (`dependency_tree`)

| ID | Target | Сценарий | Assert |
|---|---|---|---|
| U-D01 | TargetHierarchyTopologyBuilder | валидный adjacency `_ouid→parent_id` | snapshot nodes/parent/children/roots корректны |
| U-D02 | TargetHierarchyTopologyBuilder | self-loop `a→a` | diag `TOPOLOGY_CYCLE_DETECTED`, snapshot не собран |
| U-D03 | TargetHierarchyTopologyBuilder | cycle `a→b→a` | diag `TOPOLOGY_CYCLE_DETECTED` (graphlib) |
| U-D04 | TargetHierarchyTopologyBuilder | parent_id ∉ node space | diag `TOPOLOGY_PARENT_MISSING` |
| U-D05 | TargetHierarchyTopologyBuilder | duplicate node_id | diag `TOPOLOGY_DUPLICATE_NODE` |
| U-D06 | TargetHierarchyTopologyBuilder | forest (несколько roots) | `roots` содержит все корни |
| U-D07 | SourcePathTopologyBuilder | distinct canonical path batch | synthetic id и parent из prefix |
| U-D08 | SourcePathTopologyBuilder | acyclic-by-construction | cycle-валидация не требуется/не падает |
| U-D09 | SourcePathTopologyBuilder | пустой/blank path дошёл до builder | diag `TOPOLOGY_SOURCE_PATH_EMPTY`; тихого drop в builder нет |
| U-D10 | SourcePathTopologyBuilder | gap в уровнях (`L1,'',L3`) | malformed policy детерминирована |
| U-D11 | Snapshot | read-only | мутация snapshot/индексов невозможна |
| U-D12 | Query.path_to_root / ancestors | глубокая ветка | корректная цепочка, O(depth) |
| U-D13 | Query.depth / root_id | forest | верные depth/корень на каждой ветке |
| U-D14 | Query.canonical_path(node_id) | target node | canonical-сегменты пути (рунг «exact path») |
| U-D15 | Query.descendants | поддерево | полный набор потомков |
| U-D16 | Query.structural_signature | одинаковые/разные ветки | равные/разные сигнатуры |

#### Unit — canonicalizer & ids (критично)

| ID | Target | Сценарий | Assert |
|---|---|---|---|
| U-C01 | CompiledTopologyCanonicalizer | whitelist `trim/lower/compact/regex_replace` | посегментный канон корректен |
| U-C02 | symmetry | один canonicalizer к source-segments и target-labels | `canon(source)==canon(target)` для эквивалентных иерархий |
| U-C03 | dual-form | Polars-expr форма vs Python форма из одного rule-set | идентичный вывод (property-style) |
| U-C04 | canonicalizer | не-whitelist op | fail на загрузке (Pydantic), не runtime |
| U-C05 | synthetic id | один path → один id | детерминизм (golden sha256) |
| U-C06 | synthetic id | смена `normalization_version` | id меняется (versioned) |
| U-C07 | id | `hash()` не используется | стабилен между процессами (не PYTHONHASHSEED) |
| U-C08 | collision | разные display → один canonical | `kept_display` детерминирован + warn `collision` |

#### Unit — usecases (порты замоканы)

| ID | Target | Сценарий | Assert / Mock |
|---|---|---|---|
| U-U01 | TargetReadinessEvaluator | пустой target snapshot | `is_ready=False`, `TOPOLOGY_TARGET_EMPTY` |
| U-U02 | TargetReadinessEvaluator | stale + `require_target_topology=True` | `is_ready=False`, diag `TOPOLOGY_TARGET_STALE` |
| U-U03 | TargetReadinessEvaluator | freshness-метаданные отсутствуют + optional topology | warning/skip по policy, но не silent success |
| U-U04 | TopologyRequirementResolver | `mapping/normalize/enrich` | `require_*=False` |
| U-U05 | TopologyRequirementResolver | `match` + match-policy on | `require_target/source=True` |
| U-U06 | TopologyRequirementResolver | employees: link-policy on, match off | activation по link-policy (R3) = `True` |
| U-U07 | TopologyRequirementResolver | capability disabled в registry | `False` |
| U-U08 | TopologyMatchService.compare | exact canonical path | `mode=EXACT_CANONICAL_PATH`, matched id |
| U-U09 | compare | leaf+parent chain | `mode=EXACT_LEAF_PARENT_CHAIN` |
| U-U10 | compare | leaf+root+depth | `mode=EXACT_LEAF_ROOT_DEPTH` |
| U-U11 | compare | неуверенный рунг | `is_ambiguous=True`, evidence объясним |
| U-U12 | compare | mode/reason — enum | `TopologyMatchMode` (§10) |
| U-U13 | TopologyLinkResolutionService.resolve_link | source path → target FK | write-ready `resolved_target_id` |
| U-U14 | resolve_link | ambiguous / no match | `on_missing/on_ambiguous` policy |
| U-U15 | shared comparison core | match и link на одном входе | один target/рунг (DRY, нет дрейфа) |
| U-U16 | BootstrapUseCase | оба сайда ok | `artifacts`, `errors=()` |
| U-U17 | BootstrapUseCase | фатальная диагностика | `artifacts=None`, `errors≠()` |
| U-U18 | BootstrapUseCase | `topology_dataset=None` | нормализуется в `pipeline_dataset` (инв. 9) |
| U-U19 | observability | каждый lifecycle-шаг | recording-sink получил ожидаемые event+поля |
| U-U20 | observability | DEBUG off | `NullTopologyTrace` no-op, payload не строится |

#### Integration (real polars/SQLite, `tmp_path`)

| ID | Target | Сценарий | Assert |
|---|---|---|---|
| I-01 | ProjectionAdapter | real CSV org-уровни | distinct canonical paths, dropped_blank |
| I-02 | ProjectionAdapter | только path-колонки (lazy scan) | объектов ~ distinct, не rows |
| I-03 | ProjectionAdapter | 100k строк / N путей | результат = N путей |
| I-04 | TargetTopologyReader | real SQLite organizations | snapshot из adjacency, `cache_snapshot_revision` получен |
| I-05 | TargetReader+Readiness | пустая таблица | `TOPOLOGY_TARGET_EMPTY` fail-fast |
| I-06 | BootstrapUseCase | real source+cache | оба snapshot, provenance заполнена |
| I-07 | BootstrapUseCase | spec load по dataset name | грузит `topology.yaml` без full pipeline |
| I-08 | Provider wiring | inject в `StageExecutionContext` | `MatchStage` получает `TopologyProviderPort` |
| I-09 | Provider snapshot-only | стадия тянет metadata через provider | недоступно (инв. 24) |
| I-10 | LegacyLogEventSink | emit | `comp=topology`, logfmt; нет петли TeeStream (original stream) |
| I-11 | diagnostics catalog | все `TOPOLOGY_*` | зарегистрированы, верные SystemErrorCode/severity/stage |
| I-12 | reporting | bootstrap finish | `ReportContextKey.TOPOLOGY` с provenance один раз |
| I-13 | reporting | match summary | `by_mode` counts → report |

#### E2E (CliRunner) + write-path

| ID | Сценарий | Assert |
|---|---|---|
| E-01 | `import plan --dataset organizations` (1a) | exit 0; topology diag на bootstrap, не в середине pipeline |
| E-02 | organizations: одинаковые leaf в разных ветках | дизамбигуация по topology |
| E-03 | bootstrap fail (empty target, require=True) | ненулевой exit, handler не вызван, ошибка в report |
| E-04 | employees write-path (1b) | `organization_id` в `plan.json` через resolve-path |
| E-05 | dataset без capability | bootstrap не запускается |
| E-06 | `--quiet` | логи только в файл; фатал на `stderr` |
| E-07 | console mirror opt-in | зеркало на `stderr`, файл полный |

#### Architecture (import-linter)

| ID | Контракт |
|---|---|
| A-01 | `domain.dependency_tree` ∌ `polars` |
| A-02 | `domain.dependency_tree` ∌ `structlog`/logging backend (только `TopologyTracePort`) |
| A-03 | `domain.*` ∌ `infra`/`delivery` (расширить на topology) |
| A-04 | runtime topology ports в `domain/ports/topology`; domain-local trace seam допускается в `domain/dependency_tree/ports.py`; impl в infra/usecases |
| A-05 | Pydantic `BaseModel` topology — только DSL/spec, не runtime snapshot/query (инв. 15) |

#### Performance (excluded by default)

| ID | Сценарий | Метрика |
|---|---|---|
| P-01 | projection 100k rows / 500 distinct | время + число domain-объектов ≈ distinct (O(distinct)) |
| P-02 | target build на крупной иерархии | линейность по nodes |
| P-03 | DEBUG-trace off | накладные ≈ no-op |
| P-04 | `path_to_root`/`ancestors` глубокое дерево | O(depth), не O(nodes) |

#### Fixtures / helpers (conftest topology)

- `synthetic_hierarchy(...)` — генератор forest (id/parent_id) и path-batch с контролем глубины/ветвления/дублей;
- `canonical_paths(...)` — пары source-path ↔ target-label для symmetry-тестов;
- `fake_topology_provider`, `recording_event_sink`, `fake_cache_adjacency` — port-fakes;
- real CSV/SQLite в `tmp_path`; реальный YAML (organizations) — только в integration/e2e.

#### Критические корректностные тесты

U-C02/U-C03 (symmetry + dual-form), U-D02..D05 (target cycle/orphan/dup),
U-C05/C06 (id детерминизм/версионирование), U-U01..U03 (readiness fail-fast),
U-U06 (activation by link-policy), E-04 (write-path FK до `plan.json`).

#### CI-гейты

- merge: `pytest -m unit` + `-m integration` + `-m architecture` + `lint-imports` + `mypy`;
- PR: `-m e2e`;
- `-m performance` — отдельный nightly/manual.

## Stage G: source-side anchoring validation (обсуждение, 2026-06-02)

### Отправная точка: что уже сделано (E/F), а что нет

Сценарий «source-иерархия по именам → target-id для FK» **полностью закрыт Stage E/F** (row-level):

- employees source имеет колонки «Орг. единица уровня 1..5», маппятся в `organization_id`;
- `SourceTopologyLocatorBuilder` канонизирует значения этих колонок → source path из имён;
- target topology (organizations) строится из `_ouid/parent_id`, но каждый узел помечен
  канонизированным `name` (`target_label_field`), поэтому `canonical_path(_ouid)` — это
  цепочка имён;
- сравнение идёт имя-путь vs имя-путь (одни и те же canonicalization ops), matched-узел
  отдаёт `_ouid` → `organization_id`; одинаковые leaf-имена различаются полной цепочкой
  предков (`exact_canonical_path`);
- FK доходит до `plan.json` (`test_plan_resolve_topology_propagates_organization_fk_into_plan`).

Сопоставление id↔name, которое поначалу казалось отдельной задачей, решается **неявно**:
target хранит канонизированное `name` на каждый id-узел, сравнение — по именам, на выходе — id.

Вывод: **Stage G — это НЕ про FK-matching** (он готов), а про отдельную потребность —
валидацию целостности source-иерархии для self-referential id/parent_id датасетов.

### Оценка применимости row-level модели

Row-level FK-by-canonical-path — правильный дефолт для частой формы ETL («в source иерархия
как имена/уровни, в target — граф id»): потоковый, stateless-per-row, без буферизации,
переносимый на любой датасет такой формы. Принципиальная граница: row-level **не** рассуждает
о собственном графе source через несколько строк. Это ровно и есть зона Stage G. Модели
комплементарны и разделение принципиальное.

### Скорректированное правило валидности (target — авторитет)

dependency_tree держит **два независимых набора правил**:

- **target-build** (из cache): target авторитетен, принимаем как есть, свои валидаторы
  (duplicate/cycle/parent_missing). `cache refresh` — НЕ точка отсечения source-данных.
- **source-validation** (из source-батча): якорим **против target**, отсекаем незаякоренные.

Source-запись (organizations из `source_departments.csv`, id/parent_id) **заякорена**, если
при подъёме по `parent_id`:

- доходит до корня (`parent_id` пустой), **или**
- доходит до id, существующего в **target**, **или**
- проходит через родителя, который есть в этом же **source-батче** и сам заякорен,

…не упираясь в id, которого нет ни в source, ни в target. Множество якорей =
`source_ids ∪ target_ids`.

### Ключевое различие: forward-reference vs permanently-unanchorable

Stage G разделяет два случая, которые иначе сливаются:

- **forward-reference** (потомок в source раньше родителя, но родитель есть в батче/target) —
  НЕ ошибка; ordering закрывает **существующий pending-механизм resolver'а**. Stage G сюда
  не лезет и pending не дублирует.
- **permanently-unanchorable** (родитель `378` отсутствует и в source, и в target) — запись
  никогда не построит иерархию; создавать doomed-pending бессмысленно → **отсекаем рано**,
  вместе со **всем поддеревом** (потомки незаякоренного узла тоже не попадут в target).

Пример: `382;Линейно-эксплуатационная служба;378`, где `378` нет ни в source, ни в target →
`382` и все его потомки отсекаются.

### Зафиксированные ответы

1. in-batch parent — валиден (reachability через заякоренных in-batch родителей); ordering
   отдаётся pending'у resolver'а.
2. Полный `hard_error` в кейсе organizations **не нужен**, но нужна **вариативность**: политика
   `on_unanchored: skip | warn | hard_error` per-dataset. organizations — `skip` с ERROR-видимой
   диагностикой.
3. Отсечение — **pre-pass до основного пайплайна** organizations (Polars читает source →
   source-snapshot → anchoring против target → set невалидных id → основной `import plan`
   фильтрует строки на входе).
4. employees source-validation **не нужна** (там name-path FK-matching, Stage E/F).
5. `organizations.topology.yaml` `source.mode` должен быть `adjacency_list` (текущий
   `path_columns` — illustrative и неверен для реальных id/parent_id данных); `on_unanchored`
   живёт под `source:`.
6. Активация — для команд, доходящих до Resolve/Plan (где FK/parent реально резолвятся).

Здесь же `require_source_topology` **наконец становится `True`** (для organizations import) —
закрывает High 2 из ревью Stage D (где он был выставлен в `False` для Phase 1a/1b).

### Диагностика и наблюдаемость

- новый catalog-код `TOPOLOGY_SOURCE_UNANCHORED` (`DATA_INVALID`, ERROR);
- per-row diagnostics + TOPOLOGY-контекст со счётчиком отсечённых → логи и отчёт (трассируемость).

### Зафиксированный domain contract anchoring (2026-06-02)

**Принцип:** DTO и domain-функция — **dataset-agnostic**. Конкретику (`id`/`code`/`_ouid`/
`organization_id`, имена колонок) знают только topology-spec и infra-адаптеры; domain их не
видит. Наш случай — проверка применимости, не форма контракта.

**id-space (для organizations):** anchoring идёт по бизнес-id (source `id` = target `code`),
**exact-match** — это отличие от E/F (там сравнение по канонизированным именам). Множество
якорей = `{source id-ов батча} ∪ {target codes}`. Anchoring'у нужен **набор target-ключей**
(плоское membership из cache по spec-настроенному полю), **а не** `_ouid`-tree снапшот Stage C.
В domain это абстрактный `frozenset[str]` — без знания, что это «code».

**DTO (domain/dependency_tree, generic):**

```python
@dataclass(frozen=True)
class SourceAdjacencyNode:
    node_id: str            # exact business id в abstract id-space; ключ anchoring
    parent_id: str | None   # None = корень
    label: str              # только для текста диагностики

@dataclass(frozen=True)
class SourceAnchoringVerdict:
    node_id: str
    reason: str               # "missing_parent" | "unanchored_subtree" | "cycle"
    broken_at_parent_id: str | None

@dataclass(frozen=True)
class SourceAnchoringResult:
    anchored_ids: frozenset[str]
    dropped: Mapping[str, SourceAnchoringVerdict]   # только отсечённые

def anchor_source_nodes(
    nodes: Iterable[SourceAdjacencyNode],
    *,
    target_ids: frozenset[str],
) -> SourceAnchoringResult: ...
```

- **row_ref в DTO НЕТ** — anchoring работает над графом в id-space, не над строками;
- **dropped subtree формируется в domain-функции** через reachability (мемоизированный подъём,
  cycle-guard); потомок незаякоренного предка → `unanchored_subtree`, `broken_at_parent_id` =
  исходный сломавший id;
- `target_ids` — абстрактный `frozenset[str]`, без dataset-семантики.

**Связывание dropped ↔ source rows (Option A):**

- pre-pass отдаёт только `SourceAnchoringResult` (node_id-keyed) + агрегат для report-контекста,
  **без per-row диагностик** и **без row_ref**;
- основной поток organizations: тонкий фильтр **после Map** (где есть `code` = node_id); строки
  с `code ∈ dropped` → `TransformResult(row=None, errors=[TOPOLOGY_SOURCE_UNANCHORED …,
  record_ref=<row_ref ЭТОЙ строки>])`; заякоренные — pass-through;
- через границу едет только node_id-keyed map (детерминированно, без зависимости от
  порядка/dedup Polars) → диагностика эмитится **один раз**, с **собственным row_ref** потока,
  без рассинхрона line_no/record_id между двумя чтениями source.

**Граница ответственности:** pre-pass = граф (id-space), основной поток = строки (row_ref +
reporting). Общение — только через множество id + вердикты.

**Дубликаты node_id** — **ортогональный валидатор** (`TOPOLOGY_DUPLICATE_NODE`, своя политика),
не смешивается с anchoring-фильтром (anchoring keying по node_id корректен при уникальных id).
