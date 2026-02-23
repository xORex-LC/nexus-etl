# PLANNER-DEC-002: Растворение избыточных слоёв планнера и очистка plan_writer

> **Статус**: Открыто (реализуется совместно с PLANNER-DEC-001)
> **Дата принятия**: 2026-02-23
> **Решает проблему**: [PLANNER-PROBLEM-002](./PLANNER-PROBLEM-002-planner-redundant-layers-and-masking.md)
> **Реализуется совместно с**: [PLANNER-DEC-001](./PLANNER-DEC-001-pending-replay-at-resolve-boundary.md)
> **Реализуется до DEC-006**: `import_plan.py` в промежуточном состоянии вызывает `open_match_runtime` напрямую; [TRANSFORM-DEC-006](../transform/TRANSFORM-DEC-006-pipeline-segments-in-container.md) упростит его далее, но не является prerequisite
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

`PlanUseCase` — пустая обёртка над `PlanBuilder` без собственной логики. `ImportPlanService` после PLANNER-DEC-001 + TRANSFORM-DEC-006 сводится к координации `PlanUseCase` + `write_plan_file` + logging без бизнес-правил — delivery-concern в wrong layer. `plan_writer.py` вызывает `maskSecretsInObject` на данных, в которых секретных значений уже нет (enrich их очистил). Подробнее: [PLANNER-PROBLEM-002](./PLANNER-PROBLEM-002-planner-redundant-layers-and-masking.md).

---

## 🎯 Решение

1. **`PlanBuilder.build_from_stream()`** поглощает фильтр-цикл из `PlanUseCase` — domain rules остаются в domain.
2. **`PlanUseCase` удаляется** — пустой посредник без ответственности.
3. **`ImportPlanService` удаляется** — delivery-координация переходит в command handler.
4. **`plan_writer.py` теряет маскировку** — `_mask_sensitive_item()` и `maskSecretsInObject` удаляются; контракт: `plan_items` приходят без секретных значений (гарантия enrich-стадии).

---

## 🏗️ Архитектурное решение

### PlanBuilder получает build_from_stream()

```python
# connector/domain/planning/plan_builder.py

class PlanBuilder:
    ...

    def build_from_stream(
        self,
        resolved_rows: Iterable[TransformResult],
    ) -> PlanBuildResult:
        """
        Поглощает поток resolved строк, применяет domain-фильтры и строит план.

        Фильтры (domain rules):
            - row is None     → строка не прошла resolve, пропустить
            - result.errors   → строка с ошибками, не включать в план
            - op == CONFLICT  → конфликт match, не включать в план
        """
        for result in resolved_rows:
            row = result.row
            if row is None:
                continue
            if result.errors:
                continue
            if row.op == ResolveOp.CONFLICT:
                continue
            self.add_resolved(row)
        return self.build()
```

### plan_writer.py — убрать маскировку

```python
# connector/infra/artifacts/plan_writer.py  (после изменения)

def write_plan_file(
    plan_items: list[dict[str, Any]],
    summary: dict[str, Any],
    meta: dict[str, Any],
    report_dir: str,
    run_id: str,
    generated_at: str,
) -> str:
    """
    Контракт: plan_items не содержат секретных значений.
    Гарантия обеспечивается enrich-стадией (очищает значения, оставляет только имена полей).
    Маскировка здесь избыточна и удалена.
    """
    plan_dir = Path(report_dir)
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plan_dir / f"plan_import_{run_id}.json"
    data = {
        "meta": {"run_id": run_id, "generated_at": generated_at, **meta},
        "summary": summary,
        "items": plan_items,   # as-is, без маскировки
    }
    plan_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(plan_path)
```

### ImportPlanService → command handler (delivery)

**Промежуточное состояние** (после DEC-001 + DEC-002, до DEC-006):
`import_plan.py` берёт на себя оркестрацию, ранее бывшую в `ImportPlanService.run()`.
`open_match_runtime` вызывается напрямую — `PlanningPipeline` появится позже в DEC-006.

