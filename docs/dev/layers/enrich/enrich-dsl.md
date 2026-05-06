# Enrich DSL — спецификации правил обогащения и генерации

> `EnrichSpec` описывает три блока операций enrich-стадии: построение `match_key`, генерацию значений (`generate`) и обогащение через внешние источники (`lookup`) — в виде декларативного YAML, компилируемого в `EnricherSpec` при старте.

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

Enrich — третья стадия transform-pipeline. Принимает нормализованную строку и выполняет
три логических блока операций, описанных декларативно в `*.enrich.yaml`:

1. **match_key** — вычисляет ключ идентификации записи из заданных полей (`personnel_number|last_name|...`)
2. **generate** — генерирует значения через цепочку операций, проверяет уникальность через кэш
3. **lookup** — ищет значения во внешних источниках (кэш, справочники)

**Файловая структура слоя:**

```
connector/domain/transform_dsl/
├── specs/
│   └── enrich.py              # EnrichSpec, EnrichBlock, EnrichRule,
│                              # MatchKeySpec, SecretsSpec, ProviderRef, ExistsRef
├── compilers/
│   └── enrich.py              # EnricherDsl, EnricherSpec, EnrichmentOperation, KeyRegistry
├── build_options.py           # EnrichDslBuildOptions
└── loader.py                  # load_enrich_spec_for_dataset,
                               # _expand_enrich_templates,
                               # load_enrich_build_options_for_dataset

connector/domain/transform/
├── providers/
│   └── registry.py            # ProviderGateway, 5 встроенных провайдеров
└── enrich/
    ├── enricher_engine.py     # EnricherEngine (DSL-обвязка)
    ├── enricher_core.py       # EnricherCore (исполнитель)
    └── models.py              # CandidateValue, MergeMode, StrictnessPolicy, ...

datasets/
└── employees.enrich.yaml      # Пример DSL-конфига
```

---

## 🏗️ Архитектура слоя

```
datasets/registry.yml
        │
        │  (stage="enrich", post_load=_expand_enrich_templates)
        ▼
load_enrich_spec_for_dataset()
        │
        │  (pre-processing: template/preset expansion)
        │
        ▼
EnrichSpec (Pydantic)
  └── EnrichBlock
        ├── match_key: MatchKeySpec | None
        ├── secrets: SecretsSpec | None
        ├── generate: [EnrichRule, ...]
        └── lookup: [EnrichRule, ...]
        │
        ▼
EnricherDsl.compile(spec)
  ├── _validate_ops_known()         (если fail_on_unknown_ops)
  └── build_enricher_spec_from_dsl()
        │
        ├── 1. _build_match_key_operation()   → run_when_errors=ALWAYS, первая
        ├── 2. _build_lookup_operation(x N)   → provider wrapping
        └── 3. _build_generate_operation(x N) → secret: prefix injection, conditional build
        │
        ▼
EnricherSpec (frozen compiled)
  └── operations: tuple[EnrichmentOperation, ...]
        │
        ▼
EnricherCore.enrich(result)   (применяется к каждой записи)
```

| Компонент | Файл | Ответственность |
|-----------|------|-----------------|
| `EnrichSpec` | `specs/enrich.py` | Pydantic-модель YAML-файла |
| `EnrichBlock` | `specs/enrich.py` | Контейнер match_key + secrets + правила |
| `EnrichRule` | `specs/enrich.py` | Одно правило (generate или lookup) |
| `MatchKeySpec` | `specs/enrich.py` | Поля для построения match_key |
| `SecretsSpec` | `specs/enrich.py` | Поля, направляемые в vault |
| `EnricherDsl` | `compilers/enrich.py` | Компилятор spec → EnricherSpec |
| `EnricherSpec` | `compilers/enrich.py` | Frozen скомпилированная спека |
| `EnrichmentOperation` | `compilers/enrich.py` | Compiled операция (callable + policy) |
| `ProviderGateway` | `providers/registry.py` | Runtime-реестр lookup/exists функций |
| `EnrichDslBuildOptions` | `build_options.py` | Compile-policy |

---

## 🔑 Ключевые абстракции

### MatchKeySpec — ключ идентификации записи

**Файл:** `connector/domain/transform_dsl/specs/enrich.py`

```python
class MatchKeySpec(DslBaseModel):
    fields: list[str]
    strict: bool = True
```

```yaml
match_key:
  fields: [last_name, first_name, middle_name, personnel_number]
  strict: true
```

