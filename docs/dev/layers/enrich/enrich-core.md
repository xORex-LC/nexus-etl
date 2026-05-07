# Enrich Core — алгоритм обогащения TransformResult

> `EnricherCore` применяет операции `generate` и `lookup` к `TransformResult` последовательно: строит `match_key`, записывает секреты в Vault через `SecretStoreProtocol`, заполняет `meta["enrich_events"]` и передаёт обогащённый результат в `MatchStage`.

## 📑 Содержание

- [📋 Обзор](#-обзор)
- [🏗️ Архитектура слоя](#️-архитектура-слоя)
- [🔑 Ключевые абстракции](#-ключевые-абстракции)
- [🗂️ Модели данных](#️-модели-данных)
- [📊 Ключевые методы и алгоритмы](#-ключевые-методы-и-алгоритмы)
- [🔄 Взаимодействие с другими слоями](#-взаимодействие-с-другими-слоями)
- [🔌 Контракты и границы](#-контракты-и-границы)
- [🛠️ HOW-TO](#️-how-to)
- [💡 Типичные сценарии](#-типичные-сценарии)
- [📌 Важные детали](#-важные-детали)
- [🧪 Тестовое покрытие](#-тестовое-покрытие)
- [❓ FAQ](#-faq)
- [🔗 Связанные документы](#-связанные-документы)
- [📝 История изменений](#-история-изменений)

---

## 📋 Обзор

`EnricherCore` — центральный исполнитель обогащения. Получает `TransformResult`
после нормализации (строка типизирована, ключи совпадают с sink-схемой) и применяет
последовательно операции из скомпилированного `EnricherSpec`.

**Три ключевых сайд-эффекта, которые enrich производит в pipeline:**

1. **`match_key` установлен** — вычисляется из полей строки; без него MatchStage не может идентифицировать запись.
2. **Секреты записаны в Vault** — поля из `secrets.fields` попадают в `secret_candidates` → `SecretStoreProtocol.put_many()` → `row[field] = None`.
3. **`meta["enrich_events"]` заполнен** — детальный аудит каждого изменения поля (что, откуда, каким решением).

**Полный путь данных через enrich:**

```
NormalizeStage → TransformResult[dict]
                        │
                        ▼
              EnrichStage.run()
                        │
                        ├── records с errors → EnricherCore всё равно
                        │   запускает операции с run_when_errors=ALWAYS
                        │   (match_key всегда вычисляется)
                        │
                        └── EnricherEngine.enrich()
                                  │
                                  ▼
                          EnricherCore.enrich()
                                  │
                                  ├── op: build_match_key (COMPUTE, ALWAYS)
                                  │     → builder.match_key = MatchKey("...")
                                  │
                                  ├── op: email_from_cache (LOOKUP)
                                  │     → provider.fetch() → candidate.value
                                  │     → builder.row["email"] = "john@example.com"
                                  │
                                  ├── op: user_name (GENERATE)
                                  │     → base_generator() → condition() → append_generator()
                                  │     → exists() → allow_if() → conflict_policy()
                                  │     → builder.row["user_name"] = "IvanII"
                                  │
                                  ├── op: password (GENERATE → secret:password)
                                  │     → builder.secret_candidates["password"] = "..."
                                  │
                                  ├── _store_secrets()
                                  │     → secret_store.put_many(...)
                                  │     → row["password"] = None
                                  │     → meta["secret_fields"] = ["password"]
                                  │
                                  └── builder.build()
                                            │
                                            ▼
                                  TransformResult[dict]
                                  match_key=MatchKey("Doe|John|...")
                                  meta["enrich_events"]=[...]
                                  meta["enrich_summary"]={...}
                                            │
                                            ▼
                                   MatchStage.run()
```

---

## 🏗️ Архитектура слоя

```
connector/domain/transform/enrich/
├── enricher_core.py      EnricherCore — главная логика (608 строк)
├── enricher_engine.py    EnricherEngine — DSL-обвязка, два пути init
├── models.py             CandidateValue, MergePolicy, StrictnessPolicy, EnrichEvent
├── providers.py          CandidateProvider — Protocol для провайдеров кандидатов
├── resolver.py           ConflictResolver, MergeEngine, _FieldMutationTracker
└── report.py             EnricherReport — сводная статистика по операциям

connector/domain/transform_dsl/compilers/enrich.py
                          EnricherDsl, EnricherSpec, EnrichmentOperation, KeyRegistry
```

| Компонент | Ответственность |
|-----------|----------------|
| `EnricherEngine` | Компилирует `EnrichSpec → EnricherSpec`; создаёт `EnricherCore`; маршрутизирует `enrich()` |
| `EnricherCore` | Итерирует операции, вызывает `_execute_operation()`, хранит `ConflictResolver`/`MergeEngine` |
| `_execute_operation()` | Разрешает ключи, собирает кандидатов, принимает решение через `ConflictResolver` |
| `_collect_candidates()` | Три ветки: COMPUTE / GENERATE (legacy или compiled generate path) / LOOKUP (провайдеры) |
| `ConflictResolver` | Сортирует кандидатов по (priority, confidence); выбирает один или объявляет AMBIGUOUS |
| `MergeEngine` | Решает `should_apply()` по `MergePolicy` и `authoritative_sources` |
| `_FieldMutationTracker` | Запоминает последнего writer для каждого поля (для `never_override` / conflict detection) |
| `_store_secrets()` | Записывает `secret_candidates` в vault, очищает строку, пишет `meta["secret_fields"]` |
| `EnricherReport` | Собирает счётчики `APPLIED/SKIPPED/WARNED/FAILED` для `meta["enrich_summary"]` |

---

## 🔑 Ключевые абстракции

### CandidateValue

**Файл:** `connector/domain/transform/enrich/models.py`

```python
@dataclass(frozen=True)
class CandidateValue:
    field: str                  # имя поля назначения
    value: Any                  # кандидат на запись
    source: str                 # "computed" | "generated" | "cache.by_field" | ...
    priority: int | None = None # приоритет для ConflictResolver
    confidence: float | None = None  # уверенность (0.0–1.0), вторичный ключ
    evidence: dict | None = None     # произвольные данные источника
```

`CandidateValue` — унифицированный носитель результата любой операции: compute, generate, lookup.
`ConflictResolver` работает только с ним, не зная о природе источника.

### EnrichmentOperation (compiled)

**Файл:** `connector/domain/transform_dsl/compilers/enrich.py`

```python
@dataclass(frozen=True)
class EnrichmentOperation(Generic[T, D]):
    name: str                             # имя правила (из DSL)
    op_type: EnrichOperationType          # COMPUTE | GENERATE | LOOKUP
    targets: tuple[str, ...]             # поля назначения (обычно одно)
    required_keys: tuple[str, ...]       # ключи для поиска (через KeyRegistry)
    providers: tuple[CandidateProvider, ...]  # провайдеры для LOOKUP
    merge_policy: MergePolicy | None
    strictness: StrictnessPolicy | None
    run_when_errors: RunWhenErrors       # NEVER | ALWAYS | ONLY_NON_FATAL
    compute: Callable | None             # для COMPUTE (match_key)
    generator: Callable | None           # legacy GENERATE (ops chain)
    base_generator: Callable | None      # compiled build-block
    condition: Callable | None           # compiled when-block
    append_generator: Callable | None    # compiled then-block (append-stage)
    exists: Callable | None              # проверка уникальности (cache lookup)
    allow_if: Callable | None            # условие принятия при конфликте
    conflict_policy: CompiledConflictPolicy | None  # exists-conflict policy
    max_attempts: int                    # попыток generate (default 3)
    missing_error_code: str | None
    conflict_error_code: str | None
    error_field: str | None
```

### EnricherSpec (compiled)

**Файл:** `connector/domain/transform_dsl/compilers/enrich.py`

```python
@dataclass(frozen=True)
class EnricherSpec(Generic[T, D]):
    operations: tuple[EnrichmentOperation, ...]
    key_registry: KeyRegistry[T]
    source_priorities: dict[str, int]           # "cache.by_field" → 10, "computed" → 0
    default_merge_policy: MergePolicy           # FILL_ONLY_IF_EMPTY по умолчанию
    default_strictness: StrictnessPolicy
    authoritative_sources: set[str]             # {"sink_cache"}
    is_fatal_error: Callable | None             # классификатор fatal/non-fatal ошибок
    stop_on_failed: bool                        # прервать при первом FAILED
```

### EnricherEngine

**Файл:** `connector/domain/transform/enrich/enricher_engine.py`

DSL-обвязка: компилирует `EnrichSpec → EnricherSpec`, создаёт `EnricherCore`, маршрутизирует `enrich()`.

Два пути инициализации:
- **Путь 1 (`ctx: StageExecutionContext`)** — новый путь: capabilities берутся из context
- **Путь 2 (scattered params)** — legacy/тесты: зависимости передаются напрямую

---

## 🗂️ Модели данных

### MergePolicy и MergeMode

**Файл:** `connector/domain/transform/enrich/models.py`

```python
@dataclass(frozen=True)
class MergePolicy:
    mode: str = MergeMode.FILL_ONLY_IF_EMPTY
```

| DSL `merge` | `MergeMode` | Поведение |
|-------------|-------------|-----------|
| `fill_only_if_empty` | `OVERRIDE_IF_EMPTY` | Применить если `current is None or ""` |
| `override_if_empty` | `OVERRIDE_IF_EMPTY` | Синоним предыдущего |
| `recompute_always` | `RECOMPUTE_ALWAYS` | Всегда применять |
| `never_override` | `NEVER_OVERRIDE` | Никогда не применять |
| `override_if_authoritative` | `OVERRIDE_IF_AUTHORITATIVE` | Если source в `authoritative_sources` |
| (не задан) | spec.default_merge_policy | По умолчанию из `EnricherSpec` |

> `fill_only_if_empty` и `override_if_empty` маппятся в один и тот же `MergeMode.OVERRIDE_IF_EMPTY` — это синонимы.

### StrictnessPolicy

**Файл:** `connector/domain/transform/enrich/models.py`

```python
@dataclass(frozen=True)
class StrictnessPolicy:
    on_missing_key: str    = EnrichOutcome.SKIPPED
    on_no_candidates: str  = EnrichOutcome.SKIPPED
    on_ambiguous: str      = EnrichOutcome.NEEDS_RESOLVE
    on_provider_error: str = EnrichOutcome.WARNED
```

### EnrichOutcome

**Файл:** `connector/domain/transform/enrich/models.py`

```python
class EnrichOutcome(str, Enum):
    APPLIED       = "APPLIED"        # значение записано в поле
    SKIPPED       = "SKIPPED"        # операция пропущена
    WARNED        = "WARNED"         # предупреждение, строка продолжает обработку
    FAILED        = "FAILED"         # ошибка, строка может прерваться
    NEEDS_RESOLVE = "NEEDS_RESOLVE"  # неоднозначность, нужно ручное разрешение
```

### EnrichEvent

**Файл:** `connector/domain/transform/enrich/models.py`

Аудит-запись об изменении одного поля:

```python
@dataclass(frozen=True)
class EnrichEvent:
    op: str          # имя правила DSL
    field: str       # поле назначения
    before: Any      # значение до операции
    after: Any       # значение после операции
    source: str      # источник кандидата ("generated", "cache.by_field", ...)
    decision: str    # "applied" | "policy_skip" | "conflict_skipped" | "overridden_previous_op"
    outcome: str     # "APPLIED" | "SKIPPED"
```

Попадает в `meta["enrich_events"]` как list[dict].

### ResolveHint

**Файл:** `connector/domain/transform/enrich/models.py`

```python
@dataclass(frozen=True)
class ResolveHint:
    field: str                    # поле назначения
    lookup_key: dict[str, Any]    # ключи поиска + as_of
    reason: str                   # "ambiguous"
    candidates: list[dict]        # кандидаты (source, target_id, evidence)
    suggested_policy: str | None  # "manual"
```

Попадает в `meta["resolve_requests"]` при статусе `AMBIGUOUS`.

### EnricherReport

**Файл:** `connector/domain/transform/enrich/report.py`

```python
@dataclass
class EnricherReport:
    operations_total: int = 0
    outcomes: dict[str, int] = {}    # "APPLIED": 3, "SKIPPED": 1, ...
    updated_fields: int = 0
```

Сериализуется в `meta["enrich_summary"]`:

```python
{
    "operations_total": 4,
    "outcomes": {"APPLIED": 3, "SKIPPED": 1},
    "updated_fields": 3
}
```

### _FieldMutationTracker

**Файл:** `connector/domain/transform/enrich/resolver.py`

```python
class _FieldMutationTracker:
    _writers: dict[str, str]   # field → op_name последнего writer

    def has_writer(self, field: str) -> bool: ...
    def register(self, field: str, op_name: str) -> None: ...
```

Запоминает последнего writer для каждого поля. Используется:
- `never_override`: если tracker уже зарегистрировал writer → не применять
- Conflict detection: второй writer получает `tracker.has_writer(field) == True`

---

## 📊 Ключевые методы и алгоритмы

### `EnricherCore.enrich(result)` — полный алгоритм

**Файл:** `connector/domain/transform/enrich/enricher_core.py`

```python
def enrich(self, result: TransformResult[T]) -> TransformResult[T]:
```

**Актуальные generate semantics**:
- legacy generate path: `generator → exists → allow_if → max_attempts`
- compiled generate path: `base_generator → condition → append_generator → exists → allow_if → conflict_policy`
- для `retry_with_suffixes` suffix всегда добавляется к **base value**, а не к предыдущей попытке

```
1. if result.row is None:
       return result   # pass-through: строка уже отфильтрована

2. ctx     = EnrichContext(dataset=self.dataset, run_id=self.run_id)
   tracker  = _FieldMutationTracker()
   builder  = result.as_builder()

3. builder.meta["enrich_events"]    = []
   builder.meta["resolve_requests"] = []

4. summary = EnricherReport()

5. ПРЕДУПРЕЖДЕНИЕ: если есть builder.errors
   И spec.is_fatal_error is None
   И хоть одна операция run_when_errors=ONLY_NON_FATAL
   → warning "ENRICH_FATAL_POLICY_UNSET"

6. for op in spec.operations:
       a. if not _should_run_operation(op, builder.errors):
              continue

       b. op_report = _execute_operation(ctx, builder, op, tracker)

       c. summary.record(op_report)
          builder.add_error_item(...)   для каждой ошибки из op_report
          builder.add_warning_item(...) для каждого предупреждения

       d. builder.meta["enrich_events"].extend(events)
          builder.meta["resolve_requests"].extend(hints)

       e. if spec.stop_on_failed and op_report.outcome == FAILED:
              break

7. _store_secrets(builder)

8. builder.meta["enrich_summary"] = summary.as_dict()
   return builder.build()
```

### `_should_run_operation()` — политика запуска

**Файл:** `connector/domain/transform/enrich/enricher_core.py`

```python
def _should_run_operation(op, errors) -> bool:
    if not errors:
        return True                         # нет ошибок → всегда запускаем

    if op.run_when_errors == ALWAYS:
        return True                         # match_key и спец-операции

    if op.run_when_errors == NEVER:
        return False                        # default

    # ONLY_NON_FATAL: запустить только если все ошибки нефатальные
    checker = spec.is_fatal_error
    if checker is None:
        return False                        # без классификатора → как NEVER
    return not any(checker(err) for err in errors)
```

### `_execute_operation()` — разрешение и применение

**Файл:** `connector/domain/transform/enrich/enricher_core.py`

```
1. len(op.targets) != 1 → ENRICH_MULTI_TARGET_UNSUPPORTED (FAILED)

2. key_values = {key: key_registry.resolve(key, result) for key in op.required_keys}
   Если хоть один required_key → None/"" → StrictnessPolicy.on_missing_key

3. candidates, op_error = _collect_candidates(ctx, result, op, key_values)

4. if op_error → _report_by_policy(strictness.on_provider_error)

5. if not candidates:
       if op_type == COMPUTE and op.missing_error_code:
           → _report_by_policy(code=op.missing_error_code)
       else:
           → _report_by_policy(code="ENRICH_NO_CANDIDATES",
                                outcome=strictness.on_no_candidates)

6. decision = ConflictResolver.decide(candidates)
   AMBIGUOUS → ResolveHint в meta + _report_by_policy(strictness.on_ambiguous)
   NONE → _report_by_policy(strictness.on_no_candidates)
   SELECTED → _apply_candidates(builder, op, decision.selected, merge_policy, tracker)
```

**`_report_by_policy()` — преобразование outcome в DiagnosticItem:**

| Outcome | Действие |
|---------|---------|
| `FAILED` | `builder.add_error_item(...)` — строка помечается как ошибочная |
| `WARNED` / `NEEDS_RESOLVE` | `builder.add_warning_item(...)` — строка продолжает путь |
| `SKIPPED` | Без action |

`_report_by_policy()` также атрибутирует enrich-диагностику:
- `field` по умолчанию берётся из `op.error_field` или `op.targets[0]`;
- в `details` кладутся как минимум `rule`, `target`, `reason`;
- report-layer может поднять `details["rule"]` в `ReportDiagnostic.rule`.

### `_collect_candidates()` — три ветки по op_type

**Файл:** `connector/domain/transform/enrich/enricher_core.py`

**COMPUTE** — используется только для `build_match_key`:

```python
def _build_match_key(result, deps):
    parts = [read_value_path(result.row, field) for field in match_key_spec.fields]
    try:
        match_key = build_delimited_match_key(parts, strict=match_key_spec.strict)
    except MatchKeyError:
        return None     # None-поле при strict=True
    return {"match_key": match_key.value}
```

- `strict=True` → `MatchKeyError` при любом `None`-поле
- `strict=False` → `None`-поля пропускаются
- Результат: `"Doe|John|Иванович|u-001"` (через `|`)

**GENERATE** — генерация с retry и проверкой уникальности:

```python
def _generate_candidates(result, op):
    attempts = 0
    while attempts < max(1, op.max_attempts):
        candidate = op.generator(result, self.deps)

        if candidate is None or candidate == "":
            if op.missing_error_code:
                return [], _EnrichOpError(code=op.missing_error_code)
            return [], None

        if op.exists is not None:
            existing = op.exists(self.deps, candidate)
            if existing is not None:
                if op.allow_if and op.allow_if(result, existing):
                    return [CandidateValue(field=target, value=candidate,
                                           source="generated")], None
                attempts += 1
                continue

        return [CandidateValue(field=target, value=candidate, source="generated")], None

    # Исчерпаны все попытки
    if op.conflict_error_code:
        return [], _EnrichOpError(code=op.conflict_error_code,
                                   message="unable to generate unique value")
    return [], None
```

**Flow при повторном запуске (уже есть запись в кэше):**

```
generator("existing-uuid")       # trim → из source
candidate = "existing-uuid"
exists(deps, "existing-uuid")    → {"_id": "...", "match_key": "Doe|John|..."}
allow_if(result, existing)       → equals_path(match_key == existing.match_key) → True
→ вернуть CandidateValue("existing-uuid") несмотря на «конфликт»
```

**Compiled generate path для `user_name`-подобных правил:**

```python
base = base_generator(result, deps)
if condition(result, deps):
    append = append_generator(result, deps)
    candidate = f"{base}{append}"
else:
    candidate = base

existing = exists(deps, candidate)
if existing is not None and not allow_if(result, existing):
    # retry_with_suffixes: base, base+"_2", base+"_3"
```

**LOOKUP** — поиск через провайдеров:

```python
for provider in op.providers:
    fetched = provider.fetch(ctx, result, self.deps, key_values)
    for candidate in fetched:
        if candidate.priority is None:
            candidate = CandidateValue(..., priority=self._priority_for(candidate.source))
        candidates.append(candidate)
```

`_DslLookupProvider.fetch()`:

```python
def fetch(ctx, result, deps, key_values):
    value = _read_rule_value(row, rule)    # rule.source → row[source]
    if rule.ops:
        value, issues = apply_ops(engine, value, rule.ops)
    if value is None or value == "":
        return []
    raw_rows = providers.lookup(rule.provider.name, deps, value, args=rule.provider.args)
    for row_item in raw_rows:
        resolved = read_value_path(row_item, rule.value_path or rule.target)
        yield CandidateValue(field=rule.target, value=resolved, source=provider_name)
```

### `ConflictResolver.decide()` — выбор победителя

**Файл:** `connector/domain/transform/enrich/resolver.py`

```python
def decide(self, candidates: list[CandidateValue]) -> CandidateDecision:
    if not candidates:
        return CandidateDecision(status="NONE")

    if len(candidates) == 1:
        return CandidateDecision(status="SELECTED", selected=candidates[0])

    sorted_cands = sorted(
        candidates,
        key=lambda c: (-(c.priority or 0), -(c.confidence or 0.0))
    )
    top, second = sorted_cands[0], sorted_cands[1]

    if top.priority == second.priority and (top.confidence or 0.0) == (second.confidence or 0.0):
        return CandidateDecision(status="AMBIGUOUS", candidates=sorted_cands)

    return CandidateDecision(status="SELECTED", selected=top, candidates=sorted_cands)
```

**Пример: два провайдера вернули разные значения:**

```
CandidateValue(field="org_code", value="IT-001", source="cache.by_field",    priority=10)
CandidateValue(field="org_code", value="IT-001", source="dictionary.by_key", priority=5)
→ SELECTED (приоритет кэша выше)

CandidateValue(field="org_code", value="IT-001", source="cache.by_field", priority=10)
CandidateValue(field="org_code", value="IT-002", source="cache.by_field", priority=10)
→ AMBIGUOUS → ResolveHint в meta["resolve_requests"]
```

### `MergeEngine.should_apply()` — политика слияния

**Файл:** `connector/domain/transform/enrich/resolver.py`

```python
def should_apply(self, current: Any, candidate: CandidateValue, policy: MergePolicy) -> bool:
    handlers = {
        MergeMode.RECOMPUTE_ALWAYS:          lambda: True,
        MergeMode.NEVER_OVERRIDE:            lambda: False,
        MergeMode.OVERRIDE_IF_AUTHORITATIVE: lambda: candidate.source in self.authoritative_sources,
        MergeMode.OVERRIDE_IF_EMPTY:         lambda: current is None or current == "",
    }
    handler = handlers.get(policy.mode, handlers[MergeMode.OVERRIDE_IF_EMPTY])
    return handler()
```

### `_get_field_value` / `_set_field_value` — трёхветочный dispatch

**Файл:** `connector/domain/transform/enrich/enricher_core.py`

```python
def _get_field_value(builder, field):
    if field == "match_key":
        return builder.match_key.value if builder.match_key else None
    if field.startswith("secret:"):
        key = field.split("secret:", 1)[1]    # "secret:password" → "password"
        return builder.secret_candidates.get(key)
    row = builder.row
    return row.get(field) if isinstance(row, dict) else getattr(row, field, None)


def _set_field_value(builder, field, value):
    if field == "match_key":
        builder.set_match_key(MatchKey(str(value)))
        return
    if field.startswith("secret:"):
        key = field.split("secret:", 1)[1]
        if value is not None:
            builder.set_secret_candidate(key, str(value))
        return
    if isinstance(builder.row, dict):
        builder.row[field] = value
    else:
        setattr(builder.row, field, value)
```

| Поле | Хранится в | Пример |
|------|-----------|--------|
| `"match_key"` | `builder.match_key` (MatchKey) | `MatchKey("Doe|John|...")` |
| `"secret:password"` | `builder.secret_candidates["password"]` | `{"password": "plaintext"}` |
| `"target_id"` | `builder.row["target_id"]` | `{"target_id": "uuid-..."}` |

### `_store_secrets()` — vault flow

**Файл:** `connector/domain/transform/enrich/enricher_core.py`

```python
def _store_secrets(builder):
    if not builder.secret_candidates:
        return   # нет секретов → ранний выход

    if builder.match_key is None:
        builder.add_error_item(_make_error(code="SECRET_MATCH_KEY_MISSING"))
        return

    if self.secret_store is not None:
        self.secret_store.put_many(
            dataset=self.dataset,
            match_key=builder.match_key.value,
            secrets=builder.secret_candidates,   # {"password": "plaintext"}
            run_id=self.run_id,
        )

    secret_fields = list(builder.secret_candidates.keys())
    builder.meta["secret_fields"] = secret_fields
    _clear_secret_fields(builder, secret_fields)   # row[field] = None
    builder.secret_candidates = {}
```

**Инварианты `_store_secrets()`:**

| Условие | Результат |
|---------|----------|
| `secret_candidates` пустой | Ранний выход, vault не вызывается |
| `match_key is None` | `SECRET_MATCH_KEY_MISSING` error; vault не вызывается |
| `secret_store is None` | Секреты НЕ записываются в vault; строка всё равно зачищается |
| Vault exception | `SECRET_STORE_ERROR` error; строка зачищается |
| Успех | `meta["secret_fields"] = [...]`; `row[field] = None`; `secret_candidates = {}` |

> Зачистка строки (`row[field] = None`) происходит всегда — даже при vault-ошибке.
> Plaintext никогда не передаётся в MatchStage.

### `EnrichStage.run()` — pipeline wrapper

**Файл:** `connector/domain/transform/stages/stages.py`

```python
def run(self, source: Iterable[TransformResult]) -> Iterable[TransformResult]:
    for collected in source:
        boundary_errors: list = []
        enriched: TransformResult | None = None

        with diagnostic_boundary(stage=DiagnosticStage.ENRICH, ...):
            enriched = self.enricher.enrich(collected)

        if enriched is None:
            builder = collected.as_builder()
            builder.set_row(None)
            for err in boundary_errors:
                builder.add_error_item(err)
            yield builder.build()
            continue

        builder = enriched.as_builder()
        for err in boundary_errors:
            builder.add_error_item(err)
        yield builder.build()
```

**`diagnostic_boundary`** перехватывает неожиданные исключения → `boundary_errors`.
Pipeline не падает — ошибка фиксируется и запись помечается как ошибочная.

> В отличие от `NormalizeStage`, `EnrichStage` **не пропускает** записи с ошибками.
> Он передаёт их `EnricherCore`, который сам решает через `_should_run_operation()`.
> Это позволяет `build_match_key` (ALWAYS) выполняться даже для проблемных записей.

### `EnricherEngine` — два пути инициализации

**Файл:** `connector/domain/transform/enrich/enricher_engine.py`

**Путь 1 (`ctx: StageExecutionContext`, новый):**

```python
if ctx is not None:
    effective_deps = SimpleNamespace(
        cache_gateway=ctx.get(EnrichLookupPort),       # может быть None
        secret_store=ctx.get(SecretStoreProtocol),     # может быть None
        dictionaries=ctx.get(DictionaryProviderPort),  # может быть None
    )
    resolved_dataset   = ctx.metadata.dataset_name
    resolved_catalog   = ctx.metadata.catalog
    resolved_sink_spec = sink_spec or ctx.metadata.sink_spec
```

**Путь 2 (scattered params, legacy/тесты):**

```python
else:
    effective_deps     = deps          # пользователь сам создаёт deps
    resolved_secret    = secret_store
    resolved_dataset   = dataset or ""
    resolved_catalog   = catalog or ErrorCatalog(...)
```

В обоих путях финал одинаков:

```python
if providers is None:
    providers = ProviderGateway.with_defaults()
core_spec = EnricherDsl(registry, providers, options).compile(spec)
self.core = EnricherCore(spec=core_spec, deps=effective_deps, ...)
```

---

## 🔄 Взаимодействие с другими слоями

### TransformResult до и после enrich

| Поле | После normalize (до enrich) | После enrich |
|------|----------------------------|--------------|
| `row` | `{"last_name": "Doe", "target_id": None, "password": None, ...}` | `{"last_name": "Doe", "target_id": "u-123", "password": None, ...}` |
| `record` | Иммутабельный `SourceRecord` | Не изменяется |
| `row_ref` | `None` | Не изменяется (`None`) |
| `match_key` | `None` | `MatchKey("Doe|John|Иванович|u-001")` |
| `secret_candidates` | `{}` | `{}` (очищен после vault write) |
| `meta` | `{}` | `{"enrich_events":[...], "enrich_summary":{...}, "secret_fields":["password"]}` |
| `errors` | Ошибки из map + normalize | + ошибки enrich-операций (FAILED) |
| `warnings` | Предупреждения из map + normalize | + предупреждения enrich-операций (WARNED) |

### Позиция в pipeline

```
MapStage
    ↓ TransformResult(row=dict c raw типами)
NormalizeStage
    ↓ TransformResult(row=dict c Python-типами: bool, int, ...)
EnrichStage         ← текущий слой
    ↓ TransformResult(match_key=MatchKey(...), meta["enrich_events"]=[...])
MatchStage
    ↓ TransformResult(row_ref=RowRef(...))
ResolveStage
```

**Что передаётся MatchStage:**
- `row` — обогащённый dict; secret-поля = `None`
- `match_key` — установлен (или error если `MATCH_KEY_MISSING`)
- `meta["enrich_events"]` — полный аудит изменений
- `meta["enrich_summary"]` — счётчики операций
- `meta["secret_fields"]` — список имён secret-полей

### Сборка в delivery

```python
# containers.py
enrich_context = providers.Factory(
    _build_enrich_context,
    metadata=pipeline_meta,
    cache_roles=cache.roles,
    secret_store=secret_store,
    dictionaries=dictionary_runtime,
)
enrich_stage = providers.Factory(
    _create_stage,
    stage_type=EnrichStage,
    ctx=enrich_context,
    spec=enrich_spec,
)
```

---

## 🔌 Контракты и границы

**Enrich-пакет** (`connector/domain/transform/enrich/`) содержит только:
- `EnricherCore` — исполнитель операций
- `EnricherEngine` — DSL-обвязка
- `ConflictResolver`, `MergeEngine`, `_FieldMutationTracker` — вспомогательные алгоритмы
- `EnricherReport`, models, providers Protocol

**Запрещённые импорты в `enricher_core.py`:**
- `connector/infra/` — никакой инфраструктуры напрямую
- `connector/delivery/` — никакой доставки
- Конкретные классы `CacheGateway`, `SqliteVaultRepository`, `DictionaryRuntime`

**Паттерн изоляции через `SimpleNamespace deps`:**

```python
# EnricherEngine создаёт deps:
effective_deps = SimpleNamespace(
    cache_gateway=ctx.get(EnrichLookupPort),       # Protocol, не конкретный класс
    secret_store=ctx.get(SecretStoreProtocol),
    dictionaries=ctx.get(DictionaryProviderPort),
)

# EnricherCore и ProviderGateway используют:
cache_gateway = getattr(deps, "cache_gateway", None)  # не знает о конкретном типе
```

**Правила изоляции:**

| ❌ Нарушение | ✅ Правильно |
|-------------|-------------|
| Импорт `CacheGateway` в `enricher_core.py` | Работать только с `EnrichLookupPort` Protocol |
| Вызов `find_one()` напрямую в `EnricherCore` | Делать через `ProviderGateway` и `CandidateProvider` |
| Добавить новый провайдер в `enricher_core.py` | Зарегистрировать в `ProviderGateway` |
| Создать `AppContainer()` внутри enrich | DI-wiring только в `connector/delivery/` |
| Хранить `StageExecutionContext` как поле класса | Распаковывать в `EnricherEngine.__init__()` |
| Модифицировать `result.meta` напрямую | Использовать `builder.meta[key] = ...` |

---

## 🛠️ HOW-TO

### Дебаг enrich через meta["enrich_events"]

```python
result = enricher.enrich(transform_result)
for event in result.meta.get("enrich_events", []):
    print(f"{event['op']}.{event['field']}: {event['before']!r} → {event['after']!r}")
    print(f"  source={event['source']}, decision={event['decision']}, outcome={event['outcome']}")
```

Типичные значения `decision`:
- `"applied"` — нормальная запись
- `"policy_skip"` — merge_policy запретила перезапись
- `"conflict_skipped"` — другая операция уже записала
- `"overridden_previous_op"` — merge_policy разрешила перезапись поверх

---

### Дебаг resolve_requests (AMBIGUOUS)

```python
for hint in result.meta.get("resolve_requests", []):
    print(f"AMBIGUOUS {hint['field']}: {len(hint['candidates'])} кандидатов")
    for cand in hint["candidates"]:
        print(f"  source={cand['source']}, value={cand.get('value')}")
```

---

### Написать unit-тест с минимальными зависимостями

```python
from types import SimpleNamespace
from connector.domain.transform.enrich.enricher_engine import EnricherEngine
from connector.domain.transform_dsl.loader import load_enrich_spec_for_dataset

def test_enrich_sets_match_key():
    spec = load_enrich_spec_for_dataset("employees")
    engine = EnricherEngine(
        spec=spec,
        dataset="employees",
        catalog=ErrorCatalog(dataset="employees", items={}),
        deps=SimpleNamespace(cache_gateway=None, dictionaries=None),
    )
    result = make_transform_result(row={
        "last_name": "Doe", "first_name": "John",
        "middle_name": "Petr", "personnel_number": "123",
        "target_id": None, "password": None,
    })
    enriched = engine.enrich(result)
    assert enriched.match_key is not None
    assert "Doe" in enriched.match_key.value
```

---

### Добавить новый тип операции

Если стандартных COMPUTE/GENERATE/LOOKUP недостаточно:

1. Добавить значение в `EnrichOperationType` в `connector/domain/transform/enrich/models.py`
2. Добавить ветку в `_collect_candidates()` в `connector/domain/transform/enrich/enricher_core.py`
3. Добавить builder-функцию в `connector/domain/transform_dsl/compilers/enrich.py`
4. Вызвать из `build_enricher_spec_from_dsl()` при нужных условиях DSL
5. Добавить тест в `tests/unit/transform/test_enricher.py`

> Не добавляй инфраструктурные вызовы напрямую в `enricher_core.py` —
> используй Protocol в `providers.py` и новый провайдер в `providers/registry.py`.

---

## 💡 Типичные сценарии

### Сценарий 1: Первый запуск — генерация UUID

```
Строка: {"last_name": "Doe", "target_id": None, ...}

op: build_match_key (COMPUTE, ALWAYS)
    parts = ["Doe", "John", "Иванович", "u-001"]
    match_key = MatchKey("Doe|John|Иванович|u-001")
    event(op="build_match_key", decision="applied", outcome="APPLIED")

op: target_id (GENERATE, NEVER, fill_only_if_empty)
    generator → None → default_uuid → "new-uuid-456"
    exists(deps, "new-uuid-456") → None (свободен)
    ConflictResolver → SELECTED
    MergeEngine.should_apply(None, ..., OVERRIDE_IF_EMPTY) → True
    _set_field_value("target_id", "new-uuid-456")
    event(before=None, after="new-uuid-456", outcome="APPLIED")
```

---

### Сценарий 2: Повторный запуск — allow_if принимает существующий UUID

```
Строка: {"last_name": "Doe", "target_id": "existing-uuid", ...}

op: target_id (GENERATE)
    generator → "existing-uuid" (из source: target_id)
    exists → {"_id": "existing-uuid", "match_key": "Doe|John|..."}
    allow_if: equals_path(result.match_key, existing["match_key"])
        → "Doe|John|..." == "Doe|John|..." → True
    → принять "existing-uuid"
```

---

### Сценарий 3: Конфликт, поле пропущено (on_error: warn)

```
op: org_code (LOOKUP, on_error: warn)
    source = "organization_id" → "UNKNOWN-ORG"
    providers.lookup("cache.by_field", deps, "UNKNOWN-ORG") → []
    strictness.on_no_candidates = WARNED
    → builder.add_warning_item(code="ENRICH_NO_CANDIDATES")
    → OperationReport(outcome=WARNED)

Строка продолжает путь: org_code = None
```

---

### Сценарий 4: Запись пароля в Vault

```
op: password (GENERATE, target="secret:password")
    generator → "Passw0rd!23"
    _set_field_value("secret:password", "Passw0rd!23")
    → builder.secret_candidates = {"password": "Passw0rd!23"}

_store_secrets():
    secret_store.put_many(
        dataset="employees",
        match_key="Doe|John|...",
        secrets={"password": "Passw0rd!23"},
    )
    meta["secret_fields"] = ["password"]
    row["password"] = None   ← зачищено
    secret_candidates = {}
```

---

### Сценарий 5: stop_on_failed — прерывание при MATCH_KEY_MISSING

```
op: build_match_key (ALWAYS)
    parts = [None, "John", ...]   ← personnel_number = None
    build_delimited_match_key([None, ...], strict=True) → MatchKeyError
    candidates = []
    → _report_by_policy(FAILED, "MATCH_KEY_MISSING")

if spec.stop_on_failed:
    break   ← все дальнейшие операции не выполняются

_store_secrets():
    secret_candidates пуст → ранний выход

builder.errors = [DiagnosticItem(code="MATCH_KEY_MISSING", stage=ENRICH)]
```

---

## 📌 Важные детали

| Деталь | Описание |
|--------|----------|
| `build_match_key` всегда ALWAYS | Выполняется даже при ошибках — match_key нужен для диагностики и vault |
| EnrichStage не пропускает errors | Решение принимает EnricherCore через `_should_run_operation()`, не стадия |
| `row=None` pass-through | Если `result.row is None` — немедленный возврат без обработки |
| Зачистка secret-полей | `row[field] = None` происходит всегда, даже при vault-ошибке — plaintext не утекает |
| `fill_only_if_empty` == `override_if_empty` | Оба маппятся в `MergeMode.OVERRIDE_IF_EMPTY` — синонимы |
| AMBIGUOUS не ошибка по умолчанию | `on_ambiguous = NEEDS_RESOLVE` → предупреждение + `ResolveHint` в meta |
| `_FieldMutationTracker` per-record | Создаётся заново для каждой записи в `EnricherCore.enrich()` |
| Stateless core | `EnricherCore` не хранит состояния между записями — безопасен для последовательного вызова |

---

## 🧪 Тестовое покрытие

| Файл | Что тестирует |
|------|--------------|
| `tests/unit/transform/test_enricher.py` | EnricherCore алгоритм, generate retry, conflict resolution, _store_secrets |
| `tests/unit/transform/test_enrich_dsl.py` | Template expansion, allow_if, value_path, provider contract |
| `tests/integration/transform/test_dsl_build_options.py` | Merge build options для enrich |
| `tests/integration/secrets/test_enrich_vault_write_service.py` | Vault write с шифрованием |
| `tests/e2e/pipelines/test_enrich_pipeline.py` | Полный pipeline с CLI |
| `tests/unit/transform/test_pipeline_stage_contract.py` | EnrichStage как участник pipeline |

---

## ❓ FAQ

**Как EnricherCore узнаёт о vault?**

Через `deps.secret_store` — поле `SimpleNamespace`, которое заполняет `EnricherEngine`
из `ctx.get(SecretStoreProtocol)`. Если vault не подключён — `secret_store is None`,
секреты записываются в `meta["secret_fields"]` но не в vault.

**Почему CandidateValue, а не просто значение?**

`CandidateValue` несёт метаданные: `source` (для MergeEngine.OVERRIDE_IF_AUTHORITATIVE),
`priority` (для ConflictResolver), `evidence` (для ResolveHint). Без обёртки
`ConflictResolver` не может принять решение о выборе из нескольких кандидатов.

**Что такое ResolveHint и зачем он нужен?**

`ResolveHint` — подсказка для `ResolveStage` при неоднозначных кандидатах (AMBIGUOUS).
Хранится в `meta["resolve_requests"]`. Позволяет оператору вручную выбрать правильную
запись или настроить автоматическое разрешение (дополнительные ограничения в DSL).

**Как работает stop_on_failed?**

Если `EnricherSpec.stop_on_failed=True` и операция вернула `outcome=FAILED` — цикл
прерывается. Оставшиеся операции не выполняются. Запись продолжает путь в pipeline
с `row` (не `None`) но с errors — это отличие от mapper/normalize: enrich не обнуляет `row`.

**Почему EnrichStage не пропускает записи с ошибками (как NormalizeStage)?**

Потому что `build_match_key` с `run_when_errors=ALWAYS` должен выполняться даже при ошибках.
Если бы стадия пропускала записи с ошибками — match_key не был бы вычислен, и MatchStage
не смог бы идентифицировать запись для диагностики.

---

## 🔗 Связанные документы

| Документ | Описание |
|----------|---------|
| [enrich-dsl.md](enrich-dsl.md) | YAML-спецификация: EnrichRule, merge-политики, template-система, build options |
| [enrich-infra.md](enrich-infra.md) | Порты, ProviderGateway, StageExecutionContext, DI-wiring, изоляция |
| [normalizer-core.md](../normalizer/normalizer-core.md) | Предыдущая стадия pipeline (NormalizerCore) |
| [docs/dev/layers/vault/vault-core.md](../vault/vault-core.md) | Vault pipeline: enrich → plan → apply |
| `connector/domain/transform/enrich/enricher_core.py` | Главный файл реализации (608 строк) |

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-03-01 | Создан документ — core-алгоритм enrich-слоя | xORex-LC |
| 2026-05-06 | Документ синхронизирован с compiled generate path (`base_generator/condition/append_generator/conflict_policy`), новым порядком `exists → allow_if → on_conflict` и атрибутированными enrich diagnostics | xORex-LC |
