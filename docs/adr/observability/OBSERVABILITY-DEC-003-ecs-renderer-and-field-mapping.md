# OBSERVABILITY-DEC-003: ECS-форма JSON-логов через подмену финального рендерера

> **Статус**: Предложено
> **Дата принятия**: 2026-06-09
> **Решает проблему**: [OBSERVABILITY-PROBLEM-003](./OBSERVABILITY-PROBLEM-003-non-ecs-log-shape.md)
> **Развивает**: [OBSERVABILITY-DEC-001](./OBSERVABILITY-DEC-001-structlog-as-standard.md) (structlog как стандарт)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

JSON-логи структурированы, но не в ECS — это блокирует прямую интеграцию с Elasticsearch
([OBSERVABILITY-PROBLEM-003](./OBSERVABILITY-PROBLEM-003-non-ecs-log-shape.md)). Нужно привести
**только финальный JSON-вывод** к ECS, не трогая транспорт, корреляцию, redaction и человекочитаемые
синки ([DEC-002](./OBSERVABILITY-DEC-002-per-component-prod-observability-layout.md)).

---

## 🎯 Решение

Ввести **один structlog-процессор `ecs_transform` (dict → dict)**, который маппит наш внутренний
`event_dict` в ECS-форму с **dotted-ключами**, и поставить его **в `ProcessorFormatter` непосредственно
перед `JSONRenderer`** — только на JSON-синках. Все существующие context-процессоры
(`merge_contextvars`, `add_log_level`, `TimeStamper`, `schema_version`, runtime-meta) и redaction
остаются нетронутыми.

Ключевые принципы решения:

1. **Меняется только последний шаг рендера, а не цепочка контекста.** Рендеринг у нас живёт не в
   `structlog.configure()`, а в `ProcessorFormatter` на хендлерах (цепочка структлога заканчивается
   на `ProcessorFormatter.wrap_for_formatter`). Поэтому ECS-маппинг — это вставка одного процессора в
   `_build_formatter`, без изменения call-sites и без новой зависимости.
2. **SRP:** маппинг (`ecs_transform`, dict→dict) отделён от сериализации (`JSONRenderer`, dict→str).
   Маппинг юнит-тестируется без парсинга JSON.
3. **Dotted-ключи** (`"log.level"`, `"event.action"`, `"labels.run_id"`) — валидный ECS; Filebeat/ES
   разворачивают их в объекты автоматически. Проще генерировать и читать глазами в файле.
4. **ECS — только на JSON-синках.** Человекочитаемые рендереры (`_HumanConsoleRenderer`,
   `_JsonTextRenderer`) не меняются.
5. **Свой процессор, а не библиотека `ecs-logging`.** Полный контроль над порядком
   redaction → map → render и над dual-transport инвариантом; библиотека хочет быть formatter'ом и
   конфликтует с нашим `ProcessorFormatter` + redaction. `ecs.version` проставляем сами.

---

## 🏗️ Архитектурное решение

### Порядок процессоров в `ProcessorFormatter` (JSON-синк)

Текущий (`_build_formatter`, `connector/infra/logging/runtime.py`):

```
ExceptionRenderer(ExceptionDictTransformer()) → redaction → remove_processors_meta → JSONRenderer
```

Целевой:

```
ExceptionRenderer(ExceptionDictTransformer()) → redaction → remove_processors_meta → ecs_transform → JSONRenderer
```

**Почему именно этот порядок (инварианты):**
- `ecs_transform` стоит **после redaction** — redaction матчит по нашим внутренним именам ключей;
  переименование в ECS до redaction увело бы ключи из-под маскирования.
- `ecs_transform` стоит **после `remove_processors_meta`** — чтобы служебные structlog-ключи
  (`_record`, `_from_structlog`) уже были вырезаны и не утекли в `labels.*` через catch-all.
- `ecs_transform` стоит **перед `JSONRenderer`** — рендерер просто сериализует уже-ECS dict.

Для текстовых синков порядок не меняется (ECS-процессор туда не добавляется).

### Новый компонент