| Параметр | Значение |
|----------|----------|
| `fields` | Список имён полей из `row` (порядок важен — формирует ключ через `\|`) |
| `strict=True` | Если хоть одно поле `None` или пусто → `MATCH_KEY_MISSING` error |
| `strict=False` | Пустые поля пропускаются, ключ строится из имеющихся |

**Результат:** `match_key = "Doe|John|Иванович|u-001"` (поля соединяются через `|`).

**Операция** `build_match_key` компилируется как первая в `EnricherSpec.operations`
и всегда выполняется с `run_when_errors=ALWAYS` — даже если предыдущие стадии
дали ошибки, match_key нужен для диагностики и vault.

### SecretsSpec — поля для vault

**Файл:** `connector/domain/transform_dsl/specs/enrich.py`

```python
class SecretsSpec(DslBaseModel):
    fields: list[str] = []
```

```yaml
secrets:
  fields: [password]
```

**Механизм:** При компиляции `_build_generate_operation()` проверяет:

```python
target = rule.target
if target in secrets_spec.fields:
    target = f"secret:{target}"   # ← "password" → "secret:password"
```

После этого `EnricherCore._set_field_value("secret:password", value)` записывает значение
в `builder.secret_candidates["password"]`, а не в `builder.row["password"]`.

По завершении всех операций `_store_secrets()` отправляет `secret_candidates`
в `SecretStoreProtocol.put_many()` и очищает их из `row`.

### EnrichRule — атомарное правило

**Файл:** `connector/domain/transform_dsl/specs/enrich.py`

Единое правило как для `generate`, так и для `lookup`:

```python
class EnrichRule(DslBaseModel):
    name: str
    target: str
    build: SourceOpsBlock | None = None
    when: EnrichConditionalBlock | None = None
    then: EnrichConditionalBlock | None = None
    provider: ProviderRef | None = None
    value_path: str | None = None
    source: str | None = None
    sources: list[str] | None = None
    ops: list[OperationCall] = []
    on_error: Literal["error", "warn"] = "error"
    merge: Literal[...] | None = None
    exists: ExistsRef | None = None
    allow_if: OperationCall | str | None = None
    on_conflict: EnrichConflictPolicy | None = None
    max_attempts: int | None = None
    run_when_errors: Literal["never", "if_any", "always"] | None = None
    missing_error_code: str | None = None
    conflict_error_code: str | None = None
    error_field: str | None = None
```

Сахар `allow_if: str` — если задана строка, оборачивается в `OperationCall(op=str, args={})`.

| Поле | Обязательность | Описание |
|------|----------------|----------|
| `name` | Да | Уникальный идентификатор операции. Используется в `enrich_events` и диагностике |
| `target` | Да | Поле назначения в `row` (или `"match_key"` для match_key операции) |
| `build` | Нет | Базовый source/sources + ops pipeline для `generate` |
| `when` | Нет | Predicate block для условного append в `generate` |
| `then` | Нет | Append block; выполняется только если `when == true` |
| `provider` | Нет | Ссылка на провайдер (обязателен для `lookup` правил) |
| `value_path` | Нет | Путь к значению в ответе провайдера (`"_id"`, `"org_code"`) |
| `source` | Нет | Имя поля из `row` — входное значение для ops/provider |
| `sources` | Нет | Несколько входных полей (ops получают список) |
| `ops` | Нет | Постобработка (generate) или подготовка ключа (lookup) |
| `on_error` | Нет (`"error"`) | Severity при ошибке операции |
| `merge` | Нет | Политика слияния |
| `exists` | Нет | Проверка уникальности (только для generate) |
| `allow_if` | Нет | Условие принятия при конфликте exists |
| `on_conflict` | Нет | enrich-specific политика `error` / `retry_with_suffixes` |
| `max_attempts` | Нет (`3` при compile) | Количество попыток при конфликте uniqueness |
| `run_when_errors` | Нет (`"never"`) | Политика запуска при наличии ошибок |
| `missing_error_code` | Нет | Кастомный код ошибки при пустом результате |
| `conflict_error_code` | Нет | Кастомный код ошибки при исчерпании попыток |
| `error_field` | Нет | Поле для привязки диагностики |

### Два типа правил: `generate` vs `lookup`

**`generate` правила** — генерируют значение через ops-цепочку или через расширенный `build/when/then` контракт с проверкой уникальности:

