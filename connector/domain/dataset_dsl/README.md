# connector/domain/dataset_dsl

## Назначение

DSL описания схемы датасета: структура catalog (поля, типы), правила построения payload для целевой системы, компиляция sink-схемы.

## Файлы

| Файл | Назначение |
|---|---|
| `specs.py` | Pydantic-модели: `DatasetCatalogSpec`, `DatasetFieldSpec`, `PayloadSpec`, `FieldSerializationSpec` |
| `compiler.py` | `CatalogCompiler` — compiles catalog spec → runtime field index; `PayloadCompiler` — builds payload dict from resolved state per sink rules |
| `loader.py` | Загрузка YAML dataset-спек |

## Зависимости

**Зависит от:** `pydantic`, `domain/transform_dsl/specs/sink.py`.  
**Используется:** `datasets/yaml_spec.py`.