- `EcsFieldTransformer` (или функция-процессор `ecs_transform`) в новом модуле
  `connector/infra/logging/ecs.py` — **машинно-авторитетный** источник правды по ECS-маппингу и
  словарям семантики:
  - Чистая функция вида `(_logger, _method, event_dict) -> event_dict` (структлог-процессор).
  - Константы `ECS_VERSION = "8.11"`, `SERVICE_NAME = "nexus-etl"`.
  - Таблица соответствия полей (внутренний ключ → ECS-таргет).
  - **Словари семантики как код** (легко пополнять — добавить член enum):
    `EventAction` (StrEnum, словарь `event.action`), `EventOutcome` (`success`/`failure`/`unknown`),
    `EventKind` (`event`/`metric`/`state`). Эти enum'ы валидируются контрактным тестом, поэтому
    «пополнить словарь» = добавить член, а не править строки по всему коду.
  - Не делает I/O, не знает про синки/хендлеры — чистый dict→dict.

Прозаический человекочитаемый дом семантики (каталог `event.action` с описаниями, правила уровней,
как добавить поле/действие) — dev-doc
[`docs/dev/layers/observability/ecs-logging-conventions.md`](../../dev/layers/observability/ecs-logging-conventions.md).
Машинная истина — в `ecs.py` (enum'ы), описания — в dev-doc; добавление действия правит оба (тест
сверяет членство enum).

### Точное соответствие полей (внутреннее → ECS dotted)

| Внутренний ключ (сейчас) | ECS-ключ | Примечание |
|---|---|---|
| `timestamp` | `@timestamp` | ISO-8601 UTC (offset `+00:00`/`Z` — оба валидны для ES) |
| `event` (строка-сообщение) | `message` | переименование; снимает конфликт с ECS-объектом `event` |
| `level` | `log.level` | значения уже lowercase (`info`/`warning`/…) |
| *(имя логгера)* | `log.logger` | добавить `structlog.stdlib.add_logger_name` в цепочку контекста |
| `component` | `labels.component` | из `.bind(component=…)` |
| `run_id` | `labels.run_id` | из contextvars; первичный correlation key |
| `pipeline_run_id` | `labels.pipeline_run_id` | из contextvars |
| `dataset` | `event.dataset` | ECS-каноничный для имени датасета |
| `stage` | `labels.stage` | стадия пайплайна |
| `scope` | `labels.scope` | наш scope-концепт |
| `schema_version` | `labels.schema_version` | наша версия конверта; отлична от `ecs.version` |
| `host` | `host.name` | |
| `pid` | `process.pid` | |
| `app_version` | `service.version` | |
| `git_rev` | `labels.git_rev` | |
| `exception` (dict от `ExceptionDictTransformer`) | `error.type` / `error.message` / `error.stack_trace` | `type`←класс верхнего исключения, `message`←строка, `stack_trace`←развёрнутый трейс |
| *(новый)* `action` | `event.action` | verb-noun kebab-case; словарь — `EventAction` в `ecs.py` (каталог с описаниями — в `ecs-logging-conventions.md`) |
| *(новый)* `outcome` | `event.outcome` | `success` / `failure` / `unknown` |
| *(новый)* `duration_ns` | `event.duration` | наносекунды (ECS-тип long) |
| *(новый)* `kind` | `event.kind` | `event` (default) / `metric` / `state` |
| *(добавляется константой)* | `ecs.version` | `"8.11"` |
| *(добавляется константой)* | `service.name` | `"nexus-etl"` |
| **любой прочий бизнес-kwarg** | `labels.<key>` | **catch-all**: ничего не теряем, выход остаётся валидным ECS |

**Catch-all** — ключевое правило: всё, что не имеет явного ECS-таргета, уезжает в `labels.*`
(санкционированный ECS «мешок» произвольных keyword-полей). Так переход не теряет данные и не требует
одномоментной правки всех call-sites.

### Поток данных

