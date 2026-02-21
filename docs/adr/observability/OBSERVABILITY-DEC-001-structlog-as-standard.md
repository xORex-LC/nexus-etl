# OBSERVABILITY-DEC-001: structlog как единственный стандарт логирования

> **Статус**: Принято (миграция постепенная)
> **Дата принятия**: 2026-02-19
> **Решает проблему**: [OBSERVABILITY-PROBLEM-001](./OBSERVABILITY-PROBLEM-001-inconsistent-logging.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

В проекте сосуществуют stdlib `logging` (через `connector/infra/logging/setup.py`) и `structlog`
(уже добавлен, используется в ряде мест). Это создаёт несогласованный контекст в логах и
повышает стоимость каждого нового компонента с логированием
([OBSERVABILITY-PROBLEM-001](./OBSERVABILITY-PROBLEM-001-inconsistent-logging.md)).

---

## 🎯 Решение

Зафиксировать `structlog` как единственный стандарт. Весь новый код использует structlog.
Существующий код на stdlib мигрирует оппортунистически. `connector/infra/logging/` удаляется
после завершения миграции (с отдельной обработкой `StdStreamToLogger`/`TeeStream`).

---

## 🏗️ Архитектурное решение

### Стандартный паттерн использования

**1. Конфигурация — один раз при старте приложения:**
```python
# connector/delivery/cli/app.py или containers.py
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if dev_mode else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(log_level),
    logger_factory=structlog.PrintLoggerFactory(),
)
```

**2. Привязка контекста — один раз в точке старта pipeline:**
```python
# В начале каждой команды
structlog.contextvars.clear_contextvars()
structlog.contextvars.bind_contextvars(
    run_id=run_id,
    command=command_name,
    dataset=dataset_name,
)
# Далее — все логи в любом модуле автоматически несут run_id, command, dataset
```

**3. Логирование в модулях:**
```python
log = structlog.get_logger()

# Вместо: logger.info("Processing row %s", row_id, extra={"runId": run_id, "component": "apply"})
log.info("row_processed", row_id=row_id, status=status)
# В логе автоматически: run_id=... command=... dataset=... row_id=... status=...
```

### Что происходит с `connector/infra/logging/`

| Компонент | Судьба | Замена |
|-----------|--------|--------|
| `EnsureFieldsFilter` | Удалить | `bind_contextvars()` гарантирует наличие полей |
| `logEvent(runId, component, ...)` | Удалить | `log.info("event", component="apply")` |
| `mapLogLevel` | Удалить | `structlog.make_filtering_bound_logger(level)` |
| `createCommandLogger` | Удалить | Глобальная конфигурация structlog в bootstrap |
| `StdStreamToLogger` + `TeeStream` | **Перенести** | CLI stdout/stderr capture — отдельная CLI-утилита, не часть logging-инфраструктуры |

**`StdStreamToLogger`/`TeeStream`** — функциональность перехвата stdout/stderr с одновременной
записью в файл и вывод на консоль — специфична для CLI и не исчезает. Переносится в
`connector/delivery/cli/stream_capture.py` и при необходимости адаптируется под structlog.

### Stdlib bridge

Structlog настраивается с stdlib bridge, чтобы логи от внешних библиотек (sqlite3, httpx и т.д.)
также проходили через structlog-процессоры:

```python
structlog.stdlib.recreate_defaults()  # или кастомная настройка stdlib bridge
logging.basicConfig(handlers=[structlog.stdlib.ProcessorFormatter.wrap_for_formatter(...)])
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ `bind_contextvars(run_id=...)` один раз — `run_id` во всех логах pipeline без передачи вручную
- ✅ Единый формат: JSON в prod (для log-агрегаторов), ConsoleRenderer в dev
- ✅ Structlog уже в проекте — решение без новых зависимостей
- ✅ Нет `EnsureFieldsFilter` workaround'а
- ✅ Процессор-pipeline: можно добавить фильтрацию чувствительных полей (vault-ключи в логах) в одном месте

**Недостатки (компромиссы)**:
- ⚠️ `StdStreamToLogger`/`TeeStream` требует отдельной обработки — не исчезает, а переносится
- ⚠️ Постепенная миграция означает временный период сосуществования двух стилей

**Альтернативы, которые отклонили**:
- ❌ **Оставить оба**: несогласованный контекст в логах, растущая стоимость сопровождения
- ❌ **Вернуться на stdlib**: stdlib не даёт декларативного контекстного биндинга

---

## 🛠️ Реализация

### Стратегия миграции

**Весь новый код** — только structlog с первого дня.
**Существующий код** — мигрирует оппортунистически: при любом изменении модуля, использующего
`logging.getLogger()` или `logEvent()`, попутно переводим его на structlog.
**Отдельный PR** — только для удаления `connector/infra/logging/` (после полной миграции).

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/delivery/cli/app.py` / `containers.py` | Глобальная конфигурация structlog |
| Каждая команда (`delivery/commands/*.py`) | `bind_contextvars` в начале, `clear_contextvars` в конце |
| `connector/infra/logging/setup.py` | Удалить после миграции всех потребителей |
| `connector/delivery/cli/stream_capture.py` | Новый файл: `StdStreamToLogger`/`TeeStream` |

### Инварианты

1. `run_id`, `command`, `dataset` биндятся через `contextvars` — не передаются как параметры
2. Новые модули не импортируют `logging.getLogger()` напрямую — только `structlog.get_logger()`
3. Чувствительные данные (ключи, пароли) не попадают в structlog через keyword args

---

## 🧪 Валидация решения

**Проверка**:
- `run_id` присутствует в каждой строке лога команды без явной передачи
- В JSON-режиме (prod) каждая строка — валидный JSON с полями `run_id`, `command`, `level`, `timestamp`, `event`
- Логи внешних библиотек проходят через stdlib bridge и имеют тот же формат

---

## 🔗 Связанные документы

- [OBSERVABILITY-PROBLEM-001](./OBSERVABILITY-PROBLEM-001-inconsistent-logging.md) — решаемая проблема
- `connector/infra/logging/setup.py` — удаляется после миграции
- `connector/delivery/cli/stream_capture.py` — целевое место для `StdStreamToLogger`/`TeeStream`

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-19 | Решение принято; structlog уже в проекте, зафиксирован как стандарт |