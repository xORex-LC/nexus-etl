# connector/domain/dsl/specs

## Назначение

Базовые Pydantic-модели для описания DSL-операций и спецификаций трансформации. Служат фундаментом для всех DSL-спек более высокого уровня (`transform_dsl/specs/`).

## Файлы

| Файл | Назначение |
|---|---|
| `_base.py` | `OperationCall` — одна DSL-операция с именем и аргументами; базовые миксины валидации |
| `transform.py` | `TransformSpec` — базовая спека применения DSL к полю; shorthand нормализация (`op:` → `ops: [...]`) |

## Зависимости

**Зависит от:** `pydantic`.  
**Используется:** `domain/transform_dsl/specs/`, `domain/dsl/engine.py`.