```python
# connector/delivery/commands/import_plan.py  (промежуточное: DEC-001 + DEC-002, до DEC-006)

enriched_rows = iter_ok(transform_pipeline.run(Extractor(row_source, catalog).run()), ...)

with open_match_runtime(                            # из usecases/planning_match_runtime.py
    run_id=run_id,
    match_stage=match_stage,
    match_runtime=planning_runtime,
    ...
) as match_runtime:
    matched_rows = iter_matched_ok(runtime=match_runtime, enriched_source=enriched_rows)
    resolved_rows = iter_ok(
        ResolveUseCase(...).iter_resolved(
            matched_source=matched_rows,
            resolve_stage=resolve_stage,
            dataset=dataset_name,
            pending_replay=planning_runtime,        # DEC-001: pending replay в ResolveUseCase
        )
    )
    plan_result = PlanBuilder().build_from_stream(resolved_rows)   # DEC-002: domain rules

plan_path = write_plan_file(                        # infra, вызывается из delivery
    plan_items=plan_result.items,
    summary=plan_result.summary_as_dict(),
    meta={"include_deleted": include_deleted, "dataset": dataset_name},
    report_dir=report_dir,
    run_id=run_id,
    generated_at=generated_at,
)
logger.info("plan_written", path=plan_path, run_id=run_id)  # structlog, delivery
return result_with(SystemErrorCode.OK)
```

> **DEC-006 (будущее)**: заменяет `open_match_runtime + ResolveUseCase` на `pipeline.planning_pipeline(run_id, planning_runtime)` — `import_plan.py` сокращается до 3 строк.

### Удаляемые файлы / классы

| Артефакт | Действие |
|----------|---------|
| `connector/usecases/plan_usecase.py` | Удалить |
| `connector/usecases/import_plan_service.py` | Удалить |
| `plan_writer._mask_sensitive_item()` | Удалить |
| `plan_writer` импорт `maskSecretsInObject` | Удалить |

### Контракт enrich → plan (явная фиксация)

После этого решения `plan_writer.py` полагается на контракт: **enrich-стадия гарантирует отсутствие секретных значений в `TransformResult` к моменту формирования плана**. Контракт:

```
EnrichStage.run() → TransformResult где:
    - result.row не содержит значений секретных полей (очищены _clear_secret_fields)
    - result.meta["secret_fields"] = ["field_name", ...] (только имена)
    - result.secret_candidates = {} (пусто)
```

Этот контракт существовал де-факто; данное решение делает его явным и зафиксированным.

### Поток данных после реализации DEC-001 + DEC-002 (промежуточное состояние)

```
import_plan command handler (delivery)
    │
    ├─ transform_pipeline.run(Extractor(row_source))
    │       ├─ MapStage → NormalizeStage → EnrichStage
    │       └─ EnrichStage: vault write + clear secret values
    │       → enriched_rows
    │
    ├─ open_match_runtime(match_stage, planning_runtime, ...)   [из usecases/]
    │       matched_rows = iter_matched_ok(runtime, enriched_rows)
    │       │
    │       └─ ResolveUseCase.iter_resolved(
    │               matched_source=matched_rows,
    │               pending_replay=planning_runtime,            [PLANNER-DEC-001]
    │           )
    │               ├─ pending_codec.load_pending_rows()
    │               │       → PendingLoadResult(rows, skipped)
    │               │       + warning if skipped > 0
    │               ├─ chain(matched_rows, pending_rows)
    │               └─ _iter_resolved()  → resolved_rows
    │
    ├─ PlanBuilder().build_from_stream(resolved_rows)    [domain]
    │       filter(row is None, errors, CONFLICT) → plan_result
    │
    ├─ write_plan_file(plan_result, ...)                 [infra]
    │       items as-is (no masking)
    │
    └─ logger.info("plan_written")                       [delivery]
```

> **После DEC-006**: `open_match_runtime + ResolveUseCase` заменяется на `with pipeline.planning_pipeline(...) as resolved_rows`.

