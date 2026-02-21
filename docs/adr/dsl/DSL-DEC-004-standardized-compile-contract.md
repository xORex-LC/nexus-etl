# DSL-DEC-004: Стандартизированный compile-контракт transform стейджей

> **Статус**: Принято / Реализовано
> **Дата принятия**: 2026-02-17
> **Решает проблему**: [DSL-PROBLEM-004](./DSL-PROBLEM-004-inconsistent-transform-compile-architecture.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

Пять transform стейджей используют три разных compile-паттерна: Map/Normalize создают Core
напрямую, Enrich/Match возвращают data-only структуры, Resolve — набор callable-ов.
Это блокирует чистое разделение DSL-слоя и runtime-слоя (DSL-DEC-003).

Подробности: [DSL-PROBLEM-004](./DSL-PROBLEM-004-inconsistent-transform-compile-architecture.md).

---

## 🎯 Решение

Стандартизировать compile-контракт: все `*Dsl.compile()` возвращают **frozen data-only** объект
(`Compiled*Rules`). `*Core` конструируется из compiled rules отдельно — в `*Engine` или
конструкторе Core.

```
Spec (Pydantic, из YAML)
    ↓  *Dsl.compile()
CompiledRules (frozen data-only)
    ↓  *Core(compiled_rules, deps)
Core (runtime-объект)
    ↓
Engine (orchestration)
    ↓
Stage (pipeline integration)
```

---

## 🏗️ Архитектурное решение

### Единый compile-контракт

Каждый DSL-компилятор в `transform_dsl/compilers/` следует одному контракту:

```python
class StageDsl:
    @staticmethod
    def compile(
        spec: StageSpec,
        *,
        # stage-специфичные зависимости компиляции
        options: StageBuildOptions = ...,
    ) -> CompiledStageRules:
        """YAML Spec → frozen data-only compiled rules."""
        ...
```

**Инварианты compile-контракта:**
1. Вход: Pydantic Spec (загруженный из YAML).
2. Выход: frozen data-only объект (CompiledRules). Без runtime-зависимостей (HTTP, DB, ...).
3. Компилятор не знает о Core/Engine — он не создаёт runtime-объекты.
4. CompiledRules содержит всё необходимое для конструирования Core.

### Per-stage compiled rules

#### Mapping

```python
@dataclass(frozen=True)
class CompiledMapRule:
    targets: tuple[str, ...]
    sources: tuple[str, ...]
    ops: tuple[OperationCall, ...]
    required: bool
    on_error: str

@dataclass(frozen=True)
class CompiledMapRules:
    rules: tuple[CompiledMapRule, ...]
    meta_rules: tuple[CompiledMetaRule, ...]
    schema_policy: CompiledSchemaPolicy | None
```

**Было:** `MapperDsl.compile()` → `MapperCore` (runtime).
**Станет:** `MapperDsl.compile()` → `CompiledMapRules` (data) → `MapperCore(rules, engine)`.

#### Normalize

```python
@dataclass(frozen=True)
class CompiledNormalizeRule:
    field: str
    ops: tuple[OperationCall, ...]
    on_error: str

@dataclass(frozen=True)
class CompiledNormalizeRules:
    rules: tuple[CompiledNormalizeRule, ...]
    global_on_error: str
```

**Было:** `NormalizerDsl.compile()` → `NormalizerCore[T]` (runtime).
**Станет:** `NormalizerDsl.compile()` → `CompiledNormalizeRules` (data) → `NormalizerCore(rules, engine, row_builder)`.

#### Enrich

```python
@dataclass(frozen=True)
class CompiledEnrichOps:
    operations: tuple[CompiledEnrichOperation, ...]
    match_key_fields: tuple[str, ...] | None
    secret_fields: frozenset[str]
    default_merge_policy: str
    default_strictness: str
```

**Уже близко к целевому состоянию.** `EnricherSpec` (текущее имя) переименовывается
в `CompiledEnrichOps` для консистентности. Структурных изменений минимум.

#### Match

```python
@dataclass(frozen=True)
class CompiledMatchRules:
    identity_rules: tuple[CompiledIdentityRule, ...]
    source_dedup: CompiledSourceDedupRules
    fuzzy: CompiledFuzzyRules | None
    ignored_fields: frozenset[str]
```

**Уже близко к целевому состоянию.** `MatchingRules` (текущее имя) переименовывается
в `CompiledMatchRules`. Структурных изменений минимум.

#### Resolve

```python
@dataclass(frozen=True)
class CompiledResolveRules:
    build_desired_state: Callable
    build_source_ref: Callable
    diff_policy: Callable
    merge_policy: Callable
    secret_fields_for_op: Callable
    link_rules: tuple[CompiledLinkRule, ...]
```

**Уже в целевом состоянии.** Callable-ы — приемлемый вариант data-only (замыкания
не содержат runtime-зависимостей, только capture compile-time данных из spec).

### Где живут compiled rules

```
transform_dsl/
├── compilers/
│   ├── mapping.py      ← MapperDsl + CompiledMapRules + CompiledMapRule
│   ├── normalize.py    ← NormalizerDsl + CompiledNormalizeRules + CompiledNormalizeRule
│   ├── enrich.py       ← EnricherDsl + CompiledEnrichOps + CompiledEnrichOperation
│   ├── match.py        ← MatchDsl + CompiledMatchRules + CompiledIdentityRule + ...
│   └── resolve.py      ← ResolveDsl + CompiledResolveRules + CompiledLinkRule + ...
```

CompiledRules определяются **рядом с компилятором** в `transform_dsl/compilers/`,
потому что это выходной контракт DSL-слоя, а не runtime-слоя.

### Как Core конструируется

После миграции Core принимает compiled rules через конструктор:

```python
# transform/mapping/mapper_core.py
class MapperCore:
    def __init__(
        self,
        compiled: CompiledMapRules,
        engine: TransformationEngine,
    ) -> None: ...

# transform/mapping/mapper_engine.py
class MapperEngine:
    def __init__(self, spec: MappingSpec, *, sink_spec, catalog, options):
        compiled = MapperDsl.compile(spec, sink_spec=sink_spec, options=options)
        self._core = MapperCore(compiled, TransformationEngine.with_core_ops())
```

Engine отвечает за:
1. Вызов `*Dsl.compile()` → CompiledRules
2. Создание Core из CompiledRules + runtime deps
3. Оркестрация вызовов Core

### Что меняется vs что остаётся

| Стейдж | Compile output сейчас | Compile output после | Объём рефакторинга |
|--------|----------------------|---------------------|-------------------|
| **Mapping** | `MapperCore` (runtime) | `CompiledMapRules` (data) | **Средний**: разделить compile и instantiate |
| **Normalize** | `NormalizerCore[T]` (runtime) | `CompiledNormalizeRules` (data) | **Средний**: аналогично Mapping |
| **Enrich** | `EnricherSpec` (data) | `CompiledEnrichOps` (data) | **Малый**: переименование |
| **Match** | `MatchingRules` (data) | `CompiledMatchRules` (data) | **Малый**: переименование |
| **Resolve** | `CompiledResolveRules` (callable) | `CompiledResolveRules` (callable) | **Нулевой**: уже в целевом состоянии |

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Единый compile-контракт для всех стейджей: `Spec → CompiledRules (data-only)`.
- ✅ DSL-компиляторы не зависят от Core → могут жить в `transform_dsl/compilers/`.
- ✅ CompiledRules тестируются отдельно от runtime (assert на data, без моков).
- ✅ Новый стейдж имеет чёткий образец: `compile() → Compiled*Rules`, `*Core(compiled, deps)`.
- ✅ Enrich, Match, Resolve уже близки к целевому состоянию — рефакторинг минимален.
- ✅ Разблокирует DSL-DEC-003: компиляторы переезжают в DSL-слой без обратных зависимостей.

**Недостатки (компромиссы)**:
- ⚠️ Mapping и Normalize требуют рефакторинга (разделение compile + Core instantiate) — приемлемо, т.к. это простейшие стейджи.
- ⚠️ `CompiledResolveRules` содержит callable-ы (замыкания) — формально не чистый data. Приемлемо: замыкания capture-ят только compile-time данные из spec, не runtime deps.
- ⚠️ Дополнительный dataclass на стейдж — небольшой overhead, окупается чёткостью контракта.

**Альтернативы, которые отклонили**:
- ❌ **Оставить *Dsl в transform/, стандартизировать только naming**: Не решает проблему разделения DSL/runtime слоёв.
- ❌ **Не стандартизировать — различия оправданы доменной спецификой**: Блокирует DSL-DEC-003 и масштабирование. Enrich/Match уже доказали, что data-only подход работает для сложных стейджей.
- ❌ **Все compile outputs через callables (как Resolve)**: Теряется introspection compiled rules для тестирования и диагностики. Data-first лучше для простых стейджей.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `transform_dsl/compilers/mapping.py` | Создан: MapperDsl + CompiledMapRules (из `transform/mapping/mapper_dsl.py`) |
| `transform_dsl/compilers/normalize.py` | Создан: NormalizerDsl + CompiledNormalizeRules (из `transform/normalize/normalizer_dsl.py`) |
| `transform_dsl/compilers/enrich.py` | Создан: EnricherDsl + CompiledEnrichOps (из `transform/enrich/enricher_dsl.py`) |
| `transform_dsl/compilers/match.py` | Создан: MatchDsl + CompiledMatchRules (из `transform/matcher/match_dsl.py`) |
| `transform_dsl/compilers/resolve.py` | Создан: ResolveDsl + CompiledResolveRules (из `transform/resolver/resolve_dsl.py`) |
| `transform/mapping/mapper_core.py` | Изменён: конструктор принимает CompiledMapRules |
| `transform/mapping/mapper_engine.py` | Изменён: вызывает compile() + создаёт Core |
| `transform/normalize/normalizer_core.py` | Изменён: конструктор принимает CompiledNormalizeRules |
| `transform/normalize/normalizer_engine.py` | Изменён: вызывает compile() + создаёт Core |
| `transform/enrich/enricher_engine.py` | Минимально: переименование EnricherSpec → CompiledEnrichOps |
| `transform/matcher/match_engine.py` | Минимально: переименование MatchingRules → CompiledMatchRules |
| Удалены: `transform/*/mapper_dsl.py`, `normalizer_dsl.py`, `enricher_dsl.py`, `match_dsl.py`, `resolve_dsl.py` | Перемещены в `transform_dsl/compilers/` |

### Инварианты

1. **Data-only output**: `*Dsl.compile()` возвращает frozen dataclass без runtime-зависимостей.
2. **No Core in DSL**: `transform_dsl/compilers/` не импортирует из `transform/` (ни Core, ни Engine).
3. **Core from compiled**: `*Core.__init__` принимает `Compiled*Rules` + runtime deps — не Spec напрямую.
4. **Naming convention**: Compile output всегда `Compiled{Stage}Rules` (или `Compiled{Stage}Ops` для Enrich).

---

## 🧪 Валидация решения

**Тесты**:
- ✅ Все существующие `*_dsl` тесты проходят после рефакторинга (тест compile → assert на compiled rules).
- ✅ Все `*_core` тесты проходят (Core конструируется из compiled rules).
- ✅ Все `*_engine` тесты проходят (engine orchestrates compile + Core).
- ✅ Verify: `transform_dsl/compilers/` не содержит импортов из `connector.domain.transform.*`.

**Метрики успеха**:
- Количество `*_dsl.py` файлов в `transform/`: 0 (все перемещены в `transform_dsl/compilers/`).
- Compile output для каждого стейджа: frozen dataclass (проверяется `dataclasses.is_dataclass` + `__dataclass_params__.frozen`).

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- `CompiledResolveRules` содержит callable-ы — замыкания capture compile-time данные. Это приемлемое исключение из "чистого data-only", т.к. Resolve compile-logic слишком функциональна для чистого data.
- `CompiledEnrichOperation` может содержать ProviderRef (ссылку на runtime-провайдер по имени) — это data (имя), а не runtime-зависимость (инстанс).

**Риски**:
- ⚠️ Рефакторинг Mapping/Normalize Core конструкторов может сломать тесты → Митигация: изменение механическое (split compile и instantiate), `pytest` верифицирует.
- ⚠️ Будущие стейджи могут не укладываться в data-only контракт → Митигация: callable в compiled rules допустим (как Resolve), главное — не Core instance.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `transform/mapping/` | Прямое | Core конструктор принимает CompiledMapRules, mapper_dsl.py удалён |
| `transform/normalize/` | Прямое | Core конструктор принимает CompiledNormalizeRules, normalizer_dsl.py удалён |
| `transform/enrich/` | Минимальное | Переименование EnricherSpec → CompiledEnrichOps, enricher_dsl.py перемещён |
| `transform/matcher/` | Минимальное | Переименование MatchingRules → CompiledMatchRules, match_dsl.py перемещён |
| `transform/resolver/` | Минимальное | resolve_dsl.py перемещён |
| `transform/enrich/spec.py` | Прямое | Модели `EnricherSpec`, `EnrichmentOperation` переносятся в compiled/ |
| `transform/matcher/rules.py` | Прямое | Модели `MatchingRules`, `IdentityRule` переносятся в compiled/ |
| Тесты `*_dsl` | Прямое | Обновление импортов |

---

## 🔗 Связанные документы

- [DSL-PROBLEM-004](./DSL-PROBLEM-004-inconsistent-transform-compile-architecture.md) — решаемая проблема
- [DSL-DEC-003](./DSL-DEC-003-per-layer-dsl-modules.md) — созависимое решение (per-layer модули)
- [DSL-DEC-002](./DSL-DEC-002-modular-dsl-core-and-contract-stabilization.md) — предыдущая модуляризация

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-17 | Решение предложено |
| 2026-02-17 | Решение принято после обсуждения |
