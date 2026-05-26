# connector/config

## Назначение

Загрузка, валидация и проекция конфигурации приложения. Граница между CLI-аргументами / YAML-файлом / ENV-переменными и типизированными объектами конфигурации, которые используются в runtime.

## Структура

| Файл | Назначение |
|---|---|
| `models.py` | Pydantic-модели всех секций конфига (`ApiConfig`, `RuntimeConfig`, `ExecutionConfig`, `SqliteConfig`, `VaultConfig`, `DictionaryConfig`, и др.) |
| `config.py` | `AppConfig` — корневая модель; `SettingsLoadError` — ошибка загрузки |
| `loader.py` | `load_app_config(path, overrides)` — читает YAML + ENV через `pydantic-settings` |
| `projections.py` | `to_operational_paths(config)` — проекция `AppConfig` → `RuntimePaths`; связывает конфиг с runtime-ресурсами |
| `diagnostics.py` | `translate_settings_load_error()` — конвертирует pydantic ValidationError → `DiagnosticItem` |

## Зависимости

**Зависит от:** `pydantic`, `pydantic-settings`, `connector/common/runtime_paths.py`, `connector/domain/diagnostics/`.  
**Используется:** `delivery/cli/containers.py` (DI-wiring), `delivery/cli/runtime/orchestrator.py`.

## Правило

Модели конфига — только `pydantic`. Конфиг не знает о бизнес-логике: `AppConfig` описывает _как запустить_, не _что делать_. Все пути разрешаются через `projections.py`, а не через прямое обращение к строкам в конфиге.
