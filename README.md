# AnkeyIDM Employee Data Synchronization

CLI-приложение для синхронизации данных сотрудников с target-системой (сейчас основной провайдер: Ankey IDM REST API).

Проект вырос из "простого CSV→API скрипта" в layered connector с DSL-спеками (source/transform/cache/target), use-case слоями и target runtime abstraction.

## Что умеет сейчас

- `cache refresh/status/clear` для локального кэша
- stage-команды пайплайна: `mapping`, `normalize`, `enrich`, `match`, `resolve`
- `import plan` (построение плана импорта)
- `import apply` (применение готового плана)
- `check-api` (проверка доступности target API)

## Быстрый старт (dev)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
```

Проверка CLI:

```bash
syncEmployees --help
# или
python -m connector.main --help
```

## Конфигурация

Настройки загружаются с приоритетом:

`CLI > ENV > config.yml > defaults`

Готовый пример:

- `examples/configs/config_example.yml`

Быстрый старт с конфигом:

```bash
cp examples/configs/config_example.yml ./config.yml
syncEmployees --config ./config.yml --help
```

### Минимально нужное для API-команд

Для `check-api`, `cache refresh`, `import apply` (и других команд с доступом к target API) должны быть заданы:

- `host`
- `port`
- `api_username`
- `api_password`

Можно передавать через:

- `--config config.yml`
- env-переменные (см. поля в `connector/config/config.py`)
- CLI-опции (`--host`, `--port`, `--api-username`, `--api-password`)

## Источник CSV (важно)

Команды pipeline (`mapping`, `normalize`, `enrich`, `match`, `resolve`, `import plan`) берут CSV не через `--csv ...`, а через source DSL датасета.

Для `employees` это описано в:

- `datasets/employees.source.yaml`

По умолчанию там используется `location_ref: EMPLOYEES_SOURCE_PATH`, поэтому перед запуском нужно задать переменную окружения:

```bash
export EMPLOYEES_SOURCE_PATH=/path/to/employees.csv
```

## Основные команды

### Проверка подключения к target API

```bash
syncEmployees --config ./config.yml check-api
```

### Обновление кэша

```bash
syncEmployees --config ./config.yml cache refresh --dataset employees
syncEmployees --config ./config.yml cache status --dataset employees
```

Полезные override-параметры:

- `--page-size`
- `--max-pages`
- `--retries`
- `--retry-backoff-seconds`
- `--include-deleted`
- `--deps/--no-deps`

### Построение плана импорта

```bash
syncEmployees --config ./config.yml import plan --dataset employees --csv-has-header
```

Результат плана пишется в `reports/` (путь логируется и попадает в report).

### Применение плана импорта

```bash
syncEmployees --config ./config.yml import apply --plan ./reports/plan_import_<run_id>.json
```

Полезные флаги:

- `--dry-run`
- `--max-actions`
- `--stop-on-first-error`
- `--vault-mode auto|on|off`

### Отладка отдельных стадий

```bash
syncEmployees --config ./config.yml mapping --dataset employees --csv-has-header
syncEmployees --config ./config.yml normalize --dataset employees --csv-has-header
syncEmployees --config ./config.yml enrich --dataset employees --csv-has-header
syncEmployees --config ./config.yml match --dataset employees --csv-has-header
syncEmployees --config ./config.yml resolve --dataset employees --csv-has-header
```

## Артефакты выполнения

По умолчанию используются директории:

- `logs/`
- `reports/`
- `cache/`

Пути можно переопределить через config/env/CLI (`--log-dir`, `--report-dir`, `--cache-dir`).

## Архитектура (кратко)

- `connector/delivery` — CLI, команды, runtime orchestration, telemetry
- `connector/usecases` — сценарии (`cache refresh`, `import plan/apply`, stage commands)
- `connector/domain` — доменные модели, порты, DSL-спеки, правила
- `connector/infra` — SQLite, target runtime/gateway/driver, внешние интеграции
- `datasets/` — DSL-конфигурация датасетов и target-спеков

Target runtime и provider-конфигурация:

- `datasets/targets/ankey.target.yaml`
- `connector/infra/target/core/*`

## Разработка

Запуск тестов:

```bash
pytest
```

Линтинг:

```bash
ruff check .
```

## Документация

- `docs/dev/README.md` — навигация по dev-документации слоёв
- `docs/adr/` — архитектурные решения и проблемные описания
