# CACHE-PROBLEM-002: Расхождение SQLite-инфраструктуры между Cache и Vault

> **Статус**: Решена в CACHE-DEC-002
> **Дата создания**: 2026-02-19
> **Затронутые компоненты**: `connector/infra/cache/backends/sqlite/`, `connector/infra/secrets/sqlite/`, `SqliteEngine`, `VaultSqliteDb`, `openCacheDb`

---

## 📋 Контекст

Проект использует два независимых SQLite-файла: кэш (`ankey_cache.sqlite3`) и vault
(`ankey_vault.sqlite3`). Оба слоя выросли независимо друг от друга, каждый реализовал
собственный набор механик для работы с SQLite — открытие соединения, PRAGMA, транзакции,
обработку ошибок, миграции схемы.

При добавлении vault-слоя механики не были заимствованы из cache-слоя, а написаны заново
с иными параметрами (BEGIN IMMEDIATE, clamped busy_timeout, error mapping в доменные
исключения). В результате два решения одной задачи разошлись и теперь дублируют
инфраструктурный бойлерплейт.

---

## ⚠️ Проблема

Два SQLite-слоя имеют существенное расхождение механик при одинаковой функциональной роли:

| Аспект | Cache DB | Vault DB |
|--------|----------|----------|
| Точка входа | `openCacheDb(path)` — простая функция | `VaultSqliteDb` — класс-обёртка |
| Transaction mode | `BEGIN` (DEFERRED) | `BEGIN IMMEDIATE` |
| Busy timeout | hardcoded `5.0 s` | configurable + clamped (max 30 s) |
| Error mapping | raw `sqlite3.*` exceptions | → доменные исключения (`SecretStoreError`) |
| Readonly detection | отсутствует | есть, но вшита в `VaultStartupGuard` (domain-класс) |
| Migration chain | вручную: `if current_version < N` | отсутствует (schema создаётся целиком) |
| Schema retry | отсутствует | `SQLITE_SCHEMA_MAX_RETRIES = 2` |
| Engine | `SqliteEngine` (в cache) | прямые вызовы `self._conn.execute()` |

Дополнительно: `VaultStartupGuard.ensure_ready()` совмещает DB-уровневую задачу
(определение readonly-режима через `sqlite_master`) с domain-задачей (валидация probe-записи,
проверка мастер-ключа). Это нарушает принцип единственной ответственности и усложняет
тестирование каждой части отдельно.

---

## 🔍 Симптомы

- **Симптом 1**: Добавление нового SQLite-файла требует выбора между двумя образцами
  (cache-стиль или vault-стиль) или написания третьего варианта с нуля.
- **Симптом 2**: Улучшения на уровне DB (WAL-checkpointing, connection metrics, единая
  обработка `SQLITE_BUSY`) нельзя добавить в одном месте — нужно дублировать в оба слоя.
- **Симптом 3**: `VaultStartupGuard` тестируется как единый класс, хотя проверка
  `sqlite_master` (инфра) и проверка probe-записи (домен) — независимые задачи.
- **Симптом 4**: `SqliteEngine` реализован только в cache-слое; vault-слой его не использует,
  несмотря на то что Engine предоставляет удобный API.

---

## 📊 Масштаб проблемы

- **Частота**: При каждом добавлении новой DB или cross-cutting DB-фичи
- **Критичность**: Средняя (работающий код, но масштабирование затруднено)
- **Затронуто**: Любой новый слой, которому нужна SQLite-база (operational DB, audit log и т.д.)

---

## 🧪 Как воспроизвести

1. Открыть `connector/infra/cache/backends/sqlite/db.py` и
   `connector/infra/secrets/sqlite/db.py` рядом
2. Сравнить: обе функции делают одно — открывают SQLite с PRAGMA, но реализованы
   по-разному и имеют расходящиеся значения по умолчанию
3. Попробовать добавить новую SQLite-базу (например, `audit.sqlite3`)
4. **Ожидаемый результат**: единый шаблон, новая DB = новый дескриптор + список миграций
5. **Фактический результат**: нужно выбрать образец (cache или vault) или писать с нуля;
   lifecycle (open → migrate → close) нигде не описан единообразно

---

## 🚫 Почему это проблема?

- Дублирование инфраструктурного бойлерплейта — нарушение DRY на уровне инфраструктуры
- DB-уровневая и domain-уровневая ответственность перемешаны в `VaultStartupGuard`
- Нет единой точки для cross-cutting DB-улучшений (retry политики, метрики, PRAGMA defaults)
- Стоимость добавления новой DB растёт линейно с количеством расхождений

---

## 💡 Возможные решения (обсуждение)

### Вариант 1: Общие строительные блоки (shared utilities)

- **Идея**: Вынести общие функции в `connector/infra/sqlite/utils.py`, каждый слой
  продолжает управлять своим lifecycle самостоятельно
- **Плюсы**: Минимальные изменения в существующем коде
- **Минусы**: Lifecycle по-прежнему разбросан, нет единой точки управления всеми DB,
  не решает проблему конфигурируемости и регистрации новых DB

### Вариант 2: Единый менеджер DB (SqliteDbLifecycleManager)

- **Идея**: Создать `connector/infra/sqlite/` с декларативной регистрацией DB через
  `SqliteDbDescriptor` и единым `SqliteDbLifecycleManager` (open → migrate → hook → close)
- **Плюсы**: Одна точка управления всеми DB; добавление новой DB = дескриптор + миграции;
  domain-хуки (VaultStartupGuard) вызываются после инфраструктурной части
- **Минусы**: Требует рефакторинга обоих существующих слоёв; больше новых классов

---

## 🔗 Связанные документы

- [CACHE-DEC-002](./CACHE-DEC-002-unified-sqlite-infra-layer.md) — принятое решение
- `connector/infra/cache/backends/sqlite/db.py` — cache DB открытие соединения
- `connector/infra/secrets/sqlite/db.py` — vault DB открытие соединения
- `connector/infra/cache/backends/sqlite/engine.py` — SqliteEngine (только в cache)
- `connector/domain/secrets/vault_startup_guard.py` — conflated DB + domain readiness

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-19 | Проблема зафиксирована по итогам архитектурного ревью vault-слоя |
| 2026-02-19 | Решение принято в CACHE-DEC-002 |