```
log.info("msg", action="stage-started", stage="normalize", record_count=10)
        │  (+ contextvars: run_id/pipeline_run_id/component/dataset)
        ▼
[structlog chain: merge_contextvars → add_log_level → add_logger_name → TimeStamper → schema_version → runtime_meta → wrap_for_formatter]
        ▼  (ProcessorFormatter на JSON-хендлере)
ExceptionRenderer → redaction → remove_processors_meta → ecs_transform → JSONRenderer
        ▼
{"@timestamp":"…","message":"msg","log.level":"info","log.logger":"nexus.normalizer",
 "event.action":"stage-started","event.dataset":"employees","labels.run_id":"…",
 "labels.stage":"normalize","labels.record_count":10,"service.name":"nexus-etl","ecs.version":"8.11"}
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **Аддитивно и обратимо** — один процессор + переименования; транспорт/корреляция/redaction/
  текстовые синки не трогаются.
- ✅ **Единый источник правды по ECS** (`ecs.py`) — OCP/DRY; новые поля добавляются в одном месте.
- ✅ **Call-sites не правятся для Фазы 1** — catch-all в `labels.*` сохраняет совместимость.
- ✅ **Без новой зависимости** — согласуется с духом DEC-001 (structlog уже в проекте).
- ✅ **Прямая отправка в ES** без ingest-переименований на стороне кластера.

**Недостатки (компромиссы)**:
- ⚠️ Dotted-ключи менее «каноничны», чем вложенные объекты (но ES/Filebeat принимают их как есть, а
  читать в файле проще).
- ⚠️ Сами тащим соответствие `ecs.version` (нужно отслеживать апгрейды ECS) — приемлемо: версия одна,
  меняется редко, зафиксирована константой.
- ⚠️ Реальная ценность `event.action`/`outcome`/`duration` появляется только после наполнения
  call-sites (Фаза 2) — но Фаза 1 уже делает поток валидным ECS.

**Альтернативы, которые отклонили**:
- ❌ **Библиотека `ecs-logging` (полное подключение)** — хочет быть finalize-formatter'ом,
  конфликтует с нашим `ProcessorFormatter` + redaction; меньше контроля над порядком и
  dual-transport инвариантом. Развёрнутый разбор рисков — в разделе ниже.
- ❌ **Дотированные ECS-ключи прямо на call-sites** (`extra={"event.action": …}`) — верботно,
  размазывает ECS-знание по всему коду, ломает эргономику structlog.
- ❌ **ingest-pipeline в Elasticsearch** — дублирование маппинга, дрейф источник↔кластер, лишняя точка
  отказа.
- ❌ **Вложенные объекты вместо dotted** — чище по спеке, но сложнее собирать и хуже читается в сыром
  логе; выгода для ES нулевая (он принимает оба варианта).

---

## ❌ Почему отклонено полное подключение `ecs-logging`

Рассматривали «полную» замену нашего рендера официальной библиотекой Elastic `ecs-logging`
(`StructlogFormatter` для structlog + `StdlibFormatter` для stdlib-логов). Отклонено: она борется с
тремя несущими решениями [DEC-002](./OBSERVABILITY-DEC-002-per-component-prod-observability-layout.md)
(stdlib-bridge, dual transport, redaction-surface). Риски по убыванию серьёзности:

1. **🔴 Обход redaction в трейсбэках (security-регрессия).** Сейчас порядок жёсткий:
   `ExceptionRenderer(ExceptionDictTransformer())` → **redaction** → render
   (`runtime.py`, `_build_formatter`). Трейсбэк превращается в данные ДО маскирования, и redaction по
   нему проходит. `StructlogFormatter` — терминальный рендерер: он сам строит `error.stack_trace` в
   момент рендера, ПОСЛЕ наших процессоров. Секрет в тексте исключения (`ValueError(f"token={…}")`)
   соберётся в `error.stack_trace` за пределами `LogRedactionEngine` → прямой обход маскирования
   (нарушает раздел 8 CLAUDE.md и redaction-surface для трейсбэков, см. `observability-logging.md`).
2. **🔴 Ломается dual transport (инвариант DEC-002).** У нас разные рендереры на разных синках
   (console-JSON→stderr, file logfmt/JSON, human-console) — выбор по `config.sinks.*.format`, потому
   что рендер живёт в `ProcessorFormatter` на каждом хендлере. `StructlogFormatter` ставится ОДНИМ
   терминальным процессором в `structlog.configure()` и не умеет «JSON на одном хендлере, текст на
   другом» → форсирует ECS-JSON для всего вывода и убивает человекочитаемые синки. Сохранить их можно
   только не используя библиотеку для них — т.е. это уже гибрид, а не «полное» подключение.
3. **🟠 Foreign-логи теряют корреляцию и ECS.** Логи httpx/sqlite3 сейчас ECS-ифицируются и получают
   `run_id` через `foreign_pre_chain` (stdlib-bridge). У библиотеки для stdlib свой `StdlibFormatter`,
   не знающий про наши contextvars и redaction → «полное» подключение даёт два несвязанных форматтера и
   пропажу `run_id`/маскирования на foreign-логах.
4. **🟠 Нет catch-all в `labels.*` → mapping explosion в ES.** Наш процессор уводит всё неучтённое
   (`scope`, `pipeline_run_id`, `op`, …) в `labels.*`. `ecs-logging` кладёт незнакомые ключи в корень
   по своим правилам → рост числа полей в индексе и конфликты типов (keyword vs object) в ES.
5. **🟡 Расходится с принятой формой (dotted vs nested).** Решено эмитить dotted-ключи; библиотека
   эмитит вложенные объекты. Для ES оба валидны, но это отменяет принятый выбор и хуже читается в файле.
6. **🟡 Новая зависимость + Nuitka standalone.** +1 runtime-dep (сейчас 12 в `pyproject.toml`), которую
   надо вшить в standalone-сборку и прогнать `smoke-standalone`; версия ECS жёстко связывается с
   версией пакета (апгрейд ECS = апгрейд библиотеки).
7. **🟡 Широкая переделка тестов.** Golden-тесты stderr-JSON, 5 surfaces redaction и
   no-stdout-double-emit завязаны на нашу форму и путь обработки исключений. Смена ломает их широко, а
   redaction-тест на трейсбэк (п.1) становится непроходимым.

**Что у библиотеки всё же хорошо** (и почему это не перевешивает): гарантированная
ECS-version-совместимость, поддерживаемый маппинг и обработка `error.*`, меньше своего кода — но эти
плюсы реализуются только для greenfield single-sink JSON-сервиса без stdlib-bridge и без своей
redaction. Наш случай иной.

**Реалистичный максимум — гибрид, а не «полное»:** взять у `ecs-logging` лишь *справочник имён полей*
как dict→dict шаг ВНУТРИ нашего `ProcessorFormatter` (до сериализации нашим `JSONRenderer`), сохранив
порядок `redaction → map → render`, dual transport и `labels`-catch-all. Но это ровно то, что делает
собственный `ecs_transform` — только ценой внешней зависимости ради таблицы соответствия на ~40 строк.
Поэтому выбран свой процессор.

---

## 🛠️ Реализация (план, без кода)

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/infra/logging/ecs.py` | **Новый**: `ecs_transform` процессор + ECS-константы + маппинг |
| `connector/infra/logging/runtime.py` | Вставить `ecs_transform` перед `JSONRenderer` в `_build_formatter` (оба JSON-синка); добавить `add_logger_name` в `_build_structlog_processors` |
| `connector/infra/logging/README.md` | Описать ECS-слой и порядок процессоров |
| `tests/unit/.../logging/test_ecs_transform.py` | **Новый**: таблица соответствия, catch-all, error.*, отсутствие пустых полей |
| `docs/dev/layers/observability/observability-logging.md` | Секция «ECS rendering» + ссылка на DEC-003 |