```yaml
generate:
  - name: user_name
    target: user_name
    build:
      source: first_name
      ops:
        - op: trim
        - op: transliterate
    when:
      source: first_name
      ops:
        - op: contains_non_ascii
    then:
      sources: [last_name, middle_name]
      ops:
        - op: map_each
          args:
            ops:
              - op: transliterate
              - op: substring
                args: { start: 0, length: 1 }
        - op: compact
        - op: concat
    exists:                      # Проверить что значение уникально
      provider:
        name: cache.exists_by_field
        args:
          dataset: employees
          field: user_name
    allow_if: equals_path
    on_conflict:
      strategy: retry_with_suffixes
      suffixes: ["_2", "_3"]
    merge: fill_only_if_empty
    conflict_error_code: USER_NAME_CONFLICT
    error_field: user_name
```

**`lookup` правила** — запрашивают значения из внешних источников:

```yaml
lookup:
  - name: org_name
    target: org_name
    source: organization_id      # Ключ для поиска
    provider:
      name: dictionary.by_key
      args:
        dict_name: organizations
        fields: [name, short_name]
    value_path: name             # Какое поле из ответа взять
    on_error: warn
    merge: fill_only_if_empty
```

**Ключевое отличие:**
- `generate`: `ops` применяются к `source`-значению → генерируют новое; `exists` проверяет уникальность
- `lookup`: `ops` применяются к ключу поиска; провайдер возвращает кандидатов; `value_path` извлекает нужное поле

### `build / when / then / on_conflict` — новый generate-контракт

- `build` формирует **base value**.
- `when` вычисляет predicate по `source/sources + ops`.
- `then` формирует **append value** и не заменяет base value.
- итоговый candidate для compiled-пути: `base_value + append_value`.
- `on_conflict.retry_with_suffixes` пробует `base`, затем `base + suffix` для каждого suffix.

**Ограничения первой версии:**
- один `when` и один `then` на правило;
- `then` нельзя использовать без `when`;
- `then` не получает прямой доступ к `base_value`;
- `lookup` не поддерживает `build/when/then/on_conflict`.

### `allow_if` — условное принятие при конфликте exists

`allow_if` используется совместно с `exists` в generate-правилах:
когда exists нашёл запись в кэше, `allow_if` решает — принять сгенерированное значение
или попробовать ещё раз.

```yaml
- name: usr_org_tab_num
  target: usr_org_tab_num
  source: usr_org_tab_num
  ops:
    - op: trim
    - op: default_prefixed_uuid
      args:
        prefix: "TAB-"
  exists:
    provider:
      name: cache.exists_by_field
      args:
        dataset: employees
        field: usr_org_tab_num
        include_deleted: true
  max_attempts: 3
  allow_if:
    op: equals_path
    args:
      left: match_key           # match_key текущей строки
      right: existing.match_key # match_key найденной в кэше строки
  conflict_error_code: USR_ORG_TAB_CONFLICT
  error_field: usrOrgTabNum
```

**Алгоритм:**
```
candidate = generate()
existing = cache.exists_by_field(candidate)
if existing is not None:
    if allow_if(result, existing):
        → принять (та же запись)
    else:
        candidate = None, attempts += 1
        → попробовать другой UUID
```

`allow_if` получает `(result: TransformResult, existing: dict)` — результат запроса к кэшу.
`equals_path` сравнивает `result.match_key` с `existing["match_key"]`.

### `ProviderRef` и `ExistsRef`

**Файл:** `connector/domain/transform_dsl/specs/enrich.py`

```python
class ProviderRef(DslBaseModel):
    name: str                              # "cache.by_field", "dictionary.by_key", ...
    args: dict[str, Any] = {}

class ExistsRef(DslBaseModel):
    provider: ProviderRef
```

`ProviderRef.name` — ключ в `ProviderGateway`. Встроенные значения:
- `"cache.by_field"` — lookup через кэш
- `"cache.exists_by_field"` — exists-проверка через кэш
- `"dictionary.by_key"` — lookup через справочник
- `"dictionary.canonicalize"` — канонизация значения через справочник
- `"dictionary.exists_by_key"` — exists-проверка через справочник

---

## 🗂️ Модели данных

### Merge-политики (`MergeMode`)

**Файл:** `connector/domain/transform/enrich/models.py`

Определяют, когда enrich перезаписывает уже имеющееся значение поля:

```yaml
merge: fill_only_if_empty    # или recompute_always, override_if_empty, ...
```

| Значение DSL | MergeMode | Поведение |
|-------------|-----------|-----------|
| `fill_only_if_empty` | `FILL_ONLY_IF_EMPTY` | Записать только если поле `None` или пустая строка |
| `recompute_always` | `RECOMPUTE_ALWAYS` | Всегда перезаписывать (default для generate) |
| `override_if_empty` | `OVERRIDE_IF_EMPTY` | Перезаписать если текущее значение пустое (None/"") |
| `override_if_authoritative` | `OVERRIDE_IF_AUTHORITATIVE` | Перезаписать если source в `authoritative_sources` |
| `never_override` | `NEVER_OVERRIDE` | Никогда не перезаписывать уже установленное |

