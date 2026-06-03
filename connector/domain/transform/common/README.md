# connector/domain/transform/common

## Назначение

Общие утилиты работы со значениями, переиспользуемые несколькими стадиями трансформации.

## Файлы

| Файл | Назначение |
|---|---|
| `canonicalization.py` | Generic compiled canonicalization contract: `CompiledCanonicalizeOp`, `CompiledCanonicalizer`, dual-form placeholder plan и shared runtime executor |
| `values.py` | `read_field_value(payload, field)` — читает поле из `dict` или объекта; `read_value(record_values, row_values, path)` — unified чтение по `row.field` или обычному пути |
| `text.py` | Утилиты нормализации текста (trim, casefold) для diff-сравнений в resolve |
| `sink_schema.py` | Хелперы для проверки соответствия записей sink-схеме |

## Зависимости

**Зависит от:** stdlib.  
**Используется:** `domain/transform/enrich/`, `domain/transform/resolver/`, `domain/transform/matcher/`.
