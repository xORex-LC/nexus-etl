# connector/domain/transform_dsl

## Назначение

Декларативный слой описания правил трансформации данных. Содержит Pydantic-модели (specs) для каждой стадии пайплайна и компиляторы, которые преобразуют эти спеки в исполняемые объекты движка.

## Структура

| Подпапка | Назначение |
|---|---|
| `specs/` | Pydantic-модели: `MappingSpec`, `NormalizeSpec`, `EnrichSpec`, `MatchSpec`, `ResolveSpec`, `SinkSpec`, `SourceSpec`, `ValidateSpec` |
| `compilers/` | Компиляторы: `MappingCompiler`, `NormalizeCompiler`, `EnrichCompiler`, `MatchCompiler`, `ResolveCompiler` — переводят spec → runtime объекты стадии |

## Поток данных

```
YAML-файл → loader → Pydantic Spec → Compiler → Stage (StageContract)
```

## Зависимости

**Зависит от:** `domain/dsl/specs/`, `domain/dsl/engine.py`, `pydantic`.  
**Используется:** `domain/transform/` (каждая стадия получает скомпилированный объект), `datasets/yaml_spec.py`.

## Правило

Спека описывает _что_ делать (декларативно). Компилятор — _как_ собрать из этого runtime-объект. Движок (`dsl/engine.py`) — _как_ выполнить. Эти три вещи должны оставаться разделёнными.
