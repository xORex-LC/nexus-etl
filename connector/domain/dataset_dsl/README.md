# connector/domain/dataset_dsl

## Назначение

DSL описания dataset-level registry metadata: report/apply настройки, diagnostics и topology capability binding.

## Файлы

| Файл | Назначение |
|---|---|
| `specs.py` | Pydantic-модели: `DatasetDslSpec`, `ReportAdapterSpec`, `ApplyAdapterSpec`, `TopologyCapabilitySpec` |
| `payload_compiler.py` | `SinkDrivenPayloadBuilder` — builds payload dict from resolved state per sink rules |
| `params_compiler.py` | Компиляция params-builder policy для apply adapter |
| `catalog_compiler.py` | Компиляция dataset diagnostic entries в `ErrorCatalog` |
| `loader.py` | Загрузка и валидация dataset-level секций runtime registry |

## Зависимости

**Зависит от:** `pydantic`, `domain/transform_dsl/specs/sink.py`.  
**Используется:** `datasets/yaml_spec.py`, `datasets/yaml_spec_loader.py`.