---

## 🗺️ TO BE: архитектурное дерево плоскости планнера

Полная картина после реализации **DEC-001 + DEC-002** (до DEC-006).

```
connector/
│
├── domain/
│   │
│   ├── planning/                              ← domain: чистая логика сборки плана
│   │   ├── plan_builder.py                   ← + build_from_stream() [НОВЫЙ МЕТОД]
│   │   │     Единственный владелец domain rules:
│   │   │     "что включать в план" (filter CONFLICT, filter errors)
│   │   ├── plan_models.py                    ← PlanItem, PlanBuildResult [без изменений]
│   │   └── record_ref.py                     ← [без изменений]
│   │
│   ├── transform/
│   │   └── resolver/
│   │       ├── resolve_core.py               ← Resolver [без изменений]
│   │       │     _serialize_pending_payload() — пишет MatchedRow → JSON (остаётся здесь)
│   │       ├── resolve_deps.py               ← [без изменений]
│   │       ├── resolve_engine.py             ← [без изменений]
│   │       └── pending_codec.py              ← [НОВЫЙ — DEC-001]
│   │             load_pending_rows()          — публичный API
│   │             _deserialize_*()             — приватные хелперы, перенесены из ImportPlanService
│   │             Симметричная сторона _serialize_pending_payload() из resolve_core.py
│   │
│   └── ports/
│       └── cache/
│           └── roles.py
│                 PendingReplayPort            ← УДАЛЁН [DEC-001] — phantom alias, ISP-нарушение
│                 ResolveRuntimePort           ← [без изменений]: list_pending_rows() → list[PendingRow]
│                 PlanningRuntimePort          ← [без изменений]: ⊇ ResolveRuntimePort
│
├── usecases/
│   │
│   ├── resolve_usecase.py                    ← [ИЗМЕНЁН — DEC-001]
│   │     iter_resolved(pending_replay=None)   — новый опциональный параметр
│   │     Вызывает pending_codec.load_pending_rows() если pending_replay передан
│   │
│   ├── planning_match_runtime.py             ← [без изменений до DEC-006]
│   │     open_match_runtime(), iter_matched_ok()
│   │     Будет перемещён в delivery при реализации DEC-006
│   │
│   ├── import_plan_service.py                ← УДАЛЁН [DEC-001 + DEC-002]
│   │     Было: 335 строк — pending-десериализация + match/resolve оркестрация + infra вызовы
│   │     Причина удаления: после DEC-001 (убрана десериализация) и DEC-002 (убраны стадии)
│   │     не осталось собственной ответственности; координация переходит в import_plan.py
│   │
│   └── plan_usecase.py                       ← УДАЛЁН [DEC-002]
│         Было: пустая обёртка над PlanBuilder без собственной логики
│         Стало: build_from_stream() поглощён PlanBuilder; файл удалён
│
├── infra/
│   └── artifacts/
│       └── plan_writer.py                    ← [УПРОЩЁН — DEC-002]
│             write_plan_file()               — записывает items as-is (без маскировки)
│             _mask_sensitive_item()           ← УДАЛЕНА — dead code (enrich уже очистил значения)
│             import maskSecretsInObject       ← УДАЛЁН
│             Контракт: план гарантированно не содержит секретных значений (enrich-контракт)
│
└── delivery/
    └── commands/
        └── import_plan.py                    ← [УПРОЩЁН — DEC-002, промежуточное состояние]
              Было: делегировал всё в ImportPlanService (335 строк)
              Стало: вызывает open_match_runtime + ResolveUseCase + PlanBuilder + write_plan_file напрямую
              Ответственность: delivery-координация (domain + infra + logging)
              После DEC-006: open_match_runtime + ResolveUseCase заменяются на planning_pipeline.open()
```

### Распределение ответственности по слоям (TO BE)

