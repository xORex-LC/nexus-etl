# connector/domain/transform/mapping

## Назначение

Реализация стадии маппинга: применяет правила `MappingRule` к сырым строкам CSV-источника, формируя нормализованный словарь полей.

## Ключевые классы

| Файл | Класс | Назначение |
|---|---|---|
| `mapper_core.py` | `MapperCore` | Применяет список `MappingRule` к одной записи; возвращает `TransformResult[dict]` |
| `mapper_engine.py` | `MapperEngine` | Итерирует поток записей через `MapperCore`; добавляет диагностику на уровне потока |

## Поведение при ошибках

- Отсутствующий source-столбец → `DiagnosticItem(code="missing_source_column")`
- Ошибка DSL-операции → `DiagnosticItem(code="DSL_OP_FAILED")`
- Любая ошибка в правиле → `final_row = None` (если `on_error: "error"`)

## Зависимости

**Зависит от:** `domain/dsl/engine.py`, `domain/transform_dsl/specs/mapping.py`, `domain/transform/core/result.py`, `domain/diagnostics/`.  
**Используется:** `domain/transform/stages/stages.py` (`MapStage`).
