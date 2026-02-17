# DSL-PROBLEM-004: Неконсистентная compile-архитектура transform стейджей

> **Статус**: Решена в DSL-DEC-004
> **Дата создания**: 2026-02-17
> **Затронутые компоненты**: `connector/domain/transform/mapping/mapper_dsl.py`, `connector/domain/transform/normalize/normalizer_dsl.py`, `connector/domain/transform/enrich/enricher_dsl.py`, `connector/domain/transform/matcher/match_dsl.py`, `connector/domain/transform/resolver/resolve_dsl.py`
> **Созависимая проблема**: [DSL-PROBLEM-003](./DSL-PROBLEM-003-dsl-core-mixed-responsibilities.md)

---

## 📋 Контекст

Каждый transform stage имеет `*_dsl.py` — компилятор, который принимает DSL Spec (Pydantic)
и производит из неё runtime-артефакт для `*_core.py`. Этот паттерн появился органически:
каждый стейдж решал свои задачи, и компилятор проектировался под специфику стейджа.

При проектировании миграции DSL Core (DSL-PROBLEM-003) встал вопрос: куда переезжают
`*_dsl` компиляторы? Ответ зависит от того, что они производят — runtime-объект или
data-only артефакт. Анализ показал три разных паттерна.

---

## ⚠️ Проблема

Пять transform стейджей используют три разных compile-паттерна:

### Паттерн 1: DSL → Core (runtime-объект)

**Mapping** и **Normalize** — компилятор создаёт Core напрямую:

```
MapperDsl.compile(MappingSpec, engine, sink_spec, options)  →  MapperCore
NormalizerDsl.compile(NormalizeSpec, catalog, sink_spec, row_builder, options)  →  NormalizerCore[T]
```

Проблема: `*Dsl` создаёт runtime-объект. Это означает, что DSL-компиляция и runtime-инстанцирование
неразделимы. Компилятор не может жить в DSL-слое, потому что знает о Core.

### Паттерн 2: DSL → Data-only spec

**Enrich** и **Match** — компилятор создаёт промежуточную data-структуру:

```
EnricherDsl.compile(EnrichSpec, registry, options)  →  EnricherSpec (data)
MatchDsl.compile(MatchSpec, options)  →  MatchingRules (data)
```

Core конструируется отдельно: `EnricherCore(spec)`, `MatchCore(rules, ...)`.
Здесь граница "DSL compilation" vs "runtime execution" чёткая.

### Паттерн 3: DSL → Callable rules

**Resolve** — компилятор создаёт набор callable-ов:

```
ResolveDsl.compile(ResolveSpec, sink_spec, options)  →  CompiledResolveRules {
    build_desired_state: Callable,
    build_source_ref: Callable,
    diff_policy: Callable,
    merge_policy: Callable,
    ...
}
```

Формально data-only, но содержит замыкания — промежуточный вариант.

### Дополнительные неконсистентности

| Аспект | Map | Normalize | Enrich | Match | Resolve |
|--------|-----|-----------|--------|-------|---------|
| Compile output | Core instance | Core instance | EnricherSpec | MatchingRules | CompiledResolveRules |
| Использует dsl-core engine | Да | Да | Да | **Нет** | **Нет** |
| Generic types | — | [T] | [T, D] | — | — |
| Файлов в стейдже | 3 | 3 | 8 | 8 | 4 |
| Именование выхода | *Core | *Core | *Spec | *Rules | Compiled*Rules |

---

## 🔍 Симптомы

- **Симптом 1**: Нельзя единообразно ответить "что производит DSL-компилятор?" — ответ зависит от стейджа.
- **Симптом 2**: При попытке вынести `*_dsl.py` в отдельный DSL-модуль (DSL-PROBLEM-003), Map и Normalize тянут зависимость на Core (обратная стрелка).
- **Симптом 3**: Enrich и Match уже следуют чистому паттерну (data → Core), но это не кодифицировано как стандарт — выглядит как случайность.
- **Симптом 4**: Новый стейдж не имеет чёткого образца: какому из трёх паттернов следовать?
- **Симптом 5**: `*_engine.py` в Map/Normalize дублирует минимальную обвязку, потому что Core уже создан в *Dsl. В Enrich/Match engine делает значимую работу — создаёт Core из compiled data.

