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
syncEmployees --config ./config.yml import plan --dataset employees
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
syncEmployees --config ./config.yml mapping --dataset employees
syncEmployees --config ./config.yml normalize --dataset employees
syncEmployees --config ./config.yml enrich --dataset employees
syncEmployees --config ./config.yml match --dataset employees
syncEmployees --config ./config.yml resolve --dataset employees
```

## Vault Management (unseal runtime lifecycle)

CLI namespace для управления unseal-derived master wrapping key:

```bash
syncEmployees --config ./config.yml vault-management --help
```

Поддерживаемые subcommands:

- `init`
- `status`
- `rotate`
- `rewrap`

### Пример конфигурации

```yaml
vault_management:
  require_admin_password_for_manual_ops: true
  admin_password_hash_file: "./environment/vault-admin.env"
  admin_password_env_var: "ANKEY_VAULT_ADMIN_PASSWORD"
```

Важно:

- master key material не хранится на диске и не читается из process ENV.
- runtime-команды, которым нужен vault, запрашивают unseal passphrase через prompt.
- `vault_unseal_meta` хранит Argon2id/HMAC metadata, но не хранит master key.
- `--non-interactive` требует `--force` (confirm-step отключается только через `--force`).

### Базовые сценарии

```bash
# 1) Инициализация unseal metadata + startup probe (one-time)
syncEmployees --config ./config.yml vault-management init --verify

# 2) Текущий статус metadata/DEK без unseal
syncEmployees --config ./config.yml vault-management status

# 3) Статус с проверкой unseal passphrase и probe
syncEmployees --config ./config.yml vault-management status --verify

# 4) Ручная ротация passphrase (new derived key + rewrap всех DEK + verify)
syncEmployees --config ./config.yml vault-management rotate --verify

# 5) Rewrap всех DEK текущим active derived key
syncEmployees --config ./config.yml vault-management rewrap --verify
```

### Manual-operation security gate

Для `vault-management` операций (`status/init/rotate/rewrap`) по умолчанию включена проверка admin password:

- hash (argon2id): переменная `ANKEY_VAULT_ADMIN_PASSWORD_HASH` внутри `vault_management.admin_password_hash_file`
- plaintext для non-interactive режима: `ANKEY_VAULT_ADMIN_PASSWORD`

Можно настроить:

- `vault_management.admin_password_hash_file`
- `vault_management.admin_password_env_var`

Hash-файл должен быть локальным secret-файлом с правами `0600` или строже. Hash
не читается из process ENV.

### Общие флаги vault-management

- `--force` — отключает только confirm-step.
- `--dry-run` — валидация и план без изменений в keyring/DB.
- `--non-interactive` — без prompt, пароль читается из ENV.
- `--verify/--no-verify` — включить/выключить post-operation startup verify.

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
