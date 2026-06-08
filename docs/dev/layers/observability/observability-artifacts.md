# Observability Artifacts (Reports, Plans, Ledger, Retention, Pointers)

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
  - [🚨 Failure Modes](#-failure-modes)
  - [⚠️ Инварианты системы](#️-инварианты-системы)
  - [⏱️ Performance заметки](#️-performance-заметки)
- [🛠️ Как расширять](#️-как-расширять)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Персистентные observability-артефакты и управление их жизненным циклом — запись
отчётов/планов, индекс запусков (run ledger), безопасная ретенция и публикация удобных указателей
на свежие файлы.

**Ключевая ответственность**: *Что мы пишем на диск и как этим управляем* — атомарная запись
report/plan по component-раскладке, append/read run ledger, prune устаревших файлов, `current.log`/
`latest.json` указатели.

**Расположение в кодовой базе**:
- `connector/infra/artifacts/` — `report_renderer.py`, `plan_writer.py`, `_atomic_json.py`
- `connector/infra/observability/` — `ledger.py`, `retention.py`, `viewer.py`, `pointers.py`

Все имена/пути берутся из `ObservabilityLayout` (см. [model](./observability-model.md)) — слой
ничего не именует сам.

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
infra/artifacts/
├── _atomic_json.py        # atomic_write_json (temp + fsync + os.replace)
├── report_renderer.py     # IReportRenderer / JsonReportRenderer.render_with_layout
└── plan_writer.py         # write_plan_file_with_layout (+ legacy write_plan_file)

infra/observability/
├── ledger.py              # RunLedgerBackend Protocol + Jsonl/Sqlite backends + factory + records
├── retention.py           # ObservabilityRetentionSweeper (logs/reports/plans/ledger)
├── viewer.py              # ObservabilityArtifactViewer (read-side: latest record + read/tail)
└── pointers.py            # LatestArtifactPointerPublisher (current.log / latest.json)
```

### 🎭 Применённые паттерны

#### Паттерн 1: Atomic Write (temp + os.replace)

**Где применяется**: `atomic_write_json()` — запись report/plan через временный файл в том же каталоге,
`fsync`, затем атомарный `os.replace`; при ошибке temp удаляется.

**Зачем**: краш в середине записи не оставляет усечённый JSON, способный сломать `import apply` или
парсер отчётов.

#### Паттерн 2: Strategy + Factory (ledger backend)

**Где применяется**: `RunLedgerBackend` (Protocol) с реализациями `JsonlRunLedger` / `SqliteRunLedger`;
`build_run_ledger_backend()` выбирает по `observability.ledger.backend`.

**Зачем**: JSONL по умолчанию (просто, append-only, изоляция per-component); SQLite — опция для
query-heavy сценариев. Backend взаимозаменяем без правки потребителей.

#### Паттерн 3: Best-effort sidecar

**Где применяется**: ledger (`append`/`prune`), pointers (`publish`), retention (`sweep_*`) — все
наблюдательные; их сбой **никогда** не влияет на exit code команды (обёрнуты в try/except в
оркестраторе, см. [runtime](./observability-runtime.md)).

#### Паттерн 4: Safe Retention (guardrails)

**Где применяется**: `ObservabilityRetentionSweeper` удаляет только файлы, матчащие
`<date|datetime>_<component>.*`, строго внутри каталога компонента, **не следуя по симлинкам**, с
throttle ≤1/день через marker-файл.

---

## 🔑 Ключевые абстракции

### Интерфейсы/Порты

| Интерфейс | Назначение | Реализации |
|-----------|-----------|------------|
| `IReportRenderer` (Protocol) | Рендеринг финального `ReportEnvelope` | `JsonReportRenderer` |
| `RunLedgerBackend` (Protocol) | Append-only индекс запусков + read/prune | `JsonlRunLedger`, `SqliteRunLedger` |

### Основные классы / функции

| Класс/функция | Роль | Ключевые методы |
|---------------|------|-----------------|
| `JsonReportRenderer` | Запись отчёта | `render_with_layout()`, legacy `render()` |
| `write_plan_file_with_layout()` | Запись плана в `var/plans/<c>/` | — (legacy `write_plan_file()`) |
| `atomic_write_json()` | Атомарная запись JSON | — |
| `JsonlRunLedger` / `SqliteRunLedger` | Ledger backends | `append()`, `latest_record()`, `prune()` |
| `build_run_ledger_backend()` | Factory backend | — |
| `ObservabilityRetentionSweeper` | Ретенция | `sweep_logs/reports/plans/ledger()` |
| `ObservabilityArtifactViewer` | Read-side | `latest_record()`, `resolve_latest_artifact_path()`, `read_text()`, `tail_text()` |
| `LatestArtifactPointerPublisher` | Указатели | `publish()` |

---

## 🗂️ Модели данных

### Dataclass: `RunLedgerRecord` / `RunLedgerRowCounters`

```python
@dataclass(frozen=True)
class RunLedgerRowCounters:
    rows_total: int = 0
    rows_passed: int = 0
    rows_blocked: int = 0
    rows_skipped: int = 0
    rows_with_warnings: int = 0
    errors_total: int = 0
    warnings_total: int = 0

@dataclass(frozen=True)
class RunLedgerRecord:
    run_id: str
    pipeline_run_id: str
    component: str
    started_at: str
    finished_at: str | None
    status: str
    row_counters: RunLedgerRowCounters
    log_path: str | None
    report_path: str | None
    plan_path: str | None
```

**Назначение**: одна append-only запись запуска — компактный индекс, позволяющий найти последний run
компонента и его артефакты без открытия report/plan/log.

**Lifecycle**:
1. **Создание**: `build_run_ledger_record(...)` на границе runtime-финализации (оркестратор).
2. **Запись**: `backend.append(component, record)` (best-effort).
3. **Чтение**: `backend.latest_record(component)` (read-side, `obs latest|tail`).

**Методы**: `to_payload()` (JSON/SQLite-friendly), `artifact_path(kind)` (LOG/REPORT/PLAN → путь).

### Dataclass: `RetentionSweepResult`

```python
@dataclass(frozen=True)
class RetentionSweepResult:
    deleted_files: tuple[Path, ...]
    skipped_by_marker: bool
```

### Dataclass: `PointerPublishResult`

```python
@dataclass(frozen=True)
class PointerPublishResult:
    pointer_path: Path
    mode: str   # "symlink" | "copy"
```

### Схема SQLite ledger

Таблица `run_ledger` (id autoincrement + поля записи) с индексом
`idx_run_ledger_component_finished (component, finished_at, started_at)`. Доступ — **только через
`SqliteEngine`** (`open_sqlite`), по правилу §7 (никакого прямого `sqlite3`).

---

## 📊 Ключевые методы и алгоритмы

### Обзор сложных методов

| Метод | Сложность | Назначение |
|-------|-----------|------------|
| `ObservabilityRetentionSweeper._delete_expired_files()` | O(n) по файлам каталога | age + backup-limit очистка с guardrails |
| `JsonlRunLedger.prune()` | O(n) по строкам | переписать ledger без устаревших записей |
| `SqliteRunLedger.latest_record()` | O(log n) (индекс) | последняя запись компонента |

### Метод: `ObservabilityRetentionSweeper._delete_expired_files()`

**Расположение**: `connector/infra/observability/retention.py`

**Назначение**: удалить из каталога компонента файлы старше `retention_days` и обрезать size-backup'ы
сверх `retention_backups`, не трогая чужое.

**Алгоритм**:
```
cutoff = today - retention_days
FOR entry IN component_dir.iterdir():
    IF entry.is_symlink() OR not is_file(): continue          # guard: не следуем по симлинкам
    m = _STAMP_PATTERN.match(entry.name)                      # guard: только <date|datetime>_<component>.<ext>
    IF m is None OR m.component != component.value: continue  # guard: чужие имена не трогаем
    IF stamp_date < cutoff: unlink(); collect; continue       # age-based
    ELSE собрать в candidates_by_stamp (для backup-limit)
# backup-limit: для каждого stamp оставить первые retention_backups size-роллов, остальные удалить
```

**Инварианты**:
1. Удаляются только файлы, матчащие паттерн **и** принадлежащие этому компоненту.
2. Симлинки (`current.log`/`latest.json`) и marker-файлы (начинаются с `.`) не попадают под удаление.
3. Активный файл текущего дня не удаляется (today ≥ cutoff).

**Edge cases**: `retention_days=0` → хранить только сегодняшние; legacy плоские имена
(`{command}_{uuid}.log`) под паттерн не подпадают → не трогаются (Р21).

### Метод: backend-варианты `latest_record()` / `prune()`

**JSONL**: `latest_record` читает файл, идёт `reversed(splitlines())`, возвращает первую валидную
строку (устойчиво к битым строкам); `prune` переписывает файл, оставляя записи новее cutoff (atomic
temp+replace).

**SQLite**: `latest_record` — `SELECT ... ORDER BY COALESCE(finished_at, started_at) DESC, id DESC
LIMIT 1`; `prune` — `DELETE ... WHERE COALESCE(finished_at, started_at) < ?` + `VACUUM` (вне
транзакции — VACUUM нельзя в транзакции).

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| common/observability | Зависимость | `ObservabilityLayout` (`report_file/plan_file/ledger_file`, `log_file().parent`) | пути всех артефактов |
| report layer | Зависимость | `ReportEnvelope`, `asdict_envelope` | контент отчёта (рендерится здесь) |
| infra/sqlite | Зависимость | `SqliteEngine`/`open_sqlite` | SQLite ledger |
| delivery/cli/runtime | Потребитель | renderer/writer/ledger/sweeper/pointers | финализация запуска |
| delivery/commands | Потребитель | sweeper (prune), viewer (obs latest/tail) | CLI-команды |

> **Граница с report-слоем**: контракт `IReportRenderer`/`JsonReportRenderer` и event-модель
> описаны в [report-delivery.md](../report/report-delivery.md)/[report-models.md](../report/report-models.md).
> Здесь — только **layout-aware/atomic/retention** аспекты персиста. Дублировать контракт renderer не нужно.

---

## 🔌 Контракты и границы

### Runtime-контракт (renderer/writer)

```python
JsonReportRenderer().render_with_layout(envelope, layout, component, now=...) -> str  # путь отчёта
write_plan_file_with_layout(plan_items, summary, meta, layout, component, run_id, generated_at, now=...) -> str
```

**Гарантии**:
- Путь = `ObservabilityLayout.report_file/plan_file` (component-партиция, datetime-имя).
- `meta.run_id` и `meta.schema_version` присутствуют в отчёте; `run_id` — в meta плана.
- Запись атомарна (temp+`os.replace`).
- Legacy `render(file_base_name=...)` / `write_plan_file(report_dir, run_id, ...)` сохранены
  байт-идентичными (тоже атомарны) — но не используются активными call-sites после Stage 4.

### Контракт ledger (best-effort)

```python
backend.append(component, record)            # write-side
backend.latest_record(component) -> Record|None  # read-side
backend.prune(component, retention_days, now) -> tuple[Path, ...]
```

**Гарантии**: backend взаимозаменяем (jsonl/sqlite); сбой не влияет на exit code (обёртка в runtime).

### Границы слоёв

**Разрешённые**: `infra/artifacts`/`infra/observability` → `common/observability`,
`domain/reporting` (модели), `infra/sqlite`.
**Запрещённые**: → `usecases/`, `delivery/`. SQLite — только через `SqliteEngine`.

---

## 💡 Типичные сценарии

### Сценарий 1: записать отчёт по раскладке

```python
path = JsonReportRenderer().render_with_layout(
    envelope=envelope, layout=layout, component=ServiceComponent.ENRICHER, now=finished_at,
)  # reports/enricher/2026-06-04T12-30-15_enricher.json (atomic)
```

### Сценарий 2: найти последний отчёт компонента (read-side)

```python
viewer = ObservabilityArtifactViewer(ledger_backend=backend)
p = viewer.resolve_latest_artifact_path(component=ServiceComponent.PLANNER,
                                        artifact_kind=ObservabilityArtifactKind.REPORT)
```

### Сценарий 3: опубликовать указатель

```python
LatestArtifactPointerPublisher().publish(
    artifact_kind=ObservabilityArtifactKind.LOG, artifact_path=log_path,
)  # var/logs/<c>/current.log → symlink (fallback: copy)
```

---

## 📌 Важные детали

### Особенности реализации

- **Указатели переживают retention**: `current.log`/`latest.json` не матчат `_STAMP_PATTERN` и
  пропускаются sweeper'ом (плюс симлинки skip'аются).
- **VACUUM вне транзакции** в `SqliteRunLedger.prune` — обязательное требование SQLite.
- **`tail_text` читает файл целиком** и берёт последние N строк — допустимо при size-capped логах
  (не настоящий end-seek tail).

### 🚨 Failure Modes

| Исключение | Условие | Поведение | Как обработать |
|------------|---------|-----------|----------------|
| `OSError` в `atomic_write_json` | сбой записи/replace | temp удаляется, исключение пробрасывается → INTERNAL_ERROR на финализации | проверить права/диск |
| Ошибка `ledger.append` | битый backend/диск | best-effort: WARNING, exit code не меняется | см. лог `observability` |
| `symlink` не поддерживается | окружение без симлинков (RHEL8/контейнер) | fallback на `copy2` (`mode="copy"`) | — |
| Ошибка `sweep_*` | сбой ФС | best-effort на старте (WARNING); manual `prune` → IO_ERROR | проверить каталог |

### ⚠️ Инварианты системы

1. **Инвариант: атомарность записи артефактов**
   - **Что**: report/plan пишутся через temp+`os.replace`.
   - **Почему важно**: нет усечённых JSON, ломающих `import apply`/парсеры.
   - **Где проверяется**: `atomic_write_json`; тест на replace-failure (нет `*.tmp` остатков).
2. **Инвариант: retention не трогает чужое**
   - **Что**: только `<date|datetime>_<component>.*` внутри каталога компонента, без симлинков.
   - **Почему важно**: безопасность удаления; legacy/посторонние файлы целы.
   - **Где проверяется**: `_STAMP_PATTERN` + `is_symlink()` guard.
3. **Инвариант: read=write пути**
   - **Что**: viewer/ledger разрешают путь отчёта тем же `layout`, что и writer.
   - **Почему важно**: ledger ссылается на реально записанные файлы.

### ⏱️ Performance заметки

- JSONL ledger `latest_record`/`prune` читают весь файл — приемлемо при retention-bounded размере
  (одна строка на запуск). Для тяжёлых query-сценариев — backend `sqlite` (индекс).
- SQLite ledger открывает/закрывает соединение на операцию (append/read once-per-command) — overhead
  незначим; `prune` throttl-ится daily-marker'ом (VACUUM ≤1/день).

### Частые ошибки

- ❌ Писать артефакт без `atomic_write_json`.
- ❌ Конструировать пути в обход `ObservabilityLayout`.
- ✅ renderer/writer/ledger/pointers всегда берут пути из layout.

---

## 🔗 Связанные документы

- [Observability Model](./observability-model.md) — layout (пути артефактов), `ObservabilityArtifactKind`
- [Observability Runtime](./observability-runtime.md) — кто и когда вызывает запись/ledger/pointers/sweep
- [Report Delivery](../report/report-delivery.md) / [Report Models](../report/report-models.md) — `IReportRenderer`, envelope
- [Cache Infrastructure](../cache/cache-infra.md) — `SqliteEngine` (используется ledger)

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-06 | Создан документ (DEC-002 Stages 3,5,6) | — |
