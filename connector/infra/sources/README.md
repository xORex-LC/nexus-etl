# connector/infra/sources

## Назначение

Чтение данных из CSV-источника. Реализует `SourceMapper` (порт) на базе polars.

## Файлы

| Файл | Назначение |
|---|---|
| `csv_reader.py` | `CsvSourceReader` — реализует `SourceMapper`: читает CSV через polars, итерирует строки как `SourceRecord`; обрабатывает encoding, delimiter, null-значения |
| `csv_utils.py` | Вспомогательные утилиты парсинга CSV (определение разделителя, encoding detection) |

## Зависимости

**Зависит от:** `polars`, `domain/ports/transform/sources.py`, `domain/transform/core/source_record.py`.  
**Используется:** `datasets/yaml_spec.py` (через `DatasetSpec.build_record_source()`).

## Правило

Polars DataFrame создаётся только здесь. В domain и usecases работаем с `dict` / `SourceRecord`, не с DataFrame.