**Дефолт:** Если `merge` не задан, используется `EnricherSpec.default_merge_policy` = `fill_only_if_empty`.

### Strictness-политики (`StrictnessPolicy`)

**Файл:** `connector/domain/transform/enrich/models.py`

`on_error` в YAML транслируется в `StrictnessPolicy`:

```python
@dataclass(frozen=True)
class StrictnessPolicy:
    on_missing_key: str = EnrichOutcome.SKIPPED
    on_no_candidates: str = EnrichOutcome.SKIPPED
    on_ambiguous: str = EnrichOutcome.NEEDS_RESOLVE
    on_provider_error: str = EnrichOutcome.WARNED
```

| `on_error` (YAML) | `on_no_candidates` | Итог |
|-------------------|--------------------|------|
| `error` (дефолт) | `FAILED` | `DiagnosticItem` в errors → `row = None` |
| `warn` | `WARNED` | `DiagnosticItem` в warnings → запись продолжает путь |

Маппинг в компиляторе (`_strictness_for(rule)`):
- `on_error="error"` → `StrictnessPolicy(on_no_candidates=FAILED, on_missing_key=FAILED)`
- `on_error="warn"` → `StrictnessPolicy(on_no_candidates=WARNED, on_missing_key=SKIPPED)`

### `run_when_errors` — политика запуска при ошибках

```yaml
run_when_errors: never    # never | if_any | always
```

| Значение | Компилируется в | Поведение |
|----------|-----------------|-----------|
| `never` (дефолт) | `RunWhenErrors.NEVER` | Не запускать если `builder.errors` не пусты |
| `if_any` | `RunWhenErrors.ONLY_NON_FATAL` | Запускать если ошибки есть; требует `is_fatal_error` classifier |
| `always` | `RunWhenErrors.ALWAYS` | Запускать всегда (используется в `build_match_key`) |

**Важно:** `match_key` операция всегда компилируется с `run_when_errors=ALWAYS`.

### `EnrichDslBuildOptions`

**Файл:** `connector/domain/transform_dsl/build_options.py`

```python
@dataclass(frozen=True)
class EnrichDslBuildOptions(BaseDslBuildOptions):
    require_match_key: bool = False
```

| Параметр | Тип | Дефолт | Описание |
|----------|-----|--------|----------|
| `require_match_key` | `bool` | `False` | `DslLoadError` при отсутствии `match_key` в DSL |
| `fail_on_unknown_ops` | `bool` | `True` | `DslLoadError` при неизвестной op в `ops`/`allow_if` |
| `strict` | `bool` | `False` | `DslLoadError` при неизвестных ключах в `build_options` |

### Полный аннотированный YAML: `employees.enrich.yaml`

**Файл:** `datasets/employees.enrich.yaml`

```yaml
dataset: employees              # Идентификатор датасета

enrich:
  # match_key: вычисляется ПЕРВОЙ (run_when_errors=ALWAYS)
  match_key:
    fields: [last_name, first_name, middle_name, personnel_number]
    strict: true               # None в любом поле → MATCH_KEY_MISSING error

  # secrets: поля, уходящие в Vault (не в row)
  secrets:
    fields: [password]

  generate:
    - name: target_id          # Имя операции (в enrich_events)
      target: target_id
      source: target_id
      ops:
        - op: trim
        - op: default_uuid
      exists:
        provider:
          name: cache.exists_by_field
          args:
            dataset: employees
            field: _id
            include_deleted: true
      max_attempts: 3
      merge: recompute_always
      missing_error_code: TARGET_ID_MISSING
      conflict_error_code: TARGET_ID_CONFLICT
      error_field: target_id

    - name: usr_org_tab_num
      target: usr_org_tab_num
      source: usr_org_tab_num
      ops:
        - op: trim
        - op: default_prefixed_uuid
          args:
            prefix: "TAB-"
      allow_if:               # Принять совпадение, если та же запись
        op: equals_path
        args:
          left: match_key
          right: existing.match_key
      exists:
        provider:
          name: cache.exists_by_field
          args:
            dataset: employees
            field: usr_org_tab_num
            include_deleted: true
      max_attempts: 3
      merge: recompute_always
      conflict_error_code: USR_ORG_TAB_CONFLICT
      error_field: usrOrgTabNum

    - name: password
      target: password         # ← в secrets.fields → compile: "secret:password"
      source: password
      ops:
        - op: trim
        - op: default_password
      merge: fill_only_if_empty
      on_error: warn

  lookup: []                   # Пусто в employees
```

