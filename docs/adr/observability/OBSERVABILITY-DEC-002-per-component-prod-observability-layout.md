# OBSERVABILITY-DEC-002: Per-component прод-раскладка наблюдаемости (logs/reports/plans) на structlog

> **Статус**: Принято
> **Дата принятия**: 2026-06-04
> **Решает проблему**: [OBSERVABILITY-PROBLEM-002](./OBSERVABILITY-PROBLEM-002-flat-non-partitioned-artifacts.md)
> **Развивает**: [OBSERVABILITY-DEC-001](./OBSERVABILITY-DEC-001-structlog-as-standard.md) (structlog как стандарт)
> **Участники решения**: @xORex-LC

---

## 📋 Контекст

Логи/отчёты/планы пишутся в плоские общие каталоги с `uuid4`-именами, без ротации/ретенции, планы
смешаны с отчётами, ключ раскладки — имя CLI-команды
([OBSERVABILITY-PROBLEM-002](./OBSERVABILITY-PROBLEM-002-flat-non-partitioned-artifacts.md)).
Это не прод-модель и не готово к стратегическому расколу монорепозитория на отдельные сервисы
(per-stage systemd-юниты). Параллельно действует [OBSERVABILITY-DEC-001](./OBSERVABILITY-DEC-001-structlog-as-standard.md):
structlog — единственный стандарт логирования, `infra/logging/` удаляется после миграции.

---

## 🎯 Решение

Ввести **`ServiceComponent`** (логический сервис, отвязанный от имени команды) как ключ раскладки и
декларативную **политику наблюдаемости**. Единый резолвер раскладки переиспользуется монолитом
сегодня и отдельными сервисами завтра → раскол становится **no-op** для observability.

Логирование строится **на structlog** (реализация DEC-001 для новой подсистемы): contextvars для
сквозного контекста, JSONRenderer в stderr, processor-цепочка для обогащения и редактирования;
файловая daily+size ротация остаётся stdlib-handler'ом **под** structlog через `ProcessorFormatter`.

### Раскладка артефактов
```
var/logs/<component>/<YYYY-MM-DD>_<component>.log              # append весь день + ротация
reports/<component>/<YYYY-MM-DDThh-mm-ss>_<component>.json     # один файл на запуск
var/plans/<component>/<YYYY-MM-DDThh-mm-ss>_<component>.json   # вынесено из reports/
var/logs/<component>/index.jsonl                              # run ledger
```
`run_id` убран из имён, сохраняется в `meta`/контексте лога для корреляции. Имена в **UTC**.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые**:
- `connector/common/observability.py`: `ServiceComponent` (enum по стадиям конвейера), `ComponentIdentity`,
  `ObservabilityLayout` (чистый резолвер `(runtime_paths, component, policy, clock) → пути`, без I/O).
- `connector/infra/observability/retention.py`: sweeper ретенции.
- `connector/infra/observability/ledger.py`: run ledger (jsonl|sqlite).
- `connector/delivery/cli/stream_capture.py`: перенос `StdStreamToLogger`/`TeeStream` (по DEC-001).

**Изменения**:
- `infra/logging/`: structlog-конфигурация + processors (контекст, JSONRenderer→stderr, redaction,
  schema_version); кастомный `DailySizeRotatingFileHandler` как stdlib-handler под `ProcessorFormatter`.
  `EnsureFieldsFilter`/`map_log_level`/per-run `create_command_logger` — выводятся из употребления (DEC-001).
- `infra/artifacts/{report_renderer,plan_writer}.py`: component-подкаталог, datetime-имена, атомарная запись.
- `common/runtime_paths.py`: `plans_root`; `common/run_id.py`: `pipeline_run_id` рядом с `run_id`.
- `config/models.py`: `ObservabilityConfig` → вложенные подсекции `logging/reporting/plans/diagnostics/ledger`.
- `delivery/cli/containers.py`: observability в `InfraContainer` с разведением провайдеров по
  наличию lifecycle (не всё `Resource`): **`Resource`** — logging runtime/handler stack (+ ledger
  backend, если держит дескриптор; teardown=flush/close); **`Factory`/`Singleton`** — sweeper, layout
  resolver, redaction engine, component mapper (stateless); **вне DI** — `ComponentIdentity`/inputs.
