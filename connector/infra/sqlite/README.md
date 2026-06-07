# connector/infra/sqlite

## Назначение

Базовый адаптер SQLite. Единственное место в проекте, где используется `sqlite3` напрямую. Все остальные SQLite-компоненты (`infra/cache/`, `infra/identity/`, `infra/secrets/`) работают только через `SqliteEngine`.

## Файлы

| Файл | Назначение |
|---|---|
| `engine.py` | `SqliteEngine` — connection management, транзакции, `execute/fetchone/fetchall`, `is_readonly()`, `execute_with_retry()` |
| `config.py` | `SqliteDbConfig` — конфигурация: `journal_mode`, `synchronous`, `busy_timeout`, `wal_autocheckpoint`, `foreign_keys` |

## Транзакционная модель

```python
with engine.transaction(mode="IMMEDIATE"):
    engine.execute(sql, params)
# ROLLBACK автоматически при любом исключении
```

Режимы: `DEFERRED` (по умолчанию), `IMMEDIATE` (для записи), `EXCLUSIVE`.  
Вложенные транзакции — `RuntimeError`.

## Зависимости

**Зависит от:** stdlib `sqlite3`.  
**Используется:** `infra/cache/`, `infra/identity/`, `infra/secrets/sqlite/`.
