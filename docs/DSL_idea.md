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
