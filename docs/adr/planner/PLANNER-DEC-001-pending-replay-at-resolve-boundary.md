# PLANNER-DEC-001: Pending replay на границе ResolveUseCase + десериализация в доменном слое (pending_codec)

> **Статус**: Закрыто
> **Дата принятия**: 2026-02-23
> **Решает проблему**: [PLANNER-PROBLEM-001](./PLANNER-PROBLEM-001-pending-replay-infra-leak.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

`ImportPlanService` содержит ~200 строк JSON-десериализации pending строк (`_load_pending_rows`, `_deserialize_pending_matched_row`, `_deserialize_match_decision` и т.д.) и фантомный порт `PendingReplayPort`, который является нулевым алиасом `ResolveRuntimePort`. Pending replay — это resolve-concern: строки создаются resolve-стадией и потребляются ею же на следующем прогоне. Подробнее: [PLANNER-PROBLEM-001](./PLANNER-PROBLEM-001-pending-replay-infra-leak.md).

---

## 🎯 Решение

1. **Десериализация pending — в доменный модуль `pending_codec.py`.** Новый модуль `connector/domain/transform/resolver/pending_codec.py` инкапсулирует симметричную пару: рядом с `_serialize_pending_payload()` из `resolve_core.py` появляется `load_pending_rows(pending_rows: list[PendingRow]) -> list[TransformResult[MatchedRow]]`. Весь JSON-разбор (`_deserialize_*`) перемещается туда. Порт (`ResolveRuntimePort`) остаётся без изменений — `list_pending_rows()` возвращает `list[PendingRow]` как прежде.

2. **Pending replay — в `ResolveUseCase`.** `ResolveUseCase.iter_resolved()` получает опциональный параметр `pending_replay: ResolveRuntimePort | None = None`. Если передан — вызывает `pending_replay.list_pending_rows(dataset)`, затем `pending_codec.load_pending_rows()` для десериализации, и chain-ит результат с `matched_source`. Для команд match/resolve передаётся `None`.

3. **`PendingReplayPort` — удалить.** `ImportPlanService` передаёт `planning_runtime: PlanningRuntimePort` напрямую в `ResolveUseCase` (он наследует `ResolveRuntimePort`, значит имеет `list_pending_rows()`).

4. **`ImportPlanService` упрощается.** Параметр `pending_replay` удаляется. Все `_deserialize_*` функции удаляются. `import_plan_service.py` становится чистым оркестратором без знания о форматах хранилища.

---

## 🏗️ Архитектурное решение

### Новый модуль `pending_codec.py`

```python
# connector/domain/transform/resolver/pending_codec.py

@dataclass
class PendingLoadResult:
    rows: list[TransformResult[MatchedRow]]
    skipped: int   # количество записей, пропущенных из-за невалидного payload


def load_pending_rows(
    pending_rows: list[PendingRow],
) -> PendingLoadResult:
    """
    Десериализует список PendingRow → PendingLoadResult(rows, skipped).
    Симметричная пара _serialize_pending_payload() из resolve_core.py.
    Невалидные записи пропускаются; их количество возвращается в skipped.
    Caller (ResolveUseCase) решает, как реагировать на skipped > 0 (лог/диагностика).
    """
    results = []
    skipped = 0
    for pending in pending_rows:
        parsed = _deserialize_pending_matched_row(pending.payload)
        if parsed is None:
            skipped += 1
            continue
        matched_row, meta = parsed
        row_ref = matched_row.row_ref
        record = SourceRecord(line_no=row_ref.line_no, record_id=row_ref.row_id, values={})
        results.append(TransformResult(record=record, row=matched_row, row_ref=row_ref,
                                       match_key=None, meta=meta, secret_candidates={},
                                       errors=[], warnings=[]))
    return PendingLoadResult(rows=results, skipped=skipped)
```

Зависимости модуля: только `domain` типы (`PendingRow`, `MatchedRow`, `TransformResult`, `SourceRecord`) и `json` из stdlib. Инфраструктурных импортов нет.

> **Наблюдаемость**: `pending_codec` считает, но не логирует — он не знает о logger/structlog. Логирование `skipped > 0` — ответственность `ResolveUseCase` (см. ниже).

### Контракт порта — без изменений

```python
# connector/domain/ports/cache/roles.py — НЕ меняется

class ResolveRuntimePort(Protocol):
    ...
    def list_pending_rows(self, dataset: str) -> list[PendingRow]: ...  # остаётся как есть
```

`PendingReplayPort` — удалить.

### Изменения в `ResolveUseCase`

```python
import structlog
from connector.domain.transform.resolver import pending_codec

logger = structlog.get_logger(__name__)

def iter_resolved(
    self,
    matched_source: Iterable[TransformResult],
    resolve_stage: ResolveStage,
    *,
    dataset: str | None = None,
    pending_replay: ResolveRuntimePort | None = None,   # новый параметр
):
    pending_rows: list[TransformResult] = []
    if pending_replay is not None and dataset is not None:
        load_result = pending_codec.load_pending_rows(pending_replay.list_pending_rows(dataset))
        pending_rows = load_result.rows
        if load_result.skipped > 0:
            logger.warning(
                "pending_codec_skipped_invalid",
                count=load_result.skipped,
                dataset=dataset,
            )
    all_matched = chain(matched_source, pending_rows)
    return self._iter_resolved(all_matched, resolve_stage, dataset=dataset)
```

### Изменения в `ImportPlanService`

```python
def run(
    self,
    *,
    planning_runtime: PlanningRuntimePort,   # pending_replay удалён
    ...
    resolve_stage: ResolveStage,
    catalog: ErrorCatalog,
) -> CommandResult:
    ...
    resolve_usecase.iter_resolved(
        matched_source=matched_rows,
        resolve_stage=resolve_stage,
        dataset=dataset,
        pending_replay=planning_runtime,   # PlanningRuntimePort ⊇ ResolveRuntimePort
    )
    # Без chain(), без _load_pending_rows(), без json, без MatchedRow
```

### Поток данных

```
import_plan command
    └─ ImportPlanService.run(planning_runtime, ...)
         ├─ transform_pipeline.run(extractor)  →  enriched_rows
         ├─ open_match_runtime(...)            →  matched_rows
         └─ ResolveUseCase.iter_resolved(
                matched_source=matched_rows,
                pending_replay=planning_runtime,
                dataset=dataset,
            )
                 ├─ planning_runtime.list_pending_rows(dataset)
                 │       → list[PendingRow]             ← raw из SQLite
                 ├─ pending_codec.load_pending_rows(raw)
                 │       → list[TransformResult[MatchedRow]]  ← domain, stdlib json
                 ├─ chain(matched_rows, pending_rows)
                 └─ _iter_resolved(all, resolve_stage)  →  resolved_rows
```

### Расположение пары сериализации

```
connector/domain/transform/resolver/
    resolve_core.py       _serialize_pending_payload()   ← пишет в storage
    pending_codec.py      load_pending_rows()            ← читает из storage
```

Оба модуля — в одном пакете, оба работают только с domain типами.

---

### Ответственность и границы `pending_codec.py`

**Единственная ответственность (SRP):**
Десериализовать raw `list[PendingRow]` (байтовый JSON из storage) в типизированные domain-объекты `list[TransformResult[MatchedRow]]`. Причина изменения модуля — только изменение формата pending payload.

**Что модуль делает:**
- Публичный API: функция `load_pending_rows(pending_rows: list[PendingRow]) -> PendingLoadResult` и dataclass `PendingLoadResult(rows, skipped)`
- 4 приватных хелпера (`_deserialize_pending_matched_row`, `_deserialize_match_decision`, `_deserialize_candidate`, `_deserialize_source_links`) — каждый разбирает один уровень вложенности структуры
- Невалидные записи пропускаются без исключений; `skipped` счётчик возвращается в `PendingLoadResult` — наблюдаемость на уровне caller без побочных эффектов в самом модуле

**Что модуль НЕ делает (явные границы):**
- Не вызывает порты, не обращается к storage — получает уже загруженные `PendingRow`
- Не содержит `_serialize_*` функций — сериализация остаётся в `resolve_core.py` (её вызов точечно встроен в resolve-алгоритм)
- Не знает о `ResolveUseCase`, `ImportPlanService` или о том, кто его вызовет
- Не содержит infra-импортов — только domain types + stdlib `json`

**SOLID-проверка:**

| Принцип | Выполнение |
|---------|------------|
| **S** (SRP) | ✅ Один модуль — один формат. Фильтрация (CONFLICT, errors) живёт в `PlanBuilder`, pending-логика — в `ResolveUseCase`. `pending_codec` только парсит. |
| **O** (OCP) | ✅ Добавление поля в payload = расширение `_deserialize_pending_matched_row`. Модуль не требует подклассирования. |
| **L** (LSP) | ✅ N/A — чистые функции, не иерархия классов. |
| **I** (ISP) | ✅ Публичный API — одна функция. Вызывающий (`ResolveUseCase`) не знает о 4 приватных хелперах. |
| **D** (DIP) | ✅ Зависит от `PendingRow` (port model) и domain-типов. Направление: domain → domain. Ни одного infra-импорта. |

**Почему НЕ класс `PendingPayloadDeserializer`:**
Все функции статeless и не имеют инжектируемых зависимостей — класс добавил бы только `__init__` без аргументов, что идентично namespace-у модуля. Модуль с одной публичной функцией и приватными хелперами — это достаточная и правильная инкапсуляция для чистой функциональной трансформации.

**Почему `_serialize_*` остаются в `resolve_core.py`:**
Сериализация вызывается в единственной точке внутри `Resolver.run()` — при принятии решения "создать pending link". Это часть resolve-алгоритма, а не self-contained codec операция. Перенос добавил бы импорт `resolve_core → pending_codec` внутри пакета, что допустимо, но не даёт преимуществ при текущем scope. Задача отложена как возможный Phase 2.

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Пара сериализации замкнута в **доменном слое** — `resolve_core.py` (пишет) и `pending_codec.py` (читает) — оба в `connector/domain/transform/resolver/`. Формат JSON принадлежит домену, который знает структуру `MatchedRow`
- ✅ Порт (`ResolveRuntimePort`) остаётся thin — возвращает `list[PendingRow]` (сырые storage DTO), не знает о pipeline-типах
- ✅ `SqliteCacheGateway` остаётся storage-only — не импортирует `MatchedRow`, `TransformResult`
- ✅ `ImportPlanService` больше не знает о JSON, `MatchedRow`, `MatchDecision`
- ✅ `PendingReplayPort` удалён — phantom alias, нарушавший ISP
- ✅ `ResolveUseCase.iter_resolved(pending_replay=None)` — safe default, команды match/resolve не меняются

**Недостатки (компромиссы)**:
- ⚠️ `ResolveUseCase` теперь импортирует `pending_codec` (domain → domain — допустимо)
- ⚠️ `pending_codec.py` использует `json` из stdlib — это не infra-зависимость, а часть формата данных доменного слоя

**Альтернативы, которые отклонили**:
- ❌ **Десериализация в `SqliteCacheGateway`**: порт должен был вернуть `list[TransformResult[MatchedRow]]`. SQLite gateway — хранилище (storage infra), он не должен знать о pipeline-типах (`TransformResult`, `MatchedRow`, `MatchDecision`). Нарушает принцип "infra знает о domain.ports, но не о domain.logic"
- ❌ **Новый метод `list_pending_matched_rows()` в `ResolveRuntimePort`**: тянет высокоуровневые pipeline-типы в port contract; делает все реализации порта (`SqliteCacheGateway`, future mocks) ответственными за pipeline-семантику
- ❌ **Pending replay внутри `open_match_runtime`**: pending строки уже прошли match — смешивать их в match runtime семантически неверно

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform/resolver/pending_codec.py` | **Создать**: `load_pending_rows()` + перенести `_deserialize_*` из `import_plan_service.py` |
| `connector/domain/transform/resolver/__init__.py` | Экспортировать `pending_codec` или `load_pending_rows` |
| `connector/domain/ports/cache/roles.py` | Удалить `PendingReplayPort`; `ResolveRuntimePort` без изменений |
| `connector/usecases/resolve_usecase.py` | `iter_resolved()` + опциональный `pending_replay`; `chain` через `pending_codec` |
| `connector/usecases/import_plan_service.py` | Удалить `pending_replay` параметр и все `_deserialize_*`; передавать `planning_runtime` в `ResolveUseCase` |
| `connector/delivery/commands/import_plan.py` | Убрать `pending_replay` из вызова `service.run()` |
| `tests/unit/resolver/test_pending_codec.py` | **Создать**: unit-тесты де/сериализации |
| `tests/...` | Обновить тесты `ImportPlanService` и `ResolveUseCase` |

### Инварианты

1. **`pending_codec.py`** — только domain types + stdlib `json`; никаких infra-импортов
2. **`ResolveRuntimePort.list_pending_rows()`** — возвращает `list[PendingRow]`; не меняется
3. **`ResolveUseCase.iter_resolved(pending_replay=None)`** — поведение match/resolve команд не меняется
4. **`PlanningRuntimePort ⊇ ResolveRuntimePort`** — передача `planning_runtime` как `pending_replay` типобезопасна
5. `_serialize_pending_payload()` остаётся в `resolve_core.py` — перенос в `pending_codec` возможен в будущем, но не обязателен сейчас

---

## 🧪 Тестовый набор

### Zone 1: `pending_codec.py` — unit-тесты

**Файл**: `tests/unit/resolver/test_pending_codec.py` (новый)

| Тест | Что проверяет |
|------|--------------|
| `test_load_pending_rows_empty_list` | Пустой список → пустой список; нет исключений |
| `test_load_pending_rows_valid_matched_decision` | Полный валидный payload MATCHED → 1 `TransformResult[MatchedRow]` |
| `test_load_pending_rows_all_decision_statuses` | MATCHED, NOT_FOUND, AMBIGUOUS — все три статуса корректно десериализуются |
| `test_load_pending_rows_skips_legacy_without_typed_decision` | Нет поля `match_decision` → пропуск записи (не исключение) |
| `test_load_pending_rows_skips_invalid_json` | Невалидный JSON в `payload` → пропуск записи (не исключение) |
| `test_load_pending_rows_skips_missing_required_field` | Нет `identity` или `row_ref` → пропуск |
| `test_load_pending_rows_skips_invalid_decision_status` | Неизвестный `status` строкой → пропуск |
| `test_load_pending_rows_result_has_empty_record_values` | `record.values == {}` — `SourceRecord` создаётся без raw values |
| `test_load_pending_rows_preserves_source_links` | `source_links` с вложенными `Identity` корректно десериализуются |
| `test_load_pending_rows_result_carries_target_id` | `matched_row.target_id` сохраняется из payload |
| `test_load_pending_rows_returns_skipped_count` | Смесь валидных и невалидных → `result.skipped == N_invalid`, `len(result.rows) == N_valid` |

**Миграция**: `tests/integration/usecases/test_import_plan_service_pending_rows.py` → **удалить** после реализации:
- `test_pending_replay_rows_include_typed_match_decision_for_all_statuses` → `test_load_pending_rows_all_decision_statuses`
- `test_pending_replay_rows_skip_legacy_payload_without_typed_decision` → `test_load_pending_rows_skips_legacy_without_typed_decision`

> Примечание: старые тесты — integration с `_PendingReplay` стабом и портом; новые — чистые unit, `load_pending_rows()` принимает `list[PendingRow]` напрямую, порт не нужен.

---

### Zone 2: `ResolveUseCase.iter_resolved(pending_replay=...)` — новые integration-тесты

**Файл**: `tests/integration/usecases/test_resolve_usecase_transactions.py` (дополнить)

| Тест | Что проверяет |
|------|--------------|
| `test_iter_resolved_skips_pending_when_replay_is_none` | Backward compat: `pending_replay=None` → только `matched_source`; existing 3 теста не ломаются |
| `test_iter_resolved_chains_pending_when_replay_provided` | С `pending_replay` порт возвращает pending rows → они попадают в разрешённый поток |
| `test_iter_resolved_skips_pending_when_dataset_is_none` | `pending_replay` передан, `dataset=None` → `list_pending_rows()` не вызывается |
| `test_iter_resolved_warns_on_skipped_pending` | `load_result.skipped > 0` → structlog warning `pending_codec_skipped_invalid` эмитируется |

**Существующие тесты** (3 шт.) остаются без изменений — `pending_replay=None` по умолчанию.

---

**Инвариантные проверки** (фиксируются как architecture guard-тесты в DEC-002):
- `grep -r "PendingReplayPort" connector/` → пусто
- `connector/domain/transform/resolver/pending_codec.py` не содержит импортов из `connector.infra`

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `pending_codec.py` | Создаётся | Новый модуль в `resolver/` |
| `ImportPlanService` | Упрощение | Удалить `pending_replay` param и 200 строк |
| `ResolveUseCase` | Расширение | `pending_replay` в `iter_resolved()` |
| `ResolveRuntimePort` | Нет изменений | — |
| `SqliteCacheGateway` | Нет изменений | — |
| `import_plan.py` command | Упрощение | Убрать `pending_replay` из вызова |
| Команды match/resolve | Нет | `pending_replay=None` по умолчанию |

---

## 🔗 Связанные документы

- [PLANNER-PROBLEM-001](./PLANNER-PROBLEM-001-pending-replay-infra-leak.md) — решаемая проблема
- `connector/domain/transform/resolver/resolve_core.py` — `_serialize_pending_payload()` (симметричная сторона пары)
- `connector/domain/ports/cache/roles.py` — `ResolveRuntimePort`, `PendingRow`

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-23 | Решение принято |
| 2026-02-23 | Скорректировано: десериализация перенесена из infra (SqliteCacheGateway) в domain (`pending_codec.py`); порт оставлен без изменений |