### Инварианты (must hold)
1. **redaction → remove_processors_meta → ecs_transform → JSONRenderer** — строгий порядок.
2. **Dual transport** — ECS только на JSON-синках; текстовые рендереры не меняются; JSON по-прежнему
   на stderr, не на stdout.
3. **Catch-all в `labels.*`** — ни один бизнес-kwarg не теряется и не ломает ECS-форму.
4. **`message` ≠ `event`-объект** — строка сообщения уходит в `message`, ключ `event` в выходе не
   остаётся (только `event.*`).
5. **Никаких секретов** — redaction отрабатывает до ECS-переименования.

### Фазировка
- **Фаза 1 (эта итерация — после утверждения ADR):** `ecs_transform` + переименования + `ecs.version`/
  `service.name` + `add_logger_name`. Снаружи поток — валидный ECS. Call-sites не трогаем.
- **Фаза 2 (отдельно):** словарь `event.action` + проставление `outcome`/`duration_ns` на
  lifecycle-точках (run/stage start-complete-fail) в orchestrator и стадиях. Это даёт Kibana-аналитику.
- **Фаза 3 (опц.):** `log.origin.*` на DEBUG через `CallsiteParameterAdder`; `service.environment` из
  конфига.

---

## 🧪 Валидация решения

**Тесты (Фаза 1)**:
- ✅ Каждый ключ из таблицы соответствия маппится; `@timestamp`/`message`/`log.level` присутствуют.
- ✅ Catch-all: произвольный kwarg → `labels.<key>`; `_record`/`_from_structlog` отсутствуют.
- ✅ `exception` → `error.type`/`error.message`/`error.stack_trace`.
- ✅ Текстовые синки не меняются (golden-тест человекочитаемого вывода).
- ✅ Redaction по-прежнему маскирует чувствительные ключи (порядок процессоров не сломал маскирование).
- ✅ JSON по-прежнему на stderr, не на stdout (dual-transport).