---

## 📊 Ключевые методы и алгоритмы

### `load_enrich_spec_for_dataset(dataset)` — загрузка с template expansion

**Файл:** `connector/domain/transform_dsl/loader.py`

```
1. _load_registry_or_raise()
   → читает datasets/registry.yml
2. _resolve_dataset_path(registry, dataset, stage="enrich")
   → registry["datasets"][dataset]["enrich"] → путь к файлу
3. _read_yaml_or_raise(path)
   → читает YAML → raw dict
4. _expand_enrich_templates(raw)       ← pre-processing ПЕРЕД Pydantic
   → разворачивает template/preset-ссылки в lookup-правилах
5. _validate_spec_or_raise(raw, EnrichSpec)
   → EnrichSpec.model_validate(raw)
```

### `_expand_enrich_templates()` — template expansion

**Файл:** `connector/domain/transform_dsl/loader.py`

Позволяет переиспользовать повторяющиеся lookup-конфигурации:

```yaml
enrich:
  lookup_templates:             # или lookup_presets (синонимы)
    by_org_id:
      provider:
        name: cache.by_field
        args:
          dataset: organizations
          field: _id
      on_error: warn
      merge: fill_only_if_empty

  lookup:
    - name: org_code
      target: org_code
      source: organization_id
      template: by_org_id       # ← ссылка на шаблон
      value_path: org_code      # ← перекрывает шаблонный value_path
```

**Алгоритм:**

```python
def _expand_enrich_templates(raw):
    templates = enrich.get("lookup_templates") or enrich.get("lookup_presets") or {}
    lookup_rules = enrich.get("lookup") or []
    expanded = []
    for rule in lookup_rules:
        template_name = rule.pop("template", None) or rule.pop("preset", None)
        if template_name:
            template = templates[template_name]
            merged = {**template, **rule}   # ← rule перекрывает template
            expanded.append(merged)
        else:
            expanded.append(rule)
    enrich["lookup"] = expanded
    enrich.pop("lookup_templates", None)
    enrich.pop("lookup_presets", None)
```

**Правило merge:** `{**template, **rule}` — поля rule перекрывают template.
После expansion Pydantic видит уже развёрнутые правила.

### `build_enricher_spec_from_dsl()` — алгоритм компиляции

**Файл:** `connector/domain/transform_dsl/compilers/enrich.py`

```
1. options = EnrichDslBuildOptions() или из args

2. Если options.require_match_key И match_key_spec is None:
   → DslLoadError(code="ENRICH_DSL_COMPILE_INVALID")

3. Если match_key_spec is not None:
   operations.append(_build_match_key_operation(match_key_spec))
   → EnrichmentOperation(
       name="build_match_key",
       op_type=COMPUTE,
       targets=("match_key",),
       run_when_errors=ALWAYS,
       strictness=StrictnessPolicy(on_provider_error=FAILED),
       missing_error_code="MATCH_KEY_MISSING",
   )

4. for rule in enrich.lookup:
   operations.append(_build_lookup_operation(rule, engine, providers))

5. secrets_spec = enrich_spec.enrich.secrets or SecretsSpec()
   for rule in enrich.generate:
       target = rule.target
       if target in secrets_spec.fields:
           target = f"secret:{target}"         # ← secret: prefix injection
       operations.append(_build_generate_operation(rule, engine, secrets_spec, providers))

6. return EnricherSpec(
       operations=tuple(operations),
       key_registry=KeyRegistry(builders={}),
   )
```

### `_build_generate_operation()` — детали компиляции

**Файл:** `connector/domain/transform_dsl/compilers/enrich.py`

Создаёт либо legacy `generator(result, deps)` из цепочки ops, либо compiled generate-поля:
- `base_generator`
- `condition`
- `append_generator`
- `conflict_policy`

Legacy path:

```python
def _build_rule_generator(rule, engine):
    def _generator(result, deps):
        source_values = [read_value_path(result.row, s) for s in sources]
        raw = source_values[0] if len(sources) == 1 else source_values
        eng_result = engine.apply(raw, rule.ops)
        if eng_result.issues:
            raise ValueError(eng_result.issues[0].message)
        return eng_result.value
    return _generator
```

Compiled path использует helper-строители:

```python
def _build_source_ops_generator(block, engine): ...
def _build_source_ops_predicate(block, engine): ...
```

Callable `exists(deps, candidate)` для проверки уникальности:

```python
def _build_exists_checker(exists_ref, providers):
    def _checker(deps, candidate):
        return providers.exists(
            exists_ref.provider.name,
            deps,
            candidate,
            args=exists_ref.provider.args,
        )
    return _checker
```

### `_build_lookup_operation()` — детали компиляции

**Файл:** `connector/domain/transform_dsl/compilers/enrich.py`

Создаёт `_DslLookupProvider` (реализует `CandidateProvider.fetch()`):

```python
def fetch(ctx, result, deps, key_values):
    key = key_values.get(rule.source)      # значение из row по имени поля
    raw_rows = providers.lookup(
        provider.name, deps, key, args=provider.args
    )
    for row in raw_rows:
        value = read_value_path(row, rule.value_path)
        candidates.append(
            CandidateValue(field=target, value=value, source=provider.name)
        )
    return candidates
```

### Merge-приоритет `load_enrich_build_options_for_dataset`

```
defaults (EnrichDslBuildOptions())
    │
    ├── registry.build_options.base.*
    │
    ├── registry.build_options.stages.enrich.*
    │
    └── datasets[dataset].build_options.enrich.*
            (перезаписывает всё предыдущее)
```

**Пример в `registry.yml`:**

```yaml
build_options:
  base:
    fail_on_unknown_ops: true
  stages:
    enrich:
      require_match_key: false

datasets:
  employees:
    enrich: employees.enrich.yaml
    build_options:
      enrich:
        require_match_key: true   # ← перекрывает global
```

---

## 🔄 Взаимодействие с другими слоями

### Загрузчики DSL

`EnricherEngine.from_dataset()` вызывает все загрузчики:

```python
spec = load_enrich_spec_for_dataset(dataset)           # EnrichSpec
sink_spec = load_sink_spec_for_dataset(dataset)        # SinkSpec
dsl_options = load_enrich_build_options_for_dataset(dataset)  # EnrichDslBuildOptions
```

### registry.yml — центральный реестр

```yaml
datasets:
  employees:
    source:    employees/source_2/source.yaml
    mapping:   employees/source_2/mapping.yaml
    normalize: employees.normalize.yaml
    enrich:    employees.enrich.yaml      # ← DSL-файл enrich-стадии
    sink:      employees.sink.yaml
```

### SinkSpec → EnricherCore

`SinkSpec` используется в enrich как:
- Справочник допустимых полей при `require_targets_exist_in_sink_spec`
- Источник типов для sink-валидации (если добавлена в core)

### secrets → delivery

`_dataset_requires_vault(dataset_spec)` в `connector/delivery/commands/enrich.py`
проверяет `enrich.secrets.fields` и `target.startswith("secret:")` — если есть,
vault инициализируется для команды.

---

## 🔌 Контракты и границы

**DSL-пакет** (`connector/domain/transform_dsl/`) содержит только:
- Pydantic-модели (specs)
- Компилятор (`EnricherDsl`)
- Loader-функции с template expansion
- Build options

**Запрещённые импорты в DSL-слое:**
- `connector/infra/` — никакой инфраструктуры
- `connector/delivery/` — никакой доставки
- `connector/domain/transform/enrich/` — нет зависимости от core (только наоборот)

**EnricherEngine использует DSL:**

```python
# connector/domain/transform/enrich/enricher_engine.py
from connector.domain.transform_dsl import (
    load_enrich_build_options_for_dataset,
    load_enrich_spec_for_dataset,
)
from connector.domain.transform_dsl.compilers.enrich import EnricherDsl
```

**Правила изоляции:**

| ❌ Нарушение | ✅ Правильно |
|-------------|-------------|
| Импортировать `EnricherCore` в `specs/enrich.py` | DSL-слой не знает о core |
| Обращаться к БД внутри `_expand_enrich_templates` | Pre-processing только над raw dict |
| Хранить runtime-состояние в `EnrichSpec` | `EnrichSpec` — frozen Pydantic-модель |
| Добавить бизнес-логику в `ProviderRef` | `ProviderRef` — только декларация, логика в `ProviderGateway` |

---

## 🛠️ HOW-TO

### Добавить generate-правило

1. Открыть `datasets/employees.enrich.yaml`
2. Добавить в секцию `generate`:

```yaml
generate:
  - name: external_ref
    target: external_ref
    source: external_ref
    ops:
      - op: trim
      - op: default_prefixed_uuid
        args:
          prefix: "EXT-"
    merge: fill_only_if_empty
    on_error: warn
```

3. Убедиться что `external_ref` описан в `employees.sink.yaml`
4. Проверить тесты: `pytest tests/ -k employees`

---

### Добавить lookup через кэш