---

## 📊 Масштаб проблемы

- **Частота**: Постоянно — каждый стейдж демонстрирует свой вариант.
- **Критичность**: Средняя (стейджи работают корректно) → Высокая (при масштабировании на новые ETL-процессы).
- **Затронуто**: Transform DSL компиляторы, будущие стейджи, архитектурная консистентность проекта.

---

## 🧪 Как воспроизвести

1. Попробовать определить единый интерфейс для `*Dsl.compile()`.
2. Обнаружить, что Map/Normalize возвращают Core (runtime), а Enrich/Match — data.
3. Попробовать вынести `MapperDsl` в `transform_dsl/compilers/` (DSL-PROBLEM-003).
4. **Ожидаемый результат**: Компилятор производит data-only результат, не зависит от Core.
5. **Фактический результат**: `MapperDsl.compile()` напрямую конструирует `MapperCore` — зависимость на runtime-слой.

---

## 🚫 Почему это проблема?

- Блокирует чистое разделение DSL-слоя и runtime-слоя (DSL-PROBLEM-003 не решается полностью без стандартизации compile output).
- Отсутствие единого compile-контракта делает добавление новых стейджей непредсказуемым.
- Затрудняет тестирование: для Map/Normalize нужно создавать Core (с зависимостями) даже чтобы проверить DSL-компиляцию.
- Нарушает принцип наименьшего знания: DSL-компилятор не должен знать, как конструируется runtime-объект.

---

## 💡 Возможные решения (обсуждение)

### Вариант 1: Стандартизировать compile → data-only (Вариант C из обсуждения)

- **Идея**: Все `*Dsl.compile()` возвращают **frozen data-only** объект (`CompiledMapRules`, `CompiledNormalizeRules`, ...). `*Core` конструируется из compiled rules в `*Engine` или конструкторе Core.
- **Плюсы**: Единый контракт. Компилятор не зависит от Core → может жить в DSL-слое. Compile output тестируется отдельно от runtime.
- **Минусы**: Рефакторинг Map и Normalize (сейчас Dsl→Core напрямую). Для Resolve callable-ы в compiled rules — нюанс (формально data, фактически замыкания).

### Вариант 2: Оставить *Dsl в transform/, стандартизировать только naming

- **Идея**: Не выносить компиляторы в DSL-слой, но стандартизировать naming: `*Dsl.compile()` → `Compiled*Rules` (или *Spec) для всех стейджей. Core создаётся из них.
- **Плюсы**: Минимальные структурные изменения. Map/Normalize рефакторятся локально.
- **Минусы**: Компиляторы остаются в двух мирах (импортируют из DSL-слоя, живут в transform/).

### Вариант 3: Не стандартизировать — различия оправданы доменной спецификой

- **Идея**: Map/Normalize достаточно просты, чтобы компилировать сразу в Core. Enrich/Match/Resolve сложнее — промежуточный слой оправдан. Это не баг, а feature.
- **Плюсы**: Нет рефакторинга.
- **Минусы**: Не решает проблему разделения DSL/runtime слоёв, затрудняет масштабирование.

---

## 🔗 Связанные документы

- [DSL-PROBLEM-003](./DSL-PROBLEM-003-dsl-core-mixed-responsibilities.md) — созависимая проблема (разделение DSL Core)
- [DSL-DEC-002](./DSL-DEC-002-modular-dsl-core-and-contract-stabilization.md) — предыдущее решение
- [DSL-DEC-004](./DSL-DEC-004-standardized-compile-contract.md) — решение

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-17 | Проблема зафиксирована при анализе compile-паттернов стейджей |
| 2026-02-17 | Решение принято в DSL-DEC-004 |
