# Topology Runtime (Bootstrap & Activation)

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
  - [Жизненный цикл bootstrap](#жизненный-цикл-bootstrap)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [📊 Activation matrix](#-activation-matrix)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [📌 Важные детали](#-важные-детали)
  - [🚨 Failure Modes](#-failure-modes)
  - [⚠️ Инварианты системы](#️-инварианты-системы)
- [🛠️ Как расширять](#️-как-расширять)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Связать всю подсистему в единый runtime-шаг, который выполняется **до** основного pipeline-handler-а: решить, нужна ли topology данной команде/датасету, собрать артефакты (target snapshot, source validation state), опубликовать report-контекст и решить, продолжать ли выполнение.

**Ключевая ответственность**: Разделить **build** (построение topology-артефактов — usecase-слой) и **wire** (сборку конкретных адаптеров из DI-контейнера + CLI-lifecycle — delivery-слой). Это связующее звено между [DSL](./topology-dsl.md)/[core](./topology-core.md) и [consumers](./topology-consumers.md).

**Расположение в кодовой базе**:
- Build (usecases): [connector/usecases/topology_bootstrap.py](../../../../connector/usecases/topology_bootstrap.py), [topology_target_build.py](../../../../connector/usecases/topology_target_build.py), [topology_source_validation.py](../../../../connector/usecases/topology_source_validation.py)
- Wire (delivery): [connector/delivery/cli/runtime/topology_bootstrap.py](../../../../connector/delivery/cli/runtime/topology_bootstrap.py)

> **Почему bootstrap до pipeline** — зафиксировано в [ADR TRANSFORM-DEC-010](../../../adr/transform/TRANSFORM-DEC-010-topology-bootstrap-before-main-pipeline.md): topology должна быть готова к первой же строке match/resolve, иначе пришлось бы строить граф лениво в середине стрима.

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
usecases/                              # BUILD (storage-agnostic, без CLI)
├── topology_bootstrap.py
│   ├── TopologyRequirementResolver    # activation decision из command + policy
│   ├── TopologyBootstrapUseCase       # spec load → compile → target build → source validate
│   ├── TopologyActivationDecision     # результат resolver-а
│   ├── TopologyRuntimeBinding         # run-scoped binding (provider + artifacts + errors)
│   ├── StaticTopologyProvider         # snapshot-only TopologyProviderPort
│   └── TraceToSink                    # domain trace → TopologyEventSink (DEBUG)
├── topology_target_build.py           # TargetTopologyBuildUseCase (read→build→readiness)
└── topology_source_validation.py      # SourceTopologyValidationUseCase (Stage G pre-pass)

delivery/cli/runtime/                  # WIRE (DI + CLI lifecycle)
└── topology_bootstrap.py
    ├── TopologyBootstrapStep          # оркестрирует pre-handler шаг
    ├── attach_topology_runtime        # кладёт binding в command context.extra
    ├── _build_target_usecase          # собирает reader/builder/readiness из container
    └── _build_source_validation_usecase
```

### 🎭 Применённые паттерны

#### Паттерн 1: Build vs Wire (composition root отделён от бизнес-оркестрации)

**Где применяется**: `TopologyBootstrapUseCase` (usecases) знает *что* сделать (загрузить spec, скомпилировать, построить target, провалидировать source) и принимает фабрики через конструктор. `TopologyBootstrapStep` (delivery) знает *как* собрать конкретные адаптеры из `container` и встроиться в CLI-lifecycle.

**Реализация**:
- **Build**: `TopologyBootstrapUseCase(target_usecase_factory=..., source_validation_usecase_factory=..., event_sink=...)`
- **Wire**: `_build_target_usecase(container, ...)` / `_build_source_validation_usecase(container, ...)` передаются как фабрики

**Зачем**: usecase тестируется с fake-фабриками (см. `tests/unit/usecases/test_topology_bootstrap.py`), а delivery — интеграционно с реальным DI. Граница `usecases → infra` не нарушается: адаптеры собираются в delivery и приходят в usecase как готовые объекты.

#### Паттерн 2: Pre-handler step с short-circuit

**Где применяется**: `TopologyBootstrapStep.run()` возвращает `TopologyBootstrapStepResult`, у которого `command_result` непуст ⟺ нужно прервать команду (capability conflict, missing cache spec, required target failure).

**Зачем**: фатальная topology-ошибка должна остановить команду **до** обработки строк, единой catalog-диагностикой, а не сырым `ValueError` на поздней сборке стадии.

#### Паттерн 3: Snapshot-only provider + context injection

**Где применяется**: построенные snapshot-ы заворачиваются в `StaticTopologyProvider` и кладутся в `command context.extra["topology_runtime"]` через `attach_topology_runtime`. Стадии достают binding оттуда.

**Зачем**: provider read-only и run-scoped; стадии получают topology через контекст, а не через глобальное состояние.

### Жизненный цикл bootstrap

```
CLI команда (match / resolve / import-plan / mapping / …)
        │
        ▼
TopologyBootstrapStep.run()
        │
        ├─ TopologyRequirementResolver.resolve(command, dataset)  ──► TopologyActivationDecision
        │        │
        │        ├─ activation_error?  ──► short-circuit: TOPOLOGY_CAPABILITY_DISABLED (exit≠0)
        │        ├─ not activated?     ──► skip-binding (status=skipped), handler выполняется как обычно
        │        └─ activated          ──► продолжить
        │
        ├─ TopologyBootstrapUseCase.run(request, target_failure_is_hard)
        │        ├─ spec.loaded → canonicalizer.compiled
        │        ├─ require_target → TargetTopologyBuildUseCase.build() → readiness.evaluated
        │        └─ require_source → SourceTopologyValidationUseCase.validate() → source.validation.finish
        │
        ├─ artifacts? → StaticTopologyProvider(source?, target?)
        ├─ report_sink.emit(SetContextEvent(TOPOLOGY, binding.report_context_payload()))
        │
        └─ errors? → short-circuit (CommandResult с диагностикой)
                 │
                 ▼
        attach_topology_runtime(ctx, binding)  → handler видит ctx.extra["topology_runtime"]
```

---

## 🔑 Ключевые абстракции

### Основные классы

| Класс | Слой | Роль |
|-------|------|------|
| `TopologyRequirementResolver` | usecases | Материализует `TopologyActivationDecision` из command checkpoint + policy |
| `TopologyBootstrapUseCase` | usecases | Оркестрирует spec→compile→target build→source validate; эмитит lifecycle-события |
| `TargetTopologyBuildUseCase` | usecases | read hierarchy → `TargetHierarchyTopologyBuilder` → `TopologyTargetReadinessEvaluator` |
| `SourceTopologyValidationUseCase` | usecases | source projection + target membership → `anchor_source_nodes` (Stage G) |
| `StaticTopologyProvider` | usecases | `TopologyProviderPort` поверх готовых snapshot-ов |
| `TopologyBootstrapStep` | delivery | Pre-handler шаг: resolve → build → wire → short-circuit-решение |
| `attach_topology_runtime` | delivery | Кладёт `TopologyRuntimeBinding` в `context.extra` |

---

## 🗂️ Модели данных

### `TopologyActivationDecision`
Решение resolver-а. `activated` (property) истинно ⟺ `capability_enabled && activation_sources && require_target_topology`.
```python
@dataclass(frozen=True)
class TopologyActivationDecision:
    request: TopologyBootstrapRequest
    capability_enabled: bool
    activation_sources: tuple[str, ...]        # ("match",) / ("resolve",) / ("source_validation",) / комбинации
    target_failure_is_hard: bool
    skipped_reason: str | None = None
    activation_error: str | None = None        # конфликт: policy on, capability off
```

### `TopologyRuntimeBinding`
Run-scoped результат, который видит handler. Несёт `provider`, `artifacts`, `errors/warnings`, `activation_sources`. Методы:
- `to_runtime_requirements()` → `TopologyRuntimeRequirements` (для composition стадий);
- `report_context_payload()` → dict для `ReportContextKey.TOPOLOGY` (`status`, `built_sides`, `errors`, `source_validation`, `topology_normalization_version`, …).

### `TopologyRunArtifacts`
`source_snapshot?`, `target_snapshot?`, `source_validation: SourceTopologyValidationState?`, `source_validation_summary`, `metadata: TopologyBuildMetadata` (provenance: `cache_snapshot_revision`, `built_at`, `topology_normalization_version`).

---

## 📊 Activation matrix

Источник истины о vocabulary — `TOPOLOGY_PIPELINE_COMMANDS` в [topology_bootstrap.py](../../../../connector/usecases/topology_bootstrap.py). Это **имена команд** (`app.py`), не значения checkpoint.

| Команда | Capability видна? | Bootstrap? | `activation_sources` | Примечание |
|---------|-------------------|------------|----------------------|------------|
| вне pipeline (`cache`, `vault-…`) | нет | нет | `()` | `skipped_reason=command_not_supported` |
| `mapping` / `normalize` / `enrich` | да (если capability on) | **нет** | `()` | до topology-consumer-а; `checkpoint_before_topology_consumer` |
| `match` | да | да, если `match.topology.enabled` | `("match",)` | `on_missing_topology=hard_error` → target failure фатален |
| `resolve` | да | да, если `resolve.topology_link.enabled` и/или source-validation | `("resolve",)` / `("source_validation",)` / обе | target dataset берётся из link-rule |
| `import-plan` | да | да, если включён match и/или resolve | объединение | прогон всего пайплайна |

**Capability vs policy:**
- **capability** = `dataset_dsl.topology.enabled` — включена ли подсистема для датасета.
- **policy** = `match.topology.enabled` / `resolve.topology_link.enabled` — хочет ли стадия потреблять сигнал.
- **Конфликт** (policy on, capability off) → `activation_error` → short-circuit `TOPOLOGY_CAPABILITY_DISABLED`. Это **не** graceful skip: неправильную конфигурацию ловим громко.

**Source validation** активируется на `resolve`/`import-plan`, только если `topology.source.mode == adjacency_list` (self-referential датасет). Она всегда `target_failure_is_hard=True`.

---

## 📊 Ключевые методы и алгоритмы

### `TopologyRequirementResolver.resolve()`

**Расположение**: [topology_bootstrap.py:317](../../../../connector/usecases/topology_bootstrap.py#L317)

```
1. normalize command; ∉ pipeline → decision(command_not_supported)
2. load capability
3. pre-match команда → decision(не активна; reason = checkpoint_before_topology_consumer | capability_disabled)
4. собрать match_policy / resolve_policy / source_validation_policy (по команде)
5. FOR каждого включённого consumer:
     capability on?  → добавить source в activation_sources, обновить topology_dataset
     capability off? → вернуть activation_error (short-circuit later)
   - конфликт topology_dataset между consumer-ами → ValueError (мисконфиг)
6. activated = bool(activation_sources)
   require_source_topology = "source_validation" in activation_sources
   require_target_topology = activated
```

**Инвариант**: match и resolve, если оба включены, обязаны указывать на **один** topology dataset — иначе `ValueError` (нельзя строить два разных target-графа за run).

### `TopologyBootstrapUseCase.run()`

**Расположение**: [topology_bootstrap.py:582](../../../../connector/usecases/topology_bootstrap.py#L582)

Эмитит фиксированную последовательность событий: `bootstrap.start` → `spec.loaded` → `canonicalizer.compiled` → (`readiness.evaluated`/`readiness.empty`/`readiness.stale`) → (`target.build.finish`) → (`source.validation.finish`) → `bootstrap.finish`. Артефакты собираются только если `target_ready && not errors`.

### `TopologyBootstrapStep.run()` (short-circuit logic)

**Расположение**: [delivery/cli/runtime/topology_bootstrap.py:83](../../../../connector/delivery/cli/runtime/topology_bootstrap.py#L83)

Три точки short-circuit (все эмитят `bootstrap.short_circuit` и возвращают непустой `command_result`):
1. `decision.activation_error` → `TOPOLOGY_CAPABILITY_DISABLED`;
2. `_TopologyBootstrapConfigurationError` из фабрик (`TOPOLOGY_TARGET_CACHE_SPEC_MISSING` / `TOPOLOGY_DSL_SPEC_INVALID`);
3. `result.errors` непуст (например `TOPOLOGY_TARGET_EMPTY` при `require_target`).

Иначе binding (с provider или skip-reason) кладётся в контекст, handler продолжается.

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что |
|------|-----------|-----------|
| DSL | загрузка | `load_topology_spec_for_dataset`, `load_match/resolve/source/mapping_spec_for_dataset` |
| Core | использует | builders, `TopologyTargetReadinessEvaluator`, `anchor_source_nodes` |
| Infra | wire | `SqliteTopologyTargetReader`, `…MembershipReader`, `PolarsSourceAdjacencyReader`, `StructlogTopologyEventSink` |
| Cache (DI) | читает | `container.cache.roles().topology_read`, `cache_dsl().cache_specs` |
| Reporting | публикует | `SetContextEvent(ReportContextKey.TOPOLOGY, …)` |
| Consumers | поставляет | `TopologyRuntimeBinding` в `context.extra["topology_runtime"]` |

---

## 🔌 Контракты и границы

**Разрешено**:
- ✅ usecases → `domain/*`, фабрики (передаются извне)
- ✅ delivery runtime → `usecases`, `infra`, `container` (composition root)

**Запрещено**:
- ❌ `usecases/topology_*` → `infra/*` напрямую (адаптеры приходят через фабрики из delivery)
- ❌ `usecases/topology_*` → `typer`/`polars`/`httpx`/`dependency_injector` (контракт `core layers stay free of IO/CLI/DI libraries`)

**Архитектурные тесты**: `usecases must not depend on infra or delivery` + `core layers stay free of …` в [pyproject.toml](../../../../pyproject.toml).

---

## 📌 Важные детали

### 🚨 Failure Modes

| Код | Условие | Тип |
|-----|---------|-----|
| `TOPOLOGY_CAPABILITY_DISABLED` | policy on, capability off | short-circuit (exit≠0) |
| `TOPOLOGY_TARGET_CACHE_SPEC_MISSING` | нет cache spec для topology dataset | short-circuit (configuration) |
| `TOPOLOGY_DSL_SPEC_INVALID` | source validation требует `adjacency_list`, а в spec другой mode | short-circuit (configuration) |
| `TOPOLOGY_TARGET_EMPTY` / `TOPOLOGY_TARGET_STALE` | readiness не прошёл при `require_target` | short-circuit (data/freshness) |
| `ValueError` (мисконфиг) | match и resolve указывают на разные topology dataset | падает в resolver (баг конфигурации) |

### ⚠️ Инварианты системы

1. **Текущая фаза — target-only build** (+ опциональная source validation). `source_snapshot` в артефактах сейчас `None`; provider может вернуть source как `None` (consumers Phase 1a/1b работают от row-level локатора, не от source snapshot).
2. **`TopologyBootstrapStepResult.inactive(requirements)`** сохраняет единый контракт результата (включая `requirements`), чтобы вызывающий код не ловил `AttributeError` на разных формах.
3. **`target_failure_is_hard`** прокидывается из policy (`on_missing_topology=hard_error`) и source-validation (всегда hard) — определяет, является ли readiness-провал фатальным.
4. **Один topology dataset на run** — гарантируется resolver-ом.

---

## 🛠️ Как расширять

### Добавить новый activation-источник (новый consumer)

1. Добавить команду/policy в соответствующее подмножество (`_MATCH_ACTIVATING_COMMANDS` и т.п.) и в `resolve()`.
2. Дополнить `activation_sources` новым тегом, при необходимости — `require_source_topology`.
3. Согласовать `topology_dataset` (инвариант: один граф на run).
4. Покрыть `tests/unit/usecases/test_topology_bootstrap.py` (activation matrix).

### Включить source-snapshot build (будущая фаза)

`TopologyBootstrapUseCase` уже умеет `require_source_topology`; нужно подключить `SourcePathTopologyBuilder` в build-path и заполнить `source_snapshot` в артефактах.

---

## 🔗 Связанные документы

- [Topology Consumers](./topology-consumers.md) — кто потребляет binding из контекста
- [Topology Core](./topology-core.md) — builders/readiness/anchoring, которые здесь оркестрируются
- [Topology Infra](./topology-infra.md) — адаптеры, собираемые фабриками
- [Topology DSL](./topology-dsl.md) — capability vs policy
- [ADR TRANSFORM-DEC-010](../../../adr/transform/TRANSFORM-DEC-010-topology-bootstrap-before-main-pipeline.md) — почему bootstrap до основного pipeline