| Слой | Модуль | Ответственность | Запрещено |
|------|--------|-----------------|-----------|
| **domain/planning** | `PlanBuilder` | Domain rules: фильтрация + сборка плана | Infra, I/O, знание о форматах хранения |
| **domain/resolver** | `pending_codec.py` | Формат pending payload: десериализация | Infra вызовы, знание о SQLite |
| **domain/resolver** | `resolve_core.py` | Resolve-алгоритм + сериализация pending | Знание о planner |
| **domain/ports** | `ResolveRuntimePort` | Контракт доступа к pending storage | Знание о pipeline-типах |
| **usecases** | `ResolveUseCase` | Оркестрация resolve + pending replay | Infra импорты |
| **infra** | `plan_writer.py` | IO: запись JSON-файла плана | Бизнес-логика, маскировка |
| **delivery** | `import_plan.py` | Wiring: pipeline → PlanBuilder → write_plan_file | Бизнес-правила |

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Domain rules ("пропустить CONFLICT, пропустить ошибки") живут в `PlanBuilder` (domain) — Single Source of Truth
- ✅ Нет infra импортов в use-case слое (use-case слой исчезает)
- ✅ `plan_writer.py` становится тривиальным IO-адаптером без бизнес-логики
- ✅ Явный контракт enrich → plan снижает вероятность future regression (кто-то добавит секретное поле без vault и оно не будет замаскировано — но теперь это explicit contract violation, а не молчаливый пропуск)
- ✅ Реализуется в одном PR вместе с PLANNER-DEC-001 — атомарное улучшение

**Недостатки (компромиссы)**:
- ⚠️ Command handler `import_plan.py` становится чуть длиннее (добавляет `PlanBuilder` + `write_plan_file`). Компромисс оправдан: это delivery coordination — именно здесь место.
- ⚠️ Удаление `maskSecretsInObject` из `plan_writer.py` делает защиту explicit-contract-based вместо defensive. Если контракт нарушится (enrich не очистит поле) — значение попадёт в план. Митигация: явная документация контракта + тест на "plan не содержит секретных значений"

**Альтернативы, которые отклонили**:
- ❌ **`PlanArtifactPort` для `write_plan_file`**: порт с одной реализацией без реальных альтернатив — преждевременная абстракция. Delivery вызывает infra напрямую — это нормально
- ❌ **Оставить `ImportPlanService`**: после упрощения он — пустой класс-посредник без ответственности, добавляет indirection без пользы

---