**Контрактные тесты ECS-совместимости (CI-гейт, `pytest -m unit`)** — это механизм поддержания
совместимости во времени (детали стратегии — в разделе «🔧 Поддержание ECS-совместимости»):
1. **Golden-контракт.** Репрезентативные события (info / warning / error-с-исключением) прогоняются
   через *реальную* цепочку процессоров; проверяется точный набор ключей и их JSON-типы. Ловит
   случайные переименования и регрессии порядка процессоров.
2. **Валидация против ECS-схемы.** Вендоренный статический срез определений полей ECS для
   `ECS_VERSION` (из официального `ecs_flat.yml` тега `v8.11.0`, только эмитируемые поля) → каждый
   dotted-ключ либо известное ECS-поле с совпадающим типом, либо под открытыми `labels.*`/`tags`.
   Без runtime-зависимости (фикстура только для тестов).
3. **«Нет неизвестных корневых ключей».** В корне — только разрешённый ECS-набор; всё прочее обязано
   быть под `labels.*`. Машинно форсирует catch-all и не даёт mapping explosion на источнике.
4. **Гарантии типов.** Числовые labels → int; не-скаляры в `labels.*` → строка/JSON (через
   `_format_text_value`). Под тестом.

**Проверка готовности к ES**:
1. Прогнать `nexus import plan` в JSON-режиме, собрать stderr.
2. Каждая строка — валидный JSON с `@timestamp`/`message`/`log.level`/`ecs.version`.
3. Прогнать через `filebeat test` / отправить в dev-ES → поля разложились по ECS без ingest-правил.

---

## 🔧 Поддержание ECS-совместимости

«Совместимость» — два обязательства: (1) наш вывод соответствует спеке ECS той версии, что мы
декларируем в `ecs.version`; (2) Elasticsearch стабильно его принимает (без mapping explosion и
конфликтов типов). Держим это так:

### 1. Один источник правды + закреплённая версия
Вся таблица соответствия — только в `connector/infra/logging/ecs.py`; версия — константа
`ECS_VERSION` (она же эмитится в `ecs.version`). Добавление/переименование поля — правка в одном
месте; апгрейд ECS — осознанное ревью-изменение константы, а не неявный дрейф.

### 2. Контракт проверяется на каждом PR, а не вручную
Совместимость гарантируется тремя контрактными тестами из раздела «Валидация» (golden-контракт +
валидация против вендоренной ECS-схемы + «нет неизвестных корневых ключей») плюс гарантиями типов.
Разъедется — падает CI (`pytest -m unit`), а не прод.

### 3. Процедура апгрейда версии ECS (по чеклисту, редко)
1. Bump `ECS_VERSION` в `ecs.py`.
2. Обновить вендоренный срез определений полей (`tests/.../ecs_fields_<version>.{yml,json}`) из
   соответствующего тега `elastic/ecs`.
3. Прогнать schema-тест; починить переименованные/устаревшие поля, на которые он укажет.
4. Запись в «История» этого ADR.

Частота низкая (ECS major выходит редко); тест сам показывает, что именно разъехалось.

### 4. Защита на стороне ES (defense-in-depth, операционное требование)
Половина совместимости — кластерная: применить ECS-совместимый index/component-template (Filebeat/
Elastic Agent их несут), выставить `mapping.total_fields.limit`, для `labels.*` рассмотреть
`dynamic: runtime`/`false`, чтобы произвольные labels не плодили поля. Вне репозитория, но часть
стратегии.

