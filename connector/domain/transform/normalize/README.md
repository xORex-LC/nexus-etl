# connector/domain/transform/normalize

## Назначение

Стадия нормализации: приводит смапленные поля к единому формату (типы, регистр, whitespace, булевы значения).

## Ключевые классы

| Файл | Назначение |
|---|---|
| `normalizer_engine.py` | `NormalizerEngine` — итерирует поток через `NormalizerCore` |
| `normalizer_core.py` | `NormalizerCore` — применяет `NormalizeRule` к одной записи; поле `on_error: "warn"` превращает ошибку в предупреждение |

## Зависимости

**Зависит от:** `domain/dsl/engine.py`, `domain/transform_dsl/specs/normalize.py`, `domain/transform/core/result.py`.  
**Используется:** `domain/transform/stages/stages.py` (`NormalizeStage`).