## 🛠️ Реализация (совместно с PLANNER-DEC-001)

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/planning/plan_builder.py` | Добавить `build_from_stream(iterable)` |
| `connector/usecases/plan_usecase.py` | **Удалить** |
| `connector/usecases/import_plan_service.py` | **Удалить** (совместно с DEC-001) |
| `connector/infra/artifacts/plan_writer.py` | Убрать `_mask_sensitive_item`, `maskSecretsInObject` |
| `connector/delivery/commands/import_plan.py` | Вызывать `PlanBuilder.build_from_stream()` + `write_plan_file()` напрямую |
| `connector/domain/transform/resolver/pending_codec.py` | **Создать** (DEC-001) |
| `connector/usecases/resolve_usecase.py` | Добавить `pending_replay` param (DEC-001) |
| `connector/domain/ports/cache/roles.py` | Удалить `PendingReplayPort` (DEC-001) |
| `tests/unit/planning/test_plan_builder.py` | Тесты `build_from_stream()` + контракт "нет секретных значений в плане" |
| `tests/unit/resolver/test_pending_codec.py` | Тесты `load_pending_rows()` (DEC-001) |

### Инварианты

1. `PlanBuilder.build_from_stream()` применяет фильтры до `add_resolved()`: `row is None`, `errors`, `CONFLICT`
2. `plan_writer.py` не содержит `maskSecretsInObject` — контракт enrich является гарантией
3. `connector/usecases/` не содержит импортов из `connector/infra/` после удаления файлов
4. `import_plan.py` не импортирует `ImportPlanService`, `PlanUseCase`

---

## 🧪 Тестовый набор

### Zone 3: `PlanBuilder.build_from_stream()` — unit-тесты

**Файл**: `tests/unit/planning/test_plan_builder.py` (новый)

| Тест | Что проверяет |
|------|--------------|
| `test_build_from_stream_excludes_none_row` | `result.row is None` → строка не попадает в `plan_items` |
| `test_build_from_stream_excludes_errors` | `result.errors` непустой → строка не попадает в план |
| `test_build_from_stream_excludes_conflict_op` | `row.op == CONFLICT` → строка не включается в план, считается `failed_rows` |
| `test_build_from_stream_includes_create_and_update_ops` | Строки CREATE и UPDATE проходят → `plan_items` содержит правильные операции |
| `test_build_from_stream_summary_counts_match_input` | Counters: `planned_create`, `planned_update`, `skipped`, `failed_rows` — корректны |

---

### Zone 4: Architecture guard-тесты

**Файл**: `tests/architecture/test_planner_layer_boundaries.py` (новый)

| Тест | Что проверяет | Почему важно |
|------|--------------|--------------|
| `test_import_plan_service_module_removed` | `connector/usecases/import_plan_service.py` не существует | Предотвращает реинтродукцию пустого оркестратора |
| `test_plan_usecase_module_removed` | `connector/usecases/plan_usecase.py` не существует | Предотвращает реинтродукцию пустой обёртки |
| `test_pending_replay_port_removed_from_roles` | `PendingReplayPort` отсутствует в `roles.py` (AST-парсинг) | Предотвращает возврат phantom ISP-alias |
| `test_pending_codec_has_no_infra_imports` | `pending_codec.py` не импортирует `connector.infra` (AST-парсинг) | DIP-инвариант: domain → domain |
| `test_plan_writer_does_not_mask_secrets` | `maskSecretsInObject` отсутствует в `plan_writer.py` | Dead code не возвращается |
| `test_usecases_do_not_import_infra` | `connector/usecases/` не содержит импортов из `connector.infra` (AST) | Hexagonal direction: use-case не тянет infra |

---

### E2E / Integration — без изменений

| Файл | Статус | Обоснование |
|------|--------|-------------|
| `tests/e2e/pipelines/test_plan_pipeline.py` (6 тестов) | Проходят без правок | Тестируют поведение CLI; wiring меняется в delivery, контракт на выходе неизменен |
| `tests/integration/usecases/test_resolve_usecase_transactions.py` (3 теста) | Проходят без правок | `pending_replay=None` по умолчанию; transaction-семантика не затронута |

---

### Удаляемые тесты

| Файл | Причина |
|------|---------|
| `tests/integration/usecases/test_import_plan_service_pending_rows.py` | Тестировал private `_load_pending_rows` из удалённого модуля; логика перенесена в `test_pending_codec.py` (Zone 1, DEC-001) |

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `PlanBuilder` | Расширение | Добавить `build_from_stream()` |
| `plan_usecase.py` | Удаление | Удалить файл; обновить импорты |
| `import_plan_service.py` | Удаление | Удалить файл; обновить импорты |
| `plan_writer.py` | Упрощение | Убрать маскировку |
| `import_plan.py` | Рефакторинг | Прямой вызов `PlanBuilder` + `write_plan_file` |
| `resolve_usecase.py` | Расширение (DEC-001) | Добавить `pending_replay` param |
| `roles.py` | Упрощение (DEC-001) | Удалить `PendingReplayPort` |

---

## 🔗 Связанные документы

- [PLANNER-PROBLEM-002](./PLANNER-PROBLEM-002-planner-redundant-layers-and-masking.md) — решаемая проблема
- [PLANNER-DEC-001](./PLANNER-DEC-001-pending-replay-at-resolve-boundary.md) — реализуется совместно
- [TRANSFORM-DEC-006](../transform/TRANSFORM-DEC-006-pipeline-segments-in-container.md) — prerequisite (PlanningPipeline)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-23 | Решение принято; реализация совместно с PLANNER-DEC-001 |
