# ECS Logging Conventions (поля, уровни, словарь действий)

> **Статус**: Планируется (вводится [OBSERVABILITY-DEC-003](../../../adr/observability/OBSERVABILITY-DEC-003-ecs-renderer-and-field-mapping.md), Фаза 1)
> **Машинно-авторитетный источник**: `connector/infra/logging/ecs.py` (таблица маппинга + enum'ы `EventAction`/`EventOutcome`/`EventKind`)
> **Этот документ**: прозаический каталог для людей — что есть какое поле, какой уровень когда, какие действия существуют и как пополнять словарь.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🧭 Где живёт истина](#-где-живёт-истина)
- [🗂️ Каталог ECS-полей](#️-каталог-ecs-полей)
- [🎚️ Правила уровней](#️-правила-уровней)
- [📖 Словарь `event.action`](#-словарь-eventaction)
- [🔖 `event.outcome` и `event.kind`](#-eventoutcome-и-eventkind)
- [🛠️ Как пополнять](#️-как-пополнять)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

Все JSON-логи приводятся к [Elastic Common Schema (ECS)](https://www.elastic.co/docs/reference/ecs/ecs-field-reference)
процессором `ecs_transform` (см. [observability-logging.md](./observability-logging.md) и
[DEC-003](../../../adr/observability/OBSERVABILITY-DEC-003-ecs-renderer-and-field-mapping.md)).
Этот документ фиксирует **семантику**: какие поля мы эмитим, что они значат, какой уровень логирования
когда выбирать и какие значения допустимы для `event.action`/`event.outcome`/`event.kind`.

Три цели логирования (ими руководствуемся при выборе уровня и полей):
1. **Трассируемость** — по `labels.run_id` можно восстановить полный ход одного прогона.
2. **Actionability** — каждое WARNING+ содержит достаточно контекста, чтобы понять проблему без чтения кода.
3. **Signal-to-noise** — DEBUG подробен; INFO — операционная база; выше — редко и значимо.

Формат ключей — **dotted** (`"log.level"`, `"event.action"`, `"labels.run_id"`); ES/Filebeat
разворачивают их в объекты автоматически.

---

## 🧭 Где живёт истина

| Что | Где | Почему там |
|---|---|---|
| Таблица соответствия (внутренний ключ → ECS) | `ecs.py` | Один процессор-источник, проверяется контрактным тестом |
| Словарь `event.action` (членство) | `EventAction` (StrEnum) в `ecs.py` | Машинно-валидируется; «добавить» = член enum |
| `event.outcome` / `event.kind` (членство) | `EventOutcome` / `EventKind` в `ecs.py` | То же |
| `ECS_VERSION` | константа в `ecs.py` | Декларируется в `ecs.version`, апгрейд — ревью |
| Описания действий, правила уровней, каталог полей | **этот документ** | Людям нужны описания, которых enum не несёт |

Правило против дрейфа: **членство** — авторитетно в коде (enum + тест); **описания** — здесь.
Добавление действия правит оба места (контрактный тест сверяет, что enum и используемые значения согласованы).

---

## 🗂️ Каталог ECS-полей

Поля, которые эмитит `ecs_transform`. Источник значения — contextvars, runtime-meta или kwargs call-site.

### Базовые
| Поле | Тип | Когда | Описание |
|---|---|---|---|
| `@timestamp` | date | всегда | Время события, UTC (ISO-8601) |
| `message` | text | всегда | Человекочитаемое сообщение (бывший structlog `event`) |
| `ecs.version` | keyword | всегда | Версия ECS, на которую мы маппим (= `ECS_VERSION`) |

### `log.*`
| Поле | Когда | Описание |
|---|---|---|
| `log.level` | всегда | `debug`/`info`/`warning`/`error`/`critical` (lowercase) |
| `log.logger` | всегда | Имя логгера, напр. `nexus.normalizer` |

### `event.*`
| Поле | Когда | Описание |
|---|---|---|
| `event.action` | всегда желательно | Verb-noun из словаря (см. ниже) |
| `event.dataset` | когда известен датасет | Имя датасета: `employees` |
| `event.outcome` | на завершении | `success`/`failure`/`unknown` |
| `event.duration` | на завершении | Длительность в **наносекундах** (ECS-тип long) |
| `event.kind` | опц. | `event` (default)/`metric`/`state` |

### `error.*` (только ERROR/CRITICAL)
| Поле | Описание |
|---|---|
| `error.type` | Класс исключения |
| `error.message` | `str(exc)` |
| `error.stack_trace` | Полный трейсбэк (после redaction) |

### `service.*` / `process.*` / `host.*`
| Поле | Источник |
|---|---|
| `service.name` | константа `nexus-etl` |
| `service.version` | `app_version` runtime-meta |
| `process.pid` | `pid` runtime-meta |
| `host.name` | `host` runtime-meta |

### `labels.*` (корреляция + произвольный контекст)
| Поле | Когда | Описание |
|---|---|---|
| `labels.run_id` | всегда | UUID прогона — первичный correlation key |
| `labels.pipeline_run_id` | всегда | Корреляция между будущими per-stage сервисами |
| `labels.component` | всегда | `ServiceComponent`: `planner`/`applier`/… |
| `labels.stage` | внутри стадии | `normalize`/`enrich`/`resolve`/… |
| `labels.scope` | ситуативно | Под-область внутри компонента (напр. `cache`) |
| `labels.<любой kwarg>` | — | **catch-all**: всё неучтённое уходит сюда (`record_count`, `row_ref`, …) |

> **Catch-all**: любой бизнес-kwarg без явного ECS-таргета попадает в `labels.*`. Это санкционированный
> ECS «мешок» keyword-полей — ничего не теряем и не плодим корневые не-ECS ключи (см. тест №3 в DEC-003).

---

## 🎚️ Правила уровней

| Уровень | Когда | Обязательные поля |
|---|---|---|
| **CRITICAL** | Процесс не может продолжаться, аварийная остановка (DI/конфиг/необработанное на верхнем уровне) | `message`, `log.level`, `event.action`, `event.outcome=failure`, `error.*`, `labels.run_id` |
| **ERROR** | Прогон/значимая суб-операция упали (исключение или явный fail). Процесс может продолжиться, но этот прогон неуспешен | `message`, `event.action`, `event.outcome=failure`, `event.dataset`, `labels.run_id`, `labels.stage`, `error.*` |
| **WARNING** | Неожиданное, но восстановимое; degraded-решение. Исключение не требуется | `message`, `event.action`, `event.dataset`, `labels.run_id`. **Без** `error.stack_trace`, если он не несёт диагностики |
| **INFO** | Значимое операционное событие. База в проде | `message`, `event.action`, `event.outcome` (на завершении), `event.dataset`, `event.duration` (на завершении), `labels.run_id`, `labels.stage` (в стадии) |
| **DEBUG** | Подробная трассировка для разработчика (выкл. в проде) | `message`, `event.action`, `labels.run_id` + контекст, чтобы запись была самодостаточной |

**Минимум на прогон (INFO):** одно событие на старте прогона; старт+финиш каждой стадии (с `event.duration`
и счётчиком записей в `labels`); финиш прогона с `event.outcome`.

**Что НЕ логировать:** секреты/токены/пароли (их маскирует redaction, но и не передавать осознанно);
целые DataFrame'ы (только форму — высоту/колонки); одно и то же событие на двух уровнях; трейсбэки на WARNING.

---

## 📖 Словарь `event.action`

Канонический список — `EventAction` (StrEnum) в `ecs.py`. Значения — `verb-noun`, kebab-case. Описания:

| Действие | Уровень | Контекст |
|---|---|---|
| `run-started` | INFO | Старт прогуна команды/пайплайна |
| `run-completed` | INFO | Завершение прогона с `event.outcome` |
| `stage-started` | INFO | Старт стадии пайплайна |
| `stage-completed` | INFO | Завершение стадии с `event.outcome`+`event.duration` |
| `stage-failed` | ERROR | Стадия упала с необработанным исключением |
| `spec-loaded` | DEBUG | Загружен один spec-файл |
| `spec-registry-built` | INFO | Реестр спеков собран |
| `spec-validation-failed` | ERROR | Ошибка валидации spec |
| `cache-hit` / `cache-miss` | DEBUG | Результат кэш-лукапа |
| `cache-refreshed` / `cache-cleared` | INFO | Обновление/очистка кэша |
| `cache-drift-detected` | WARNING | Несовпадение content-hash кэша |
| `target-write-started` / `target-write-completed` | INFO | Запись в целевую систему (apply) |
| `target-write-failed` | ERROR | Запись в цель провалилась после retry |
| `retry-attempt` | WARNING | Транзиентная ошибка, повтор |
| `record-skipped` | WARNING | Запись отброшена (с причиной) |
| `secret-read` / `secret-written` | INFO | Доступ к vault (без значений) |
| `config-loaded` | INFO | `AppConfig` валидирован и загружен |
| `container-initialised` | INFO | DI-контейнер собран |

> Список расширяется по мере наполнения lifecycle-точек (Фаза 2 DEC-003). Любое значение `event.action`
> вне `EventAction` — ошибка (ловится контрактным тестом).

---

## 🔖 `event.outcome` и `event.kind`

- **`event.outcome`** (`EventOutcome`): `success` | `failure` | `unknown`. Ставится на событиях
  завершения (`*-completed`, `run-completed`, любые `*-failed` → `failure`).
- **`event.kind`** (`EventKind`): `event` (default) | `metric` (числовые замеры — длительности, счётчики
  как самостоятельное событие) | `state` (снимок состояния). Если не указан — `event`.

---

## 🛠️ Как пополнять

**Добавить ECS-поле:**
1. Добавить строку в таблицу маппинга в `ecs.py` (внутренний ключ → ECS-таргет) либо осознанно оставить
   в `labels.*`.
2. Добавить строку в [Каталог ECS-полей](#️-каталог-ecs-полей) этого документа.
3. Обновить вендоренный срез ECS-полей в тесте, если поле новое для схемы.

**Добавить `event.action`:**
1. Добавить член в `EventAction` (StrEnum) в `ecs.py`.
2. Добавить строку в [Словарь `event.action`](#-словарь-eventaction) с уровнем и контекстом.
3. Использовать на call-site: `logger.info("…", action=EventAction.MY_ACTION, …)`.

**Нельзя:** изобретать корневые не-ECS ключи на call-site — всё неучтённое обязано уходить в `labels.*`
(контрактный тест «нет неизвестных корневых ключей» это ловит).

---

## 🔗 Связанные документы

- [observability-logging.md](./observability-logging.md) — runtime, процессоры, redaction surface, sinks
- [OBSERVABILITY-DEC-003](../../../adr/observability/OBSERVABILITY-DEC-003-ecs-renderer-and-field-mapping.md) — решение, маппинг, поддержание совместимости
- [OBSERVABILITY-PROBLEM-003](../../../adr/observability/OBSERVABILITY-PROBLEM-003-non-ecs-log-shape.md) — проблема (не-ECS форма)
- `connector/infra/logging/ecs.py` — машинно-авторитетный источник (маппинг + enum'ы)
- [ECS Field Reference](https://www.elastic.co/docs/reference/ecs/ecs-field-reference) — внешний канон ECS
