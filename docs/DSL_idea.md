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

### Роль TransformationEngine
**TransformationEngine = универсальный исполнитель ops**.  
Он используется там, где логика стадии сводится к применению операций:
- MapperCore (apply ops к source → row)
- NormalizerCore (apply ops к row)
- EnricherCore (apply ops для allow_if/compute/lookup keys)
Сайд‑эффекты и политики остаются в StageCore, **не в TransformationEngine**.

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

## Lookup templates (кратко)
В enrich можно добавить укороченную форму:
```yaml
enrich:
  lookup_templates:
    manager_by_full_name:
      lookup: find_user_by_full_name
      value_path: _id
      ops: [trim, split_name]
  lookup:
    - name: manager_id
      target: manager_id
      source: manager_full_name
      template: manager_by_full_name
```
При загрузке YAML шаблон разворачивается в полноценное правило.
