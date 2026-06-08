# connector/delivery/cli

## Назначение

Ядро CLI-слоя: определение команд Typer и сборка всего графа зависимостей через DI-контейнеры.

## Ключевые файлы

| Файл | Назначение |
|---|---|
| `app.py` | Typer-приложение с корневым callback (опции конфига, run-id, pipeline-run-id, dataset, vault) и sub-app'ами: `cache_app`, `import_app`, `maintenance_app`, `obs_app`, `user_app`, `vault_management_app` |
| `containers.py` | DI-контейнеры (`dependency-injector`): `SqliteContainer`, `CacheContainer`, `TargetContainer`, `VaultContainer`, `ObservabilityContainer`, `PipelineContainer` и др.; observability runtime и ledger backend конфигурируются здесь по lifecycle-типам |
| `dictionaries_container.py` | Отдельный DI-контейнер для справочников (выделен из-за объёма и независимости) |
| `context.py` | `BoundCommandContext` — typed runtime context, передаваемый в каждый handler |
| `component_mapping.py` | `component_for_command()` — разрешение CLI-команды в `ServiceComponent`, включая observability-команды `maintenance-prune` / `obs-*` |
| `interaction.py` | `confirm_with_gate()` / `prompt_secret_with_gate()` — единая точка user-facing prompt-вызовов, синхронизированная с `InteractiveIoGate` |
| `options.py` | Переиспользуемые `typer.Option` (`DATASET`, `REPORT_DIR`, `CACHE_DIR`, `VAULT_MODE`, …) — единая точка определения флага и его `autocompletion` |
| `completions.py` | Side-effect-free `autocompletion`-коллбеки для значений опций (`complete_dataset`, `complete_path`, `complete_dir`, `complete_plan`, `complete_vault_mode`) |
| `stream_capture.py` | `StdStreamToLogger`, `TeeStream` — CLI-специфичный перехват stdout/stderr с redaction, native structlog emission и suppress-режимом на время интерактивных prompt-ов |

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

## Shell-автодополнение

Включено через `typer.Typer(add_completion=True)` в `app.py`. Пользователь ставит его один раз:
`nexus --install-completion` (или `nexus --show-completion`). Дополнение команд, подкоманд и
флагов Typer выводит **из самого дерева команд** — отдельного скрипта поддерживать не нужно.

Конвенция при добавлении нового флага/команды (масштабируемость):

- **Закрытое множество значений** → типизируй опцию `Enum`/`Literal` (`ServiceComponent`,
  `ObservabilityArtifactKind`). Дополнение значений и валидация — бесплатно, без кода.
- **Открытое/динамическое значение** → `autocompletion=<коллбек из completions.py>`, читающий
  канонический источник (registry для датасетов, fs-layout для планов). Коллбек обязан быть
  **быстрым и side-effect-free**: никакого DI/orchestrator/observability/vault/сети — Click
  вызывает его на каждый TAB в подпроцессе.
- Переиспользуемые флаги определяй один раз в `options.py` (там же `autocompletion`) — изменение
  применяется ко всем командам, которые их используют.
