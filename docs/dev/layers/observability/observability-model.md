# Observability Model (Component Identity & Artifact Layout)

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [📐 UML диаграммы](#-uml-диаграммы)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Диаграмма зависимостей](#диаграмма-зависимостей)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [🎯 Canonical artifact layout](#-canonical-artifact-layout)
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

**Назначение**: Чистое ядро observability-подсистемы — типизированные идентификаторы компонентов
и **единственный источник имён/путей** для всех runtime-артефактов (логи, отчёты, планы, ledger,
latest-pointers).

**Ключевая ответственность**: Определять, *как называется и где лежит* каждый observability-артефакт
для конкретного логического компонента сервиса, не выполняя при этом никакого I/O.

**Расположение в кодовой базе**: `connector/common/observability.py`

Observability — **cross-cutting concern**, а не стадия пайплайна. Его «ядро» — это не алгоритм
(как граф в [topology-core](../topology/topology-core.md)), а **value-object-контракт**: набор
неизменяемых идентификаторов и чистый резолвер путей. Вся остальная подсистема (logging, artifacts,
retention, ledger, runtime-wiring) строится поверх этого контракта.

**Зачем это центральный модуль**: партиционирование по `ServiceComponent` и тот факт, что
`ObservabilityLayout` — единственный владелец имён, делают будущий переход «монорепозиторий →
отдельные per-stage сервисы (systemd-юниты)» **no-op для observability**: вынесенный сервис несёт
тот же `ComponentIdentity` и ту же layout-policy и пишет в те же пути без изменения поведения.

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
connector/common/observability.py
├── ServiceComponent           # enum логических компонентов (ключ раскладки)
├── ComponentIdentity          # value-object идентичности компонента
├── ObservabilityArtifactKind  # enum типов артефактов (log/report/plan)
├── ObservabilityLayoutPolicy  # policy: partition_by_component + clock
├── ObservabilityRedactionPolicy # policy: enabled + secret keys
├── RuntimePathsLike           # Protocol на runtime roots (logs/reports/plans)
└── ObservabilityLayout        # чистый резолвер имён/путей (single source of truth)
```

Модуль не импортирует ничего из `infra/`, `usecases/`, `delivery/` — только stdlib и
`connector.common.sanitize` (для дефолтного набора секретных ключей). Это самый внутренний слой
подсистемы.

### 📐 UML диаграммы

UML-исходники для observability на текущем этапе **не создавались** (доки текстовые). Ключевые
структуры приведены ASCII-схемами в разделах ниже и в [Canonical artifact layout](#-canonical-artifact-layout).

### 🎭 Применённые паттерны

#### Паттерн 1: Value Object

**Где применяется**: все идентификаторы и policy — неизменяемые `@dataclass(frozen=True)` / `str, Enum`.

**Реализация в коде**:
- **Identity**: `ServiceComponent`, `ComponentIdentity`, `ObservabilityArtifactKind` в
  `connector/common/observability.py`
- **Policy**: `ObservabilityLayoutPolicy`, `ObservabilityRedactionPolicy` там же

**Зачем**: идентичность и политика передаются по слоям как данные, безопасны к шарингу, легко
тестируются и сравниваются.

#### Паттерн 2: Single Source of Truth (naming authority)

**Где применяется**: `ObservabilityLayout` — **единственное** место, где рождаются имена
`<component>/<date|datetime>_<component>.<ext>`.

**Реализация в коде**:
- **Authority**: `ObservabilityLayout.log_file/report_file/plan_file/ledger_file`
- **Consumers** (никогда не конструируют имена сами): `DailySizeRotatingFileHandler`,
  `JsonReportRenderer.render_with_layout`, `write_plan_file_with_layout`,
  `ObservabilityRetentionSweeper`, `JsonlRunLedger`/`SqliteRunLedger`, `LatestArtifactPointerPublisher`

**Зачем**: исключает дрейф имён между write-side и read-side/retention; смена схемы именования —
в одном месте.

#### Паттерн 3: Pure Resolver с инъекцией времени (Strategy для clock)

**Где применяется**: `ObservabilityLayout._resolve_now` / `_clock` — время инъектируется
(`now=` или `clock=`), что делает имена детерминированными в тестах.

**Зачем**: чистота и детерминизм; `ObservabilityLayout` не дёргает `datetime.now()` неявно.

### Диаграмма зависимостей

```
config (ObservabilityConfig) ──projections──▶ Policy объекты
                                                   │
RuntimePaths (common) ──RuntimePathsLike──▶ ObservabilityLayout ◀── ServiceComponent / ComponentIdentity
                                                   │
                       ┌───────────────┬───────────┴──────────┬─────────────────┐
                       ▼               ▼                      ▼                 ▼
              infra/logging     infra/artifacts        infra/observability   delivery/cli
              (file paths)      (report/plan paths)    (ledger/retention/    (runtime wiring)
                                                        pointers paths)
```

---

## 🔑 Ключевые абстракции

### Интерфейсы/Порты

| Интерфейс | Назначение | Где используется |
|-----------|-----------|------------------|
| `RuntimePathsLike` (Protocol) | Минимальный контракт на runtime roots (`logs_root`/`reports_root`/`plans_root`) | `ObservabilityLayout` — чтобы не зависеть от конкретного `RuntimePaths` |

### Основные классы

| Класс | Роль | Ключевые методы |
|-------|------|-----------------|
| `ServiceComponent` (Enum) | Канонический ключ раскладки | значения `mapper/normalizer/enricher/matcher/resolver/planner/applier/cache/vault/topology/observability` |
| `ObservabilityArtifactKind` (Enum) | Тип артефакта для read-side/pointers | `LOG`/`REPORT`/`PLAN` |
| `ComponentIdentity` | Обёртка над компонентом (точка расширения идентичности при расколе на сервисы) | `component` |
| `ObservabilityLayoutPolicy` | Политика раскладки | `partition_by_component`, `clock` |
| `ObservabilityRedactionPolicy` | Политика redaction (потребляется logging) | `enabled`, `keys` |
| `ObservabilityLayout` | Чистый резолвер путей | `log_file()`, `report_file()`, `plan_file()`, `ledger_file()` |

---

## 🗂️ Модели данных

### Enum: `ServiceComponent`

**Назначение**: логический компонент сервиса — единственный ключ партиционирования всех артефактов.
Отвязан от имени CLI-команды (маппинг команда→компонент живёт в
[delivery/cli/component_mapping.py](../../../../connector/delivery/cli/component_mapping.py), см.
[observability-runtime.md](./observability-runtime.md)).

```python
class ServiceComponent(str, Enum):
    EXTRACTOR = "extractor"
    MAPPER = "mapper"
    NORMALIZER = "normalizer"
    ENRICHER = "enricher"
    MATCHER = "matcher"
    RESOLVER = "resolver"
    PLANNER = "planner"
    APPLIER = "applier"
    CACHE = "cache"
    VAULT = "vault"
    TOPOLOGY = "topology"
    OBSERVABILITY = "observability"   # для самих obs/maintenance команд
```

**Инварианты**: значение enum используется как имя подкаталога компонента и как суффикс имени файла;
поэтому значения — стабильные lower-case slug'и без пробелов.

### Enum: `ObservabilityArtifactKind`

```python
class ObservabilityArtifactKind(str, Enum):
    LOG = "log"
    REPORT = "report"
    PLAN = "plan"
```

**Использование**: read-side (`obs latest|tail` → какой артефакт показать) и latest-pointers
(`LOG → current.log`, `REPORT|PLAN → latest.json`).

### Dataclass: `ComponentIdentity`

```python
@dataclass(frozen=True)
class ComponentIdentity:
    component: ServiceComponent
```

**Назначение**: тонкая обёртка-идентичность. На текущем этапе содержит только `component`; это
**точка расширения** для будущего раскола на сервисы (например, добавление instance/host id), не
ломающая сигнатуры layout-методов (они принимают `ServiceComponent | ComponentIdentity`).

### Dataclass: `ObservabilityLayoutPolicy`

```python
@dataclass(frozen=True)
class ObservabilityLayoutPolicy:
    partition_by_component: bool = True   # var/logs/<component>/... vs flat var/logs/...
    clock: ClockMode = "utc"              # "utc" | "local" — TZ для имён файлов
```

### Dataclass: `ObservabilityRedactionPolicy`

```python
@dataclass(frozen=True)
class ObservabilityRedactionPolicy:
    enabled: bool = True
    keys: tuple[str, ...] = DEFAULT_SENSITIVE_FIELD_KEYS  # из common/sanitize.py
```

**Назначение**: value-only политика для redaction логов; исполняется в
[observability-logging.md](./observability-logging.md) (`LogRedactionEngine`). Дефолтный набор
ключей — **единый** для логов и report-санитайзера (см. `DEFAULT_SENSITIVE_FIELD_KEYS`).

### Dataclass: `ObservabilityLayout`

```python
@dataclass(frozen=True)
class ObservabilityLayout:
    runtime_paths: RuntimePathsLike
    policy: ObservabilityLayoutPolicy = ObservabilityLayoutPolicy()
    clock: Callable[[], datetime] | None = None
```

**Lifecycle**:
1. **Создание**: в `config/projections.py::to_observability_layout()` из `AppConfig` (roots +
   policy). В runtime предоставляется DI-провайдером `observability.observability_layout` (Singleton).
2. **Использование**: все write/read/retention компоненты вызывают `*_file()` для получения `Path`.
3. **Завершение**: immutable, без teardown.

**Инварианты**:
- Методы возвращают `Path` и **не создают директории, не открывают файлы** (mkdir/IO — забота infra).
- Имя выводится только из `(component, policy, now)` — детерминировано при заданном `now`.

---

## 🎯 Canonical artifact layout

Якорь-справочник всей подсистемы. Все пути — относительно runtime roots (`logs_root` = `var/logs`,
`reports_root` = `reports`, `plans_root` = `var/plans` по умолчанию).

| Артефакт | Метод layout | Путь (`partition_by_component=true`) | Имя | Owner-doc |
|---|---|---|---|---|
| Лог | `log_file` | `var/logs/<component>/` | `<YYYY-MM-DD>_<component>.log` (+ size-rolls `.<n>.log`) | [logging](./observability-logging.md) |
| Отчёт | `report_file` | `reports/<component>/` | `<YYYY-MM-DDThh-mm-ss>_<component>.json` | [artifacts](./observability-artifacts.md) |
| План | `plan_file` | `var/plans/<component>/` | `<YYYY-MM-DDThh-mm-ss>_<component>.json` | [artifacts](./observability-artifacts.md) |
| Run ledger | `ledger_file` | `var/logs/<component>/` | `index.jsonl` или `index.sqlite3` | [artifacts](./observability-artifacts.md) |
| Latest pointer (log) | — (рядом с артефактом) | `var/logs/<component>/` | `current.log` | [artifacts](./observability-artifacts.md) |
| Latest pointer (report/plan) | — | `reports/<component>/`, `var/plans/<component>/` | `latest.json` | [artifacts](./observability-artifacts.md) |
| Retention markers | — | каталог компонента | `.retention.marker`, `.report-retention.marker`, `.plan-retention.marker`, `.ledger-retention.marker` | [artifacts](./observability-artifacts.md) |

**Замечания по именам**:
- Логи — **date** (день), потому что весь день append'ится один файл; отчёты/планы — **datetime до
  секунд**, потому что это per-run артефакты (сортируемо, видно последний, без коллизий).
- Ledger **не зависит от времени запуска** — один индекс на всю историю компонента, лежит рядом с логами.
- При `partition_by_component=false` компонентный подкаталог опускается (всё в корне root'а).
- Имена в **UTC** по умолчанию (политика `clock`).

---

## 📊 Ключевые методы и алгоритмы

> Методы layout короткие и без сложных алгоритмов; ключевое — детерминизм и единообразие имён.

### Метод: `ObservabilityLayout.report_file()` / `plan_file()` / `log_file()` / `ledger_file()`

**Расположение**: `connector/common/observability.py`

**Алгоритм** (общий для `report_file`/`plan_file`/`log_file`):
```
1. resolved_component = _coerce_component(component)   # ServiceComponent | ComponentIdentity → ServiceComponent
2. resolved_now       = _resolve_now(now)             # инъекция времени + TZ-нормализация по policy.clock
3. directory          = _component_dir(root, comp)    # root/<component> либо root (если partition off)
4. filename           = f"{resolved_now:<fmt>}_{comp.value}.<ext>"  # date для log, datetime для report/plan
5. return directory / filename
```

`ledger_file()` отличается: **не использует время** (`index.jsonl`/`index.sqlite3`), лежит в
`logs_root/<component>`.

`_resolve_now()` нормализует TZ: при `clock="utc"` naive-время трактуется как UTC, aware —
конвертируется в UTC; при `clock="local"` — приводится к локальной зоне.

**Инварианты**: возвращает `Path`, без I/O; имя детерминировано при заданном `now`.

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что | Зачем |
|------|-----------|-----------|-------|
| config | Зависимость (входящая) | `to_observability_layout/_layout_policy/_redaction_policy` | сборка layout/policy из `AppConfig` |
| infra/logging | Потребитель | `ObservabilityLayout.log_file`, `ObservabilityRedactionPolicy` | пути лог-файлов, ключи redaction |
| infra/artifacts | Потребитель | `report_file`/`plan_file` | пути отчётов/планов |
| infra/observability | Потребитель | `ledger_file`, `log_file().parent` | пути ledger, каталоги retention |
| delivery/cli | Потребитель/wiring | DI Singleton `observability_layout`, `ServiceComponent` | резолв компонента, проброс layout |

---

## 🔌 Контракты и границы

### Runtime-контракт

`ObservabilityLayout` — **чистый value-резолвер**:

```python
layout.report_file(ServiceComponent.PLANNER, now=dt) -> Path
# reports/planner/2026-06-04T12-30-15_planner.json
```

**Гарантии**:
- Никакого I/O (нет `mkdir`, нет открытия файлов).
- Имена выводятся только из `(component, policy, now)`.
- `component` принимает и `ServiceComponent`, и `ComponentIdentity` (через `_coerce_component`).

### Границы слоёв

**Разрешённые зависимости**:
- ✅ `observability.py` → stdlib, `connector.common.sanitize` (дефолтные ключи)

**Запрещённые зависимости**:
- ❌ `observability.py` → `connector/infra/*`, `connector/delivery/*`, `connector/usecases/*`
- ❌ любое file I/O / `datetime.now()` без инъекции

**Архитектурные тесты**: `tests/architecture/` (import boundaries, `lint-imports`).

**Визуальная граница**:
```
┌─────────────────────────────────────────┐
│ infra/logging · infra/artifacts ·        │  ← потребляют layout, делают I/O
│ infra/observability · delivery/cli       │
└────────────▲────────────────────────────┘
             │ uses (pure value API)
┌────────────┴────────────────────────────┐
│ common/observability.py (model)          │  ← identity + naming policy, no I/O
└──────────────────────────────────────────┘
```

---

## 💡 Типичные сценарии

### Сценарий 1: получить путь отчёта для компонента

```python
layout = to_observability_layout(app_config)
path = layout.report_file(ServiceComponent.ENRICHER, now=finished_at)
# reports/enricher/2026-06-04T12-30-15_enricher.json
```

**Объяснение**: write-side (renderer) и read-side (ledger/viewer) используют один и тот же метод →
пути гарантированно совпадают.

### Сценарий 2: отключить партиционирование

```python
policy = ObservabilityLayoutPolicy(partition_by_component=False)
# var/logs/2026-06-04_planner.log  (без подкаталога planner/)
```

---

## 📌 Важные детали

### Особенности реализации

- **`ledger_file` намеренно вне времени** — индекс обслуживает всю историю компонента.
- **`ComponentIdentity` как точка расширения** — позволяет в будущем добавить instance/host id,
  не меняя сигнатуры layout.

### 🚨 Failure Modes

| Исключение | Условие | Поведение | Как обработать |
|------------|---------|-----------|----------------|
| (нет) | — | Модуль чистый; ошибок не порождает | Невалидные команды отлавливает `component_for_command` в delivery (см. [runtime](./observability-runtime.md)) |

### ⚠️ Инварианты системы

1. **Инвариант: layout — единственный владелец имён**
   - **Что**: имена `<component>/<...>_<component>.<ext>` создаются только в `ObservabilityLayout`.
   - **Почему важно**: исключает рассинхрон write-side ↔ read-side/retention.
   - **Где проверяется**: code review + отсутствие naming-логики в `runtime_paths.py` (только roots).
2. **Инвариант: чистота (no I/O)**
   - **Что**: методы возвращают `Path`, ничего не создают/не открывают.
   - **Почему важно**: тестируемость, отсутствие side effects.
3. **Инвариант: детерминизм при заданном `now`**
   - **Что**: один и тот же `(component, policy, now)` → один и тот же путь.
   - **Почему важно**: тесты и корреляция write/read путей.

### ⏱️ Performance заметки

Операции O(1), без I/O — узких мест нет.

### Частые ошибки

- ❌ Конструировать имя артефакта вручную в infra/delivery.
- ✅ Всегда через `ObservabilityLayout.*_file()`.

---

## 🔗 Связанные документы

- [Observability Config](./observability-config.md) — декларативная конфигурация (вместо DSL)
- [Observability Logging](./observability-logging.md) — потребитель layout (лог-файлы, redaction)
- [Observability Artifacts](./observability-artifacts.md) — отчёты/планы/ledger/retention/pointers
- [Observability Runtime](./observability-runtime.md) — wiring, ServiceComponent ↔ команды
- ADR: `docs/adr/observability/OBSERVABILITY-DEC-002-per-component-prod-observability-layout.md` (почему)

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-06 | Создан документ (DEC-002, Stages 1–6) | xorex-LC |
