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
  - `target_topology`
  - `source_topology`
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

Runtime wiring должно оперировать не "источником истины", а **именованными topology snapshot**.

Например:

- `target_topology`
- `source_topology`

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

- topology data provider port
- либо topology snapshot provider port

### Infra

- cache-backed topology provider
- позже source-backed topology provider

### Delivery / runtime orchestration

- explicit snapshot build step before stage chain, если topology требуется pipeline run
- или lazy singleton provider с eager build-on-first-use semantics и documented lifecycle

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

Runtime должен оперировать **именованными topology snapshot**, а не одним жёстко зашитым "источником истины".

Базовая модель:

- `target_topology`
- `source_topology`

Это позволяет:

- использовать разные topology contexts для разных задач;
- не смешивать target reality и source-side hierarchy;
- расширять систему без изменения domain API дерева.

### Decision 10

Если topology должна использоваться стадиями во время обычного streaming pipeline, то соответствующий snapshot должен быть **полностью построен до того, как первый record дойдёт до этих стадий**.

Следствие:

- topology build не встраивается как скрытая побочная логика внутрь обычного `Extract -> Map -> Normalize -> ...` потока;
- source-backed topology для Phase 1 допускается только через отдельный pre-pass или отдельный topology source;
- попытка "постепенно достраивать" topology по ходу stream не считается корректной моделью для query-driven stage logic.

### Decision 11

Для **Phase 1** недостаточно только `cache-backed target topology`.

Чтобы решить основной practical use case topology-aware matching, Phase 1 должен поддержать две стороны сопоставления:

- `target_topology` — snapshot по cache mirror target-системы;
- `source_topology` или эквивалентное source-side topology representation — на основе source hierarchy.

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
- collector в конце materialize-ит `source_topology`.

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

1. Сначала прогнать topology pre-pass до конца и построить `source_topology`
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
5. build `source_topology`
6. основной planning pipeline стартует отдельно с готовыми `source_topology` и `target_topology`

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
- строит `source_topology`;
- сохраняет готовый snapshot в run-scoped context;
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
3. строит `source_topology`
4. параллельно или заранее получает `target_topology`
5. сохраняет оба snapshot в run-scoped context
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
   - как передаёт snapshot в run-scoped context;
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

Предпочтительно использовать именованный runtime container, а не передавать отдельно `source_topology` и `target_topology`.

Пример:

```python
@dataclass(frozen=True)
class TopologyRuntime:
    snapshots: Mapping[str, TopologySnapshot]

    def get(self, name: str) -> TopologySnapshot: ...
    def has(self, name: str) -> bool: ...
```

Базовые имена snapshots:

- `source_topology`
- `target_topology`

### Утверждённый DI placement

Зафиксировано решение:

- topology slot объявляется в `AppContainer`;
- `PipelineContainer` читает topology через dependency от `AppContainer`;
- это run-scoped dependency slot, который заполняется после bootstrap и до вызова handler.

Причина выбора:

- bootstrap выполняется на уровне runtime orchestration, а не внутри pipeline;
- topology artifact может понадобиться не только stage wiring, но и другим run-scoped runtime consumers;
- при этом `PipelineContainer` остаётся потребителем, а не владельцем topology runtime.

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
    runtime: TopologyRuntime | None
    errors: tuple[DiagnosticItem, ...]
    warnings: tuple[DiagnosticItem, ...]
```

Утверждённое уточнение:

- `TopologyBootstrapResult` не использует один общий tuple `diagnostics`;
- bootstrap boundary явно разделяет:
  - `errors`
  - `warnings`
- при наличии фатальных ошибок bootstrap result должен содержать `runtime=None`.

Семантика:

- `errors` => bootstrap прерывает дальнейший handler path;
- `warnings` допустимы вместе с валидным `runtime`;
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

Базовый DTO для `Phase 1`:

```python
@dataclass(frozen=True)
class SourceTopologyProjectionRow:
    row_ref: RowRef | None
    path_segments: tuple[str, ...]
```

Причины выбора:

- `row_ref` нужен для diagnostics и traceability bootstrap path;
- `path_segments` — минимальный стабильный контракт для domain builder;
- projection layer не должен вычислять synthetic node ids или parent ids;
- projection layer не должен протаскивать raw source rows в domain.

Что делает projection layer:

- читает source через canonicalized bootstrap path;
- выбирает только topology-relevant hierarchy fields;
- нормализует значения сегментов пути;
- отбрасывает пустые сегменты;
- отдаёт `tuple[str, ...]`.

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
  -> open source reader
  -> iterate raw source rows
  -> projection mapper
  -> topology path normalizer
  -> SourceTopologyProjectionRow stream
  -> SourceTopologyBuilder
  -> TopologySnapshot
```

