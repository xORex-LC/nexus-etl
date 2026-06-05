# connector/delivery/cli

## Назначение

Ядро CLI-слоя: определение команд Typer и сборка всего графа зависимостей через DI-контейнеры.

## Ключевые файлы

| Файл | Назначение |
|---|---|
| `app.py` | Typer-приложение с корневым callback (опции конфига, run-id, pipeline-run-id, dataset, vault) и sub-app'ами: `cache_app`, `import_app`, `user_app`, `vault_management_app` |
| `containers.py` | DI-контейнеры (`dependency-injector`): `SqliteContainer`, `CacheContainer`, `TargetContainer`, `VaultContainer`, `ObservabilityContainer`, `PipelineContainer` и др.; observability runtime и ledger backend конфигурируются здесь по lifecycle-типам |
| `dictionaries_container.py` | Отдельный DI-контейнер для справочников (выделен из-за объёма и независимости) |
| `context.py` | `BoundCommandContext` — typed runtime context, передаваемый в каждый handler |
| `component_mapping.py` | `component_for_command()` — разрешение CLI-команды в `ServiceComponent` (delivery-знание о вокабуляре команд; `ServiceComponent` живёт в `common/observability.py`) |
| `stream_capture.py` | `StdStreamToLogger`, `TeeStream`, `DropCapturedStdStreamsFilter` — CLI-специфичный перехват stdout/stderr с redaction |

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

CLI vocabulary (`mapping`, `import-plan`, `cache-refresh`, `vault-management-*`) теперь
нормализуется в `ServiceComponent` через `component_mapping.py`. Это знание
остаётся в delivery-слое, а не в `common/`.
