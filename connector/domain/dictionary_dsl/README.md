# connector/domain/dictionary_dsl

## Назначение

DSL описания справочников (справочные таблицы для стадии enrich). Определяет структуру полей справочника, правила маппинга и загрузки.

## Файлы

| Файл | Назначение |
|---|---|
| `specs.py` | Pydantic-модели: `DictionarySpec`, `DictionaryFieldSpec` — структура справочника |
| `loader.py` | Загрузка YAML-спек справочников из `datasets/registry.yaml` |

## Зависимости

**Зависит от:** `pydantic`.  
**Используется:** `infra/dictionaries/`, `delivery/cli/dictionaries_container.py`.