Что уже считается принятым:

- bootstrap orchestration получает уже normalized `TopologyBootstrapRequest`;
- source access path должен переиспользовать тот же source reader contract, что и основной runtime;
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

Source topology bootstrap использует тот же source access path, что и основной ETL runtime.

Утверждено:

- не создавать отдельный ad-hoc CSV parser;
- reader не знает про topology semantics;
- reader только отдаёт raw source rows в projection flow.

#### 3. Projection mapper

Projection mapper — отдельная логическая ответственность внутри bootstrap flow.

Он:

- выделяет topology-relevant hierarchy values;
- не строит graph;
- не вычисляет synthetic ids;
- не обязан быть полноценной main-pipeline stage.

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

После normalize flow отдаёт:

```python
@dataclass(frozen=True)
class SourceTopologyProjectionRow:
    row_ref: RowRef | None
    path_segments: tuple[str, ...]
```

Инварианты:

- `path_segments` уже canonicalized;
- blank segments уже removed;
- `node_id` / `parent_id` ещё не вычислены.

#### 6. Domain builder ingestion

`SourceTopologyBuilder` получает поток `SourceTopologyProjectionRow` и уже внутри domain делает:

- synthetic node id generation;
- parent derivation from path prefixes;
- duplicate path aggregation;
- graph-level diagnostics;
- snapshot assembly.

Утверждённый вывод:

- builder — первый слой, который знает graph semantics;
- projection path не должен знать policy synthetic key derivation.

#### 7. Streaming and buffering model

`reader -> projection mapper -> topology path normalizer -> projection row emission` должен оставаться lazy/streaming path.

`SourceTopologyBuilder` — допустимо stateful terminal step, который буферизует topology state на весь bootstrap pass.

Причина:

- topology graph нельзя построить без накопления topology state;
- buffering разрешён, если он локализован в builder и явно осознан как part of bootstrap lifecycle.

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
- topology normalization должна оставаться узкой и дешёвой, а не вырождаться во второй `NormalizeStage`.

### Как ограничивать дублирование

Согласовано следующее направление:

- topology normalizer использует узкий whitelist deterministic ops;
- topology normalization rules описываются отдельно и явно;
- они не обязаны совпадать 1:1 с полным `NormalizeStage`;
- цель — не убрать дублирование любой ценой, а не дать ему расползтись в полноценный второй transform flow.

### Куда передавать результат

Предпочтительно не класть topology напрямую в mutable `PipelineRunContext`, а передавать её как capability/provider path:

- через `StageExecutionContext`;
- или через capability registry/provider gateway.

Причина:

- topology snapshot — это read-only runtime capability;
- концептуально она ближе к execution context, чем к mutable per-run mechanics.

Утверждённое уточнение:

- stages не получают `TopologyRuntime` напрямую;
- stages получают узкий `TopologySnapshotProviderPort`;
- `TopologyRuntime` остаётся внутренним run-scoped artifact.

Причины:

- слабее связность stage API;
- `TopologyRuntime` может эволюционировать без влияния на stages;
- это лучше соответствует hexagonal pattern проекта.

Утверждённый provider contract:

```python
class TopologySnapshotProviderPort(Protocol):
    def has(self, name: TopologySnapshotName) -> bool: ...
    def get(self, name: TopologySnapshotName) -> TopologySnapshot: ...
```

Дополнительно принято:

- использовать `TopologySnapshotName`, а не raw strings;
- `get(...)` должен выбрасывать typed exception `TopologyNotAvailableError`, если snapshot не доступен;
- optional stages используют `has(...)` + `get(...)`, а не `None`-based contract.

Пример:

```python
class TopologySnapshotName(str, Enum):
    SOURCE = "source_topology"
    TARGET = "target_topology"


class TopologyNotAvailableError(Exception):
    def __init__(self, name: TopologySnapshotName) -> None: ...
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

### Working conclusion

Предпочтительный runtime integration contract:

- не строить topology в `PlanningPipeline.open()`;
- не делать lazy build on first use;
- использовать hybrid model:
  - runtime step владеет lifecycle;
  - bootstrap service/use case владеет построением;
  - стадии читают только capability.

Дополнительно утверждено:

- override topology dependency выполняется после успешного bootstrap и до `bind_context_with_container()` / `handler()`;
- bootstrap request должен различать:
  - `pipeline_dataset`
  - `topology_dataset: str | None`
- bootstrap failures short-circuit handler execution и должны маппиться в тот же report/runtime boundary, что и другие pre-handler failures.
