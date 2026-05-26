# connector/infra/dictionaries

## Назначение

Загрузка и runtime-lookup справочников (reference data) для стадии enrich. Реализует `DictionaryProviderPort`.

## Файлы / подпапки

| Путь | Назначение |
|---|---|
| `provider.py` | `PolarsDictionaryProvider` — реализует `DictionaryProviderPort`: `lookup(key, field)`, `contains(key)`, `canonicalize(value)`; телеметрия hit/miss/error |
| `loader_csv.py` | `CsvDictionaryLoader` — загружает CSV из `dictionaries/` директории; верифицирует SHA-256 по манифесту |
| `backends/polars_backend.py` | `PolarsDictionaryBackend` — хранит DataFrame, выполняет фильтрацию |
| `dsl_runtime.py` | Компилятор DSL-выражений → polars-фильтры |
| `versioning.py` | `DictionaryVersionInfo` — отслеживание версии и fingerprint |
| `telemetry.py` | Статистика hit/miss/error для мониторинга качества справочников |

## Зависимости

**Зависит от:** `polars`, `domain/ports/transform/dictionaries.py`, `domain/dictionary_dsl/specs.py`.  
**Используется:** `delivery/cli/dictionaries_container.py`, `domain/transform/providers/registry.py`.
