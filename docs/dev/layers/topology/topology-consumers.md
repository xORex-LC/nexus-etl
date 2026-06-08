# Topology Consumers (Match / Resolve / Source Validation)

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
  - [Основные компоненты](#основные-компоненты)
  - [🎭 Применённые паттерны](#-применённые-паттерны)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [💡 Две возможности](#-две-возможности)
  - [Возможность 1: FK matching/resolve (Phase 1a/1b)](#возможность-1-fk-matchingresolve-phase-1a1b)
  - [Возможность 2: Source anchoring validation (Stage G)](#возможность-2-source-anchoring-validation-stage-g)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [📌 Важные детали](#-важные-детали)
- [🛠️ Как расширять](#️-как-расширять)
- [🔗 Связанные документы](#-связанные-документы)

---

## 📋 Обзор

**Назначение**: Описать *потребителей* topology — стадии и сервисы, которые используют готовые артефакты (`TopologyProviderPort`, `SourceTopologyValidationState`) для уточнения match/resolve и для отсева незаякоренных source-строк.

**Ключевая ответственность**: Адаптировать общий comparison core ([topology-core](./topology-core.md)) к контрактам стадий и применить row-level verdicts Stage G. Consumers — это **refinement-слой**: они не заменяют identity/fuzzy-matching, а уточняют его topology-сигналом.

**Расположение в кодовой базе**:
- Match consumer: [connector/usecases/topology_match.py](../../../../connector/usecases/topology_match.py)
- Resolve consumer: [connector/usecases/topology_resolve.py](../../../../connector/usecases/topology_resolve.py)
- Source filter stage: [connector/domain/transform/stages/source_topology_filter.py](../../../../connector/domain/transform/stages/source_topology_filter.py)
- Source validation pre-pass: [connector/usecases/topology_source_validation.py](../../../../connector/usecases/topology_source_validation.py)

---

## 🏗️ Архитектура слоя

### Основные компоненты

```
usecases/
├── topology_match.py
│   ├── SourceTopologyLocatorBuilder    # SourceRecord → SourceTopologyCanonicalPath (row-level)
│   ├── TopologyMatchService            # ladder → TopologyMatchResult
│   └── build_topology_match_service / build_source_locator_builder  # null-safe фабрики
└── topology_resolve.py
    ├── TopologyLinkResolutionService   # ladder → TopologyLinkResolutionResult
    └── build_topology_link_resolution_service

domain/transform/stages/
└── source_topology_filter.py           # SourceTopologyFilterStage (Stage G, row-level применение)
```

### 🎭 Применённые паттерны

#### Паттерн 1: Adapter поверх shared comparison core

**Где применяется**: и `TopologyMatchService`, и `TopologyLinkResolutionService` вызывают один `compare_topology_candidates`, отличаясь только compiled-policy (ladder) и формой результата.

**Зачем**: единая объяснимая логика сравнения (DRY) — match и resolve не расходятся в трактовке topology.

#### Паттерн 2: Null-safe factory (graceful degradation)

**Где применяется**: `build_topology_match_service(snapshot, policy)` возвращает `None`, если snapshot отсутствует или policy выключена. Стадия, получив `None`, просто не применяет topology-уточнение.

**Зачем**: topology опциональна на уровне строки; отсутствие графа не должно ронять стадию (если policy не `hard_error`).

#### Паттерн 3: Pre-pass + row-level apply (для Stage G)

**Где применяется**: тяжёлая работа (проекция source, anchoring) выполняется один раз в bootstrap (`SourceTopologyValidationUseCase`), а `SourceTopologyFilterStage` лишь применяет готовый `dropped`-set построчно, создавая диагностику с актуальным `row_ref`.

**Зачем**: anchoring — graph-global операция; делать её на каждую строку бессмысленно. Стадия остаётся дешёвой и stateless.

---

## 🔑 Ключевые абстракции

### Основные классы

| Класс | Порт | Роль |
|-------|------|------|
| `SourceTopologyLocatorBuilder` | `SourceTopologyLocatorBuilderPort` | Из `SourceRecord` собрать canonical путь по настроенным path-колонкам |
| `TopologyMatchService` | `TopologyMatchServicePort` | Применить ladder к candidate ids → `TopologyMatchResult` |
| `TopologyLinkResolutionService` | `TopologyLinkResolutionServicePort` | Применить ladder к link-candidate ids → `TopologyLinkResolutionResult` |
| `SourceTopologyFilterStage` | — (StageContract) | Применить `dropped`-verdicts к mapped stream |

---

## 💡 Две возможности

### Возможность 1: FK matching/resolve (Phase 1a/1b)

**Задача**: у строки сотрудника есть `org_path` (имя/путь подразделения), а в target — id. Нужно сопоставить имя ↔ id, особенно когда identity/fuzzy дали несколько кандидатов.

**Поток (row-level, без полного source snapshot)**:
```
SourceRecord
  │  SourceTopologyLocatorBuilder.build()   (canonicalize_segments, отбросить пустые)
  ▼
SourceTopologyCanonicalPath
  │  + target_candidate_ids (от identity/fuzzy)
  ▼
TopologyMatchService.compare()  /  TopologyLinkResolutionService.resolve_link()
  │  → compare_topology_candidates(snapshot, segments, candidates, ladder)
  ▼
TopologyMatchResult / TopologyLinkResolutionResult
  → match: disambiguation (apply_on=ambiguous_only|all_candidates)
  → resolve: материализация FK в desired_state (в ResolveStage), либо pending/ambiguous по policy
```

**Ключевое**:
- **Row-level**, а не source-snapshot: локатор строится из перечисленных в `path_columns` колонок текущей строки. Полный source граф для Phase 1a/1b не нужен (это зафиксировано в activation: `require_source_topology=False` для match/resolve).
- **Refinement, не замена**: match подаёт topology только как уточнение (`apply_on=ambiguous_only` — лишь когда identity/fuzzy неоднозначны).
- **FK материализуется только в ResolveStage** — `TopologyLinkResolutionService` возвращает `resolved_target_id`, но сам не пишет payload. `is_pending=False` на этом уровне; pending/ambiguous-политику применяет `ResolveCore` по `on_missing_topology`/`on_ambiguous_topology`.

### Возможность 2: Source anchoring validation (Stage G)

**Задача**: для self-referential датасета (organizations: id/parent_id) — отсечь строки, чьё подразделение не привязывается к target-иерархии (родитель не существует ни в source, ни в target).

**Поток (pre-pass + row-level apply)**:
```
[bootstrap]  SourceTopologyValidationUseCase.validate()
   PolarsSourceAdjacencyReader.read_nodes()  ─┐
   SqliteTopologyTargetMembershipReader.read_target_ids()  ─┤
                                                ▼
                          anchor_source_nodes(nodes, target_ids)
                                                ▼
                          SourceTopologyValidationState(dropped, on_unanchored, node_id_field)
                                                │  (в TopologyRunArtifacts → context)
[pipeline]   SourceTopologyFilterStage.run(mapped_stream)
   FOR EACH mapped row:
     node_id = row[node_id_field]
     verdict = dropped.get(node_id)
     verdict? → DiagnosticItem(TOPOLOGY_SOURCE_UNANCHORED, row_ref=...) по policy:
        warn       → add_warning_item (строка остаётся)
        skip/hard  → set_row(None) + add_error_item (строка выбывает)
```

**Ключевое**:
- **Forward-reference валиден** — родитель, идущий позже в том же батче, не делает строку незаякоренной (anchoring видит весь батч). Такие связи штатно уходят в pending-механизм resolve.
- **Permanently-unanchorable отсекается** — родителя нет нигде → `missing_parent` → drop поддерева.
- **Диагностика стадии** тегается `DiagnosticStage.TOPOLOGY_VALIDATE` с реальным `row_ref`; bootstrap-уровневые (duplicate, hard_error) тегаются там же, но без row_ref.

---

## 📊 Ключевые методы и алгоритмы

### `SourceTopologyLocatorBuilder.build()`

**Расположение**: [topology_match.py:44](../../../../connector/usecases/topology_match.py#L44)

```
raw = [record.values.get(f) for f in path_fields]
segments = canonicalizer.canonicalize_segments([str(v or "") for v in raw])
segments = [s for s in segments if s.strip()]     # отбросить пустые уровни
return None if not segments else SourceTopologyCanonicalPath(segments)
```
> `None` означает «нет topology-сигнала для строки» — consumer пропускает уточнение.

### `SourceTopologyFilterStage.run()`

**Расположение**: [source_topology_filter.py:43](../../../../connector/domain/transform/stages/source_topology_filter.py#L43)

```
IF validation is None OR not validation.dropped → yield всё как есть (no-op)
FOR EACH result IN source:
   row is None → pass-through (стадия выше уже пометила failed)
   node_id отсутствует/пустой → pass-through
   verdict = dropped.get(node_id); None → pass-through
   factory = build_warning if on_unanchored=="warn" else build_error
   diag = factory(TOPOLOGY_SOURCE_UNANCHORED, row_ref=result.row_ref, details={node_id, reason, broken_at_parent_id})
   warn → builder.add_warning_item(diag)
   else → builder.set_row(None); builder.add_error_item(diag)
```

**Edge cases**: stage no-op, если нечего отсекать (нет `dropped`) — нулевая стоимость для датасетов без Stage G.

---

## 🔄 Взаимодействие с другими слоями

| Слой | Тип связи | Через что |
|------|-----------|-----------|
| Topology Core | использует | `compare_topology_candidates`, `TopologyQueryPort` |
| Topology Ports | реализует | service-порты, `SourceTopologyLocatorBuilderPort` |
| Topology Runtime | получает | `TopologyProviderPort`/`SourceTopologyValidationState` из binding |
| Match/Resolve DSL | конфигурируется | `TopologyMatchPolicy`, `ResolveTopologyLinkPolicy` (compiled ladder) |
| Match Core / Resolve Core | встраивается | disambiguation / FK materialization |
| Diagnostics | эмитит | `TOPOLOGY_SOURCE_UNANCHORED` |

---

## 🔌 Контракты и границы

**Разрешено**:
- ✅ consumers → `domain/dependency_tree` (core), `domain/ports/topology`, compiled policies
- ✅ `SourceTopologyFilterStage` (domain) → `TransformResult`, `SourceTopologyValidationState`, catalog

**Запрещено**:
- ❌ consumers → `infra/*` (snapshot/validation приходят через provider/binding)
- ❌ `SourceTopologyFilterStage` повторно читает source или строит граф — он применяет precomputed verdicts
- ❌ материализация FK в match-сервисе (это работа ResolveStage)

**Архитектурные тесты**: `core layers stay free of …` и `usecases must not depend on infra` ([pyproject.toml](../../../../pyproject.toml)).

---

## 📌 Важные детали

### ⚠️ Инварианты системы

1. **Refinement, не замена** — topology уточняет identity/fuzzy, не подменяет их. `apply_on=ambiguous_only` — дефолтный режим.
2. **FK материализуется только в ResolveStage** — match/resolve-сервисы возвращают результат, payload пишет `ResolveCore`.
3. **Locator `None` ⟹ no-op** — отсутствие topology-сигнала на строке не ошибка.
4. **Stage G — pre-pass + apply** — anchoring выполняется один раз; стадия stateless и дешёва.
5. **Диагностика с реальным `row_ref`** — `SourceTopologyFilterStage` создаёт row-level `DiagnosticItem`, потому что только у него есть актуальный `row_ref` (DTO `SourceTopologyValidationState` его не хранит).

### Частые ошибки

- ❌ Строить source snapshot ради Phase 1a/1b — не нужно, работает row-level локатор.
- ❌ Материализовать FK в `TopologyLinkResolutionService` — нарушает разделение match/resolve.
- ✅ Включать topology-policy только вместе с `topology.enabled` capability — иначе `TOPOLOGY_CAPABILITY_DISABLED`.

---

## 🛠️ Как расширять

### Добавить нового consumer-а topology

1. Объявить service-порт в [services.py](../../../../connector/domain/ports/topology/services.py).
2. Реализовать адаптер поверх `compare_topology_candidates` (как match/resolve).
3. Добавить null-safe фабрику (`build_*`), возвращающую `None` при отсутствии snapshot/policy.
4. Зарегистрировать activation-источник в resolver ([topology-runtime](./topology-runtime.md)).

### Изменить поведение Stage G по policy

`on_unanchored` (`skip`/`warn`/`hard_error`) задаётся в `topology.source` ([topology-dsl](./topology-dsl.md)); `hard_error` дополнительно поднимает bootstrap-уровневые диагностики в `SourceTopologyValidationUseCase`.

---

## 🔗 Связанные документы

- [Topology Core](./topology-core.md) — `compare_topology_candidates`, `anchor_source_nodes`
- [Topology Runtime](./topology-runtime.md) — откуда берутся provider и validation state
- [Topology DSL](./topology-dsl.md) — policy (`match.topology`, `resolve.topology_link`, `on_unanchored`)
- [Resolve Core](../resolver/resolve-core.md) — FK materialization / pending lifecycle
- [ADR TRANSFORM-DEC-010](../../../adr/transform/TRANSFORM-DEC-010-topology-bootstrap-before-main-pipeline.md)
