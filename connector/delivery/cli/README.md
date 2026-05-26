# connector/delivery/cli

## Назначение

Ядро CLI-слоя: определение команд Typer и сборка всего графа зависимостей через DI-контейнеры.

## Ключевые файлы

| Файл | Назначение |
|---|---|
| `app.py` | Typer-приложение с корневым callback (опции конфига, run-id, логирование, dataset, vault) и sub-app'ами: `cache_app`, `import_app`, `user_app`, `vault_management_app` |
| `containers.py` | DI-контейнеры (`dependency-injector`): `ConfigContainer`, `CacheContainer`, `TargetContainer`, `VaultContainer`, `PipelineContainer`, `ReportingContainer` и др. |
| `dictionaries_container.py` | Отдельный DI-контейнер для справочников (выделен из-за объёма и независимости) |
| `context.py` | `BoundCommandContext` — typed runtime context, передаваемый в каждый handler |

## Подпапки

| Папка | Назначение |
|---|---|
| `runtime/` | Lifecycle-оркестрация команды: init → handler → finalize → shutdown |
| `stages/` | Типизированная фабрика и реестр стадий пайплайна (`StageFactory`, `StageDescriptor`) |

## Зависимости

**Зависит от:** `config/`, `domain/`, `infra/`, `usecases/`, `datasets/`, `common/`.  
**Используется:** `connector/main.py`.

## Важно

`containers.py` (~43 КБ) — единственное место, где создаётся граф объектов. Добавление новой зависимости → только здесь. Никакого ручного `new` / прямых импортов инфра-классов в командах.
