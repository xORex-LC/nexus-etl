# TRANSFORM-PROBLEM-011: Dependency tree topology runtime integration

> **Статус**: Решена в TRANSFORM-DEC-010
> **Дата создания**: 2026-05-28
> **Затронутые компоненты**: `PlanningPipeline`, `StageExecutionContext`, `dependency_tree`

---

## 📋 Контекст

В проекте появилась потребность использовать topology-aware обработку данных в ETL pipeline. Речь идёт о случаях, когда простого сравнения значений полей недостаточно, и требуется учитывать положение сущности в иерархии.

Пример целевого use case:
> В source hierarchy подразделения приходят как набор строковых уровней (`Орг. единица уровня 1`, `Орг. единица уровня 2`, ...), а в target hierarchy те же сущности представлены через `organization_id` и cache mirror. Для корректного matching недостаточно leaf name; нужно сравнивать topology source path и target path.

Проект уже использует streaming planning pipeline:
> `Extract -> Map -> Normalize -> Enrich -> Match -> ResolveContext -> Resolve`

При этом topology может понадобиться уже в `enrich`, `match` и `resolve`, то есть достаточно рано в lifecycle run.

---

## ⚠️ Проблема

В проекте отсутствует зафиксированная runtime-модель для построения и предоставления `dependency_tree` / topology snapshots.

Нужно определить:
- в какой момент при запуске приложения строится graph;
- из каких источников он строится;
- где заканчивается build topology artifacts/provider и где начинается их wiring в pipeline stages;
- как это сделать без нарушения streaming-контракта основного ETL pipeline.

Без этого невозможно корректно внедрить topology-aware matching/disambiguation и другие сценарии, использующие иерархию.

---

## 🔍 Симптомы

- **Симптом 1**: matching по одному `name` недостаточен для подразделений с одинаковыми названиями в разных ветках hierarchy
- **Симптом 2**: неясно, можно ли безопасно строить topology внутри текущего streaming pipeline без hidden buffering
- **Симптом 3**: source и target представляют hierarchy в разных формах, поэтому одной target-side topology недостаточно
- **Симптом 4**: pre-run проверки и bootstrap work уже существуют, но распределены между `app.py`, `runtime/orchestrator.py`, container init и handler-level code
- **Симптом 5**: нет явной именованной pre-handler sequence, в которую можно безопасно встроить optional topology bootstrap без переписывания всего startup lifecycle
- **Симптом 6**: не зафиксировано, должен ли source-side bootstrap идти через тот же row-by-row reader path, или допустим отдельный topology-specific projection adapter

---

## 📊 Масштаб проблемы

- **Частота**: Всегда для topology-aware use cases
- **Критичность**: Высокая
- **Затронуто**: `enrich`, `match`, `resolve`, runtime orchestration, будущая Initialization Phase

---

## 🧪 Как воспроизвести

1. Подготовить source dataset, где hierarchy подразделения представлена строковыми уровнями пути
2. Подготовить target/cache hierarchy, где те же подразделения представлены `organization_id`
3. Попробовать выполнить matching только по leaf name или отдельным полям без topology snapshot
4. **Ожидаемый результат**: pipeline способен однозначно сопоставить подразделение по topology-aware сигналу
5. **Фактический результат**: без source-side topology signal и target-side topology snapshot matching остаётся неоднозначным

---

## 🚫 Почему это проблема?

- Невозможно надёжно сопоставлять подразделения с одинаковыми названиями
- Невозможно использовать hierarchy как сигнал в `enrich`, `match` и `resolve`
- Любая попытка собрать topology "по пути" рискует скрыто сломать streaming contract
- Без явного lifecycle graph build будет размазан между слоями и плохо диагностироваться
- Без явного разделения `build pre-handler / wire in handler` topology integration конфликтует с текущей точкой materialization dataset-specific pipeline
- Без отдельного решения по source-side projection непонятно, как минимизировать стоимость repeated read и не превратить bootstrap во второй object-level transform flow

---

## 💡 Возможные решения (обсуждение)

> Этот раздел может содержать первоначальные идеи до принятия финального решения

### Вариант 1: Lazy build on first use
- **Идея**: Строить topology только при первом запросе к capability
- **Плюсы**: Нет startup cost, если topology не используется
- **Минусы**: Скрытый lifecycle, неявная latency, source-backed build всё равно превращается в скрытый pre-pass

### Вариант 2: Incremental build внутри основного pipeline
- **Идея**: Постепенно собирать graph во время обычного streaming pass
- **Плюсы**: Теоретически одно чтение source
- **Минусы**: topology не готова для ранних stage queries, появляется hidden buffering/barrier

### Вариант 3: Отдельный bootstrap pass до основного pipeline
- **Идея**: Сначала построить source topology snapshot / target topology snapshot, затем запускать основной pipeline
- **Плюсы**: Явный lifecycle, готовый snapshot до начала stage processing, не ломает streaming contract
- **Минусы**: Дополнительное чтение source, отдельный orchestration step, всё ещё нужно отдельно решить pre-handler build vs handler-scope wiring

### Вариант 4: Общая Initialization Phase приложения
- **Идея**: Формализовать уже существующие preflight/resource-init шаги как явную pre-handler sequence и добавить в неё optional bootstrap slot
- **Плюсы**: Целостная архитектура startup/readiness без обязательного greenfield framework; естественное место для topology bootstrap diagnostics
- **Минусы**: Всё равно требует аккуратно разделить build topology до handler и wiring topology provider внутри handler; при чрезмерном обобщении может затянуть внедрение topology feature

### Дополнительное ограничение: source-side projection boundary
- **Наблюдение**: topology bootstrap использует только hierarchy-related subset source данных, а основной source reader path остаётся row-oriented
- **Проблема**: если жёстко привязать topology bootstrap к тому же reader implementation, repeated read легко превращается во второй Python object flow
- **Следствие**: problem statement должен допускать отдельный topology-specific projection adapter в `infra/`, если он лучше сохраняет streaming-инварианты основного pipeline и упрощает bootstrap

---

## 🔗 Связанные документы

- [Dependency Tree Worknote](../../notes/dependency-tree/DEPENDENCY_TREE_WORKNOTE.md)
- [Документация слоя](../../dev/INDEX.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-05-28 | Проблема зафиксирована |
| 2026-05-31 | Уточнены problem constraints: initialization sequence, build-vs-wire split и source-side projection boundary |
| 2026-05-28 | Решение принято в [TRANSFORM-DEC-010](./TRANSFORM-DEC-010-topology-bootstrap-before-main-pipeline.md) |