```yaml
lookup:
  - name: org_data
    target: org_display_name
    source: organization_id
    provider:
      name: cache.by_field
      args:
        dataset: organizations
        field: _id
        include_deleted: false
    value_path: display_name
    on_error: warn
    merge: fill_only_if_empty
```

---

### Добавить lookup через справочник

```yaml
lookup:
  - name: department_full_name
    target: department_full_name
    source: department_code
    provider:
      name: dictionary.by_key
      args:
        dict_name: departments
        fields: [name, description]
        limit: 1
    value_path: name
    on_error: warn
    merge: fill_only_if_empty
```

---

### Добавить поле в секреты (vault)

1. Добавить в секцию `secrets.fields`:

```yaml
secrets:
  fields: [password, api_token]   # ← новое поле
```

2. Добавить generate-правило:

```yaml
generate:
  - name: api_token
    target: api_token              # ← compile: "secret:api_token"
    source: api_token
    ops:
      - op: trim
      - op: default_prefixed_uuid
        args:
          prefix: "tok-"
    merge: fill_only_if_empty
    on_error: warn
```

3. Vault автоматически включится при наличии secret-полей (`_dataset_requires_vault()`)

---

### Использовать template для нескольких однотипных lookup

```yaml
enrich:
  lookup_templates:
    from_cache_by_id:
      provider:
        name: cache.by_field
        args:
          include_deleted: false
          mode: exact
      on_error: warn
      merge: fill_only_if_empty

  lookup:
    - name: org_name
      target: org_name
      source: organization_id
      template: from_cache_by_id
      provider:
        name: cache.by_field
        args:
          dataset: organizations
          field: _id
      value_path: display_name

    - name: dept_name
      target: dept_name
      source: department_id
      template: from_cache_by_id
      provider:
        name: cache.by_field
        args:
          dataset: departments
          field: _id
      value_path: name
```

---

## 💡 Типичные сценарии

### Сценарий 1: Первый запуск — target_id не задан

```
Вход: row["target_id"] = None

generate.target_id:
  source = None (из row)
  ops: trim(None) → None, default_uuid(None) → "f47ac10b-..."
  candidate = "f47ac10b-..."
  exists(deps, "f47ac10b-..."):
    → cache.exists_by_field(dataset=employees, field=_id) → None
  → candidate принят (нет конфликта)

Выход: row["target_id"] = "f47ac10b-..."
```

### Сценарий 2: Повторный запуск — target_id уже в кэше (та же запись)

```
Вход: row["target_id"] = "existing-uuid"

generate.target_id:
  ops: trim("existing-uuid") → "existing-uuid"
  candidate = "existing-uuid"
  exists → {"_id": "existing-uuid", "match_key": "Doe|John|..."}
  allow_if → equals_path(result.match_key, existing["match_key"])
    → "Doe|John|..." == "Doe|John|..." → True
  → candidate принят (та же запись)

Выход: row["target_id"] = "existing-uuid"
```

### Сценарий 3: Конфликт usr_org_tab_num (другая запись)

```
generate.usr_org_tab_num (attempt 1):
  candidate = "TAB-a1b2c3d4"
  exists → {"usr_org_tab_num": "TAB-a1b2c3d4", "match_key": "Smith|Bob|..."}
  allow_if: result.match_key="Doe|John|..." != existing.match_key="Smith|Bob|..."
  → reject, attempts += 1

generate.usr_org_tab_num (attempt 2):
  candidate = "TAB-e5f6g7h8"  (новый UUID)
  exists → None
  → candidate принят

Выход: row["usr_org_tab_num"] = "TAB-e5f6g7h8"
```

### Сценарий 4: Пароль уходит в vault

```
generate.password:
  target = "secret:password"  (compile time)
  ops: trim → "trimmed_pass"
  candidate.value = "trimmed_pass"

_set_field_value("secret:password", "trimmed_pass"):
  → builder.secret_candidates["password"] = "trimmed_pass"
  (НЕ в row!)

_store_secrets():
  secret_store.put_many(
      dataset="employees",
      match_key="Doe|John|...",
      secrets={"password": "trimmed_pass"},
  )
  → row["password"] = None
  → meta["secret_fields"] = ["password"]
```

### Сценарий 5: lookup пустой (warn)

```
lookup.org_name:
  source = row["organization_id"] = "77"
  cache.by_field(dataset=organizations, field=_id, value="77") → []
  strictness.on_no_candidates = WARNED (on_error: warn)
  → warnings += DiagnosticItem(code="ENRICH_NO_CANDIDATES", stage=ENRICH)
  → row["org_name"] не изменяется
```

---

