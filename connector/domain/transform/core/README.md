# connector/domain/transform/core

## Назначение

Базовые типы и утилиты, общие для всех стадий пайплайна трансформации.

## Файлы

| Файл | Назначение |
|---|---|
| `result.py` | `TransformResult[T]` — иммутабельный результат стадии: `row: T | None`, `errors: tuple[DiagnosticItem, ...]`, `warnings: tuple[DiagnosticItem, ...]`; `row=None` ⟺ есть fatal errors |
| `source_record.py` | `SourceRecord` — обёртка строки-источника с `line_no` и `row_id` |
| `iterators.py` | `iter_micro_batches(source, batch_size)` — разбивка потока на батчи для батч-ориентированных стадий |
| `context.py` | `StageExecutionContext` — runtime-контекст стадии (catalogs, vault, cache ports) |
| `factory.py` | `StageFactory`, `StageDescriptor` — типизированные фабрики для сборки стадий |

## Зависимости

**Зависит от:** `domain/diagnostics/`, `domain/models.py`.  
**Используется:** всеми стадиями в `domain/transform/`.
