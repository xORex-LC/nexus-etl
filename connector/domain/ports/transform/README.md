# connector/domain/ports/transform

## Назначение

Интерфейсы источников данных и справочников для pipeline.

## Порты

| Файл | Порт | Назначение |
|---|---|---|
| `sources.py` | `SourceMapper` | Итерация строк источника (CSV → `SourceRecord`) |
| `dictionaries.py` | `DictionaryProviderPort` | `lookup(key, field)`, `contains(key)`, `canonicalize(value)` — поиск в справочнике |

## Реализация

`SourceMapper` → `infra/sources/csv_reader.py`  
`DictionaryProviderPort` → `infra/dictionaries/provider.py`