## 📌 Важные детали

| Деталь | Описание |
|--------|----------|
| match_key всегда первая | Компилируется первой, `run_when_errors=ALWAYS` — выполняется даже при ошибках |
| Порядок: lookup → generate | Сначала lookup, затем generate — generate может опираться на cache-backed значения, полученные lookup-правилами |
| `secret:` prefix — compile-time | Присваивается при компиляции, не при runtime — менять только через `secrets.fields` в YAML |
| `exists` только для generate | `lookup`-правила не поддерживают `exists` |
| `max_attempts` дефолт | Если не задан — компилятор ставит дефолт из `EnrichmentOperation` = 3 |
| template vs preset | `lookup_templates` и `lookup_presets` — синонимы; `template` и `preset` в правиле тоже синонимы |
| ops в lookup vs generate | В lookup `ops` применяются к ключу поиска; в generate — к source-значению для генерации нового |
| `fail_on_unknown_ops` | Проверяет ops в правилах, `build/when/then` и op в `allow_if` |

---

## 🧪 Тестовое покрытие

| Файл | Что тестирует |
|------|--------------|
| `tests/unit/transform/test_enrich_dsl.py` | Template expansion, allow_if, value_path, provider contract |
| `tests/unit/transform/test_enricher.py` | EnricherCore алгоритм, secret write, conflict resolution |
| `tests/integration/transform/test_dsl_build_options.py` | Merge build options для enrich |
| `tests/integration/secrets/test_enrich_vault_write_service.py` | Vault write с шифрованием |
| `tests/e2e/pipelines/test_enrich_pipeline.py` | Полный pipeline с CLI |

---

## ❓ FAQ

**Зачем `name` обязателен в `EnrichRule`?**

Имя используется в `enrich_events` (audit log в meta) и диагностике ошибок.
Без имени нельзя отследить какая именно операция дала ошибку при многих правилах.

**Можно ли использовать lookup-правило без `provider`?**

Нет — `_build_lookup_operation()` требует `provider`. Для generate без провайдера используйте
`generate` с `ops` (без `exists` и `provider`).

**Что если `value_path` указывает на несуществующий ключ?**

`read_value_path(row, "nonexistent")` вернёт `None`. Если провайдер нашёл строки,
но `value_path` пуст — кандидат с `value=None`, что при sink-валидации может дать ошибку.

**Как настроить поведение при ambiguous candidates?**

`on_ambiguous` в `StrictnessPolicy` (дефолт: `NEEDS_RESOLVE` — warning + `ResolveHint` в meta).
Для автоматического выбора по приоритету — задайте разные `priority` кандидатам через `CandidateProvider`.

**Могут ли generate и lookup использовать одно поле target?**

Да, merge-политика регулирует порядок: если generate уже записал, lookup с `fill_only_if_empty`
не перезапишет. `_FieldMutationTracker` отслеживает кто уже записал в поле.

**Почему `allow_if` получает `existing` — raw dict, а не `TransformResult`?**

`allow_if(result, existing)` — сравнивает текущую запись (`result`) с найденной в кэше (`existing`).
`existing` — raw dict из кэша. `equals_path` поддерживает dotted path для обоих:
`result.match_key` и `existing["match_key"]`.

---

## 🔗 Связанные документы

| Документ | Описание |
|----------|---------|
| [enrich-core.md](enrich-core.md) | Core-логика: EnricherCore, CandidateValue, ConflictResolver, secrets flow |
| [enrich-infra.md](enrich-infra.md) | Порты, ProviderGateway, StageExecutionContext, DI-wiring |
| [normalizer-dsl.md](../normalizer/normalizer-dsl.md) | DSL предыдущей стадии (normalize) |
| [docs/dev/layers/dsl/dsl-engine.md](../dsl/dsl-engine.md) | TransformationEngine, операции, OperationRegistry |
| [docs/dev/layers/vault/vault-core.md](../vault/vault-core.md) | Vault pipeline: enrich → plan → apply |
| `datasets/employees.enrich.yaml` | Эталонный пример enrich-спецификации |
| `datasets/registry.yml` | Центральный реестр датасетов |

---

## 📝 История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-03-01 | Создан документ — DSL-спецификации enrich-слоя | xORex-LC |
| 2026-05-05 | Обновлены примеры registry wiring под текущий `source_2` layout employees dataset | xORex-LC |
| 2026-05-06 | Документ синхронизирован с новым generate-контрактом: добавлены `build/when/then/on_conflict`, обновлён порядок compile/runtime (`lookup → generate`) и приведены примеры `source_2` enrich-правил | xORex-LC |
