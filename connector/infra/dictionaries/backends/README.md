# connector/infra/dictionaries/backends

## Назначение

Бэкенды для хранения и поиска данных справочников. Абстракция над конкретной технологией хранения (сейчас только polars).

## Файлы

| Файл | Назначение |
|---|---|
| `polars_backend.py` | `PolarsDictionaryBackend` — хранит справочник как polars DataFrame; `filter_by(key, value)` → `list[dict]`; `load_from_csv(path)` |

## Зависимости

**Зависит от:** `polars`.  
**Используется:** `infra/dictionaries/provider.py`.