### 5. Гайд для контрибьюторов
Семантика живёт в репозитории: машинно-авторитетные словари (`EventAction`/`EventOutcome`/`EventKind`)
и таблица маппинга — в `connector/infra/logging/ecs.py`; прозаический каталог с описаниями, правила
уровней и «как добавить поле/действие» — в dev-doc
[`ecs-logging-conventions.md`](../../dev/layers/observability/ecs-logging-conventions.md). Правило:
новое поле проходит через маппинг в `ecs.py` либо осознанно остаётся в `labels.*`; новое действие —
член `EventAction` + строка в каталоге dev-doc; **корневые не-ECS ключи изобретать нельзя** (тест №3
это и ловит).

### Честная цена
Мы владеем маппингом, поэтому бремя ровно два пункта: держать `ecs.py` единственным местом маппинга
и синхронизировать вендоренный срез полей при bump версии. Оба самоконтролируемы тестами. Размен
против библиотеки `ecs-logging`: ~40 строк фикстуры вместо security/transport-рисков из раздела
«Почему отклонено».

---

## ⚠️ Риски и ограничения

- ⚠️ **Дрейф `ecs.version`** — версия ECS зашита константой. *Митигация*: одна точка (`ecs.py`) +
  schema-тест против вендоренного среза полей; процедура апгрейда — в разделе
  «🔧 Поддержание ECS-совместимости».
- ⚠️ **Дубли семантики `dataset`** (`event.dataset` vs возможный `labels.dataset`). *Митигация*:
  фиксируем единственный таргет — `event.dataset`; не мирроринг.
- ⚠️ **Неполный ECS до Фазы 2** — `event.action`/`outcome`/`duration` пустые, пока call-sites не
  наполнены. *Митигация*: Фаза 1 уже валидна как ECS; наполнение — инкрементально.
- ⚠️ **Незнакомые kwarg-типы в `labels.*`** (ES любит keyword/скаляры). *Митигация*: в `ecs_transform`
  приводить не-скаляры к строке/JSON, как уже делает `_format_text_value`.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `runtime.py` (`_build_formatter`/`_build_structlog_processors`) | Прямое | Вставка процессора, `add_logger_name` |
| `LogRedactionEngine` | Нет | Порядок сохраняет redaction до ECS |
| Текстовые рендереры | Нет | ECS их не касается |
| Call-sites (usecases/infra/delivery) | Нет (Фаза 1) / точечно (Фаза 2) | catch-all сохраняет совместимость |
| `ecs.py` (словари `EventAction`/`EventOutcome`/`EventKind`) | Новый | Машинно-авторитетный источник семантики |
| `docs/dev/layers/observability/ecs-logging-conventions.md` | Новый | Прозаический каталог полей/уровней/действий |

---

## 🔗 Связанные документы

- [OBSERVABILITY-PROBLEM-003](./OBSERVABILITY-PROBLEM-003-non-ecs-log-shape.md) — решаемая проблема
- [OBSERVABILITY-DEC-001](./OBSERVABILITY-DEC-001-structlog-as-standard.md) — развиваемое решение (structlog)
- [OBSERVABILITY-DEC-002](./OBSERVABILITY-DEC-002-per-component-prod-observability-layout.md) — транспорт/раскладка (не меняется)
- [ecs-logging-conventions.md](../../dev/layers/observability/ecs-logging-conventions.md) — каталог ECS-полей, правила уровней, словарь `event.action` (источник семантики)
- `connector/infra/logging/runtime.py` — целевая точка вставки `ecs_transform`
- `connector/infra/logging/ecs.py` — новый модуль маппинга + словари семантики (`EventAction`/…)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-06-09 | Решение предложено (дизайн зафиксирован; реализация — отдельным шагом) |
| 2026-06-09 | Добавлены раздел «Поддержание ECS-совместимости» и контрактные тесты (golden + schema-validation + no-unknown-root-keys) |
| 2026-06-09 | Семантика вынесена в репозиторий: словари как enum в `ecs.py` + dev-doc `ecs-logging-conventions.md` |