- `delivery/cli/runtime/orchestrator.py`: резолв компонента, structlog bind, sweeper, ledger.

### Ключевые решения (детально — в worknote, Р1–Р22)

| # | Решение |
|---|---|
| Партиция | По **стадии конвейера** (`mapper/normalizer/enricher/matcher/resolver/planner/applier/cache/vault/topology`) |
| Логи | daily + size (гибрид), **append** в дневной файл; ретенция по дням + бэкапам |
| Транспорт | **stdout = результат/presenter; stderr = структурный JSON-лог** (journald/ELK ловит оба) |
| Отчёты | один файл на запуск, pretty JSON, за `IReportRenderer` (готовность к JSONL) |
| Планы | один файл на запуск, вынесены в `var/plans/`, индивидуально адресуемы |
| Конфиг | вложенные подсекции `observability.{logging,reporting,plans,diagnostics,ledger}` — **ломающее изменение**, чистый разрыв без алиасов |
| Корреляция | `pipeline_run_id` (общий на прогон) + per-service `run_id`, заложены сразу |
| Доп. фичи | UTC-имена; атомарная запись; redaction-processor; per-component уровень лога; run ledger; CLI `maintenance prune`/`obs latest\|tail` |

### Поток данных (логи)
```
log.info("event", stage=..., dataset=...)
  → structlog processors (merge_contextvars[run_id,pipeline_run_id,component], add schema_version,
                          redaction, JSONRenderer)
  → stderr  (journald/ELK)
  + ProcessorFormatter → DailySizeRotatingFileHandler → var/logs/<component>/<date>_<component>.log
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Раскол монорепо на per-stage сервисы — no-op для observability (один резолвер + политика).
- ✅ Прод-модель: партиция, daily+size ротация, ретенция, ledger, структурный транспорт.
- ✅ По имени видно последний запуск (UTC datetime), без открытия файлов; ledger даёт queryable историю.
- ✅ Реализует DEC-001: structlog-processors закрывают контекст/JSON/redaction декларативно, без `EnsureFieldsFilter`.
- ✅ Планы отделены от отчётов; отчёты за `IReportRenderer` (будущий JSONL — подмена рендерера).

**Недостатки (компромиссы)**:
- ⚠️ Ломающее изменение схемы конфига (приемлемо: канонический конфиг, в духе CONFIG-DEC; чистый разрыв).
- ⚠️ Кастомный daily+size handler (в stdlib нет) — но это единственная «тяжёлая» часть, изолирована.
- ⚠️ Объём работ (фазовый план) — но каждая фаза самодостаточна и не ломает текущее поведение до wiring.

**Альтернативы, которые отклонили**:
- ❌ **Точечные патчи** (date-префикс + подкаталоги команд): не вводит `ServiceComponent`, не решает
  транспорт/ретенцию/ledger, не готовит раскол.
- ❌ **Остаться на stdlib, заменить DEC-001**: откат принятого направления; structlog уже в проекте и
  чище закрывает контекст/redaction/JSON.
- ❌ **JSONL-отчёты сейчас**: теряем pretty-структуру; отложено как будущая опция за `IReportRenderer`.
- ❌ **JSON-логи в stdout**: пачкает результат/presenter и ломает `nexus ... > out`; выбрали stderr.

---

## 🛠️ Реализация

Фазовый план — `docs/notes/observability/OBSERVABILITY_IMPLEMENTATION_PLAN.md` (Этапы 1–6 + O + Z).
Сводно:

| Этап | Тема |
|---|---|
| 1 | `common` value-objects + конфиг (вложенные подсекции, clock, pipeline_run_id, DI-провайдеры) |
| 2 | structlog logging: processors + JSON→stderr + redaction + daily/size handler + ретенция |
| 3 | Артефакты: отчёты/планы (component-подкаталог, datetime, атомарная запись, schema_version) |
| 4 | Wiring: маппинг команд → компонент, DI-провайдеры по типам (Resource/Factory/plain), sweeper, проброс pipeline_run_id, легаси-файлы |
| 5 | Run ledger |
| 6 | CLI-эргономика (`maintenance prune`, `obs latest\|tail`, latest-указатели) |
| O | (Ортогонально) run_id → UUIDv7/ULID |
| Z | Финальная зачистка легаси-кода |

### Инварианты

1. **`ServiceComponent` — единственный ключ раскладки**; путь/имя выводятся только из него + политики + clock.
2. **stdout = результат, stderr = логи** — структурный JSON никогда не идёт в stdout.
3. **Sweeper безопасен**: только паттерн `<date|datetime>_<component>.*` внутри `<root>/<component>`,
   без следования по симлинкам, троттлинг ≤1/день.
4. **`pipeline_run_id`** присутствует в логах/ledger/meta (в монолите равен `run_id`).
5. **Один источник секретных ключей** для redaction-processor / `PayloadSanitizer` / `TargetSafeLogger`.
6. **Легаси runtime-файлы** на диске sweeper не трогает (другой паттерн имени).
7. **DI-провайдер по lifecycle**: `Resource` — только для объектов с реальным teardown (logging
   runtime/handler stack, ledger-с-дескриптором); stateless-сервисы — `Factory`/`Singleton`;
   value-объекты (`ComponentIdentity`, inputs layout) — вне DI. Не service-locator.

---

## ⚠️ Риски и ограничения

**Ограничения**:
- `import plan` (монолит) логирует под одним компонентом (`planner`); per-stage фанаут внутри одного
  процесса отложен до реального раскола.
- Метрики (Prometheus) и компрессия/disk-cap — вне объёма (открытые вопросы ОВ-5/ОВ-6 worknote).

**Риски**:
- ⚠️ Согласование structlog-JSON в stderr с текущим перехватом stdout/stderr → **Митигация**: перенос
  `StdStreamToLogger`/`TeeStream` в `stream_capture.py`, фильтр против задвоения, интеграционный тест.
- ⚠️ Ломающее изменение конфига → **Митигация**: обновить примеры/loader/тесты, чистый разрыв одной фазой.
- ⚠️ Кастомный rotating-handler под конкурентным `import apply` → **Митигация**: thread-safe (lock).
- ⚠️ Удаление легаси-кода заденет используемый символ → **Митигация**: Этап Z последним, греп+отдельный коммит.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `config` (AppConfig) | Ломающее | Вложенные подсекции observability; обновить потребителей и примеры |
| `infra/logging` | Переписывается | structlog + handler под bridge; deprecate stdlib-фабрику (DEC-001) |
| `infra/artifacts` | Изменение раскладки/именования | component-подкаталог, datetime, атомарная запись |
| `delivery/cli` | Wiring + новые команды | маппинг компонента, DI-провайдеры по типам (Resource только для lifecycle), `maintenance`/`obs` |
| Report layer | Совместимо | `ReportEnvelope.meta` += `schema_version`; рендерер за `IReportRenderer` |

---

## 🔗 Связанные документы

- [OBSERVABILITY-PROBLEM-002](./OBSERVABILITY-PROBLEM-002-flat-non-partitioned-artifacts.md) — решаемая проблема
- [OBSERVABILITY-DEC-001](./OBSERVABILITY-DEC-001-structlog-as-standard.md) — стандарт логирования (развивается)
- [REPORT-DEC-001](../report/REPORT-DEC-001-execution-context-event-driven-report-layer.md), [REPORT-DEC-008](../report/REPORT-DEC-008-report-policy-capability-profiles-and-contract.md) — слой отчётности
- [DELIVERY-DEC-006](../delivery/DELIVERY-DEC-006-app-container-composition-root-integration.md) — DI composition root
- Worknote / Implementation Plan: `docs/notes/observability/`

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-06-04 | Решение принято; выровнено на structlog (развивает DEC-001) |
