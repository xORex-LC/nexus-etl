# TRANSFORM-DEC-005: DatasetSpec — двухфазная эволюция к generic accessor

> **Статус**: Принято (Phase 2 реализуется в [TRANSFORM-DEC-009](./TRANSFORM-DEC-009-declarative-dataset-spec-yaml-driven-plugins.md))
> **Дата принятия**: 2026-02-22
> **Решает проблему**: [TRANSFORM-PROBLEM-005](./TRANSFORM-PROBLEM-005-dataset-spec-ocp-violation.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

`DatasetSpec` Protocol объявляет типизированные методы построения DSL-спецификаций по одному на каждую стадию (`build_map_spec()`, `build_enrich_spec()`, ...). Добавление новой стадии требует изменения протокола и его реализации — нарушение OCP ([TRANSFORM-PROBLEM-005](./TRANSFORM-PROBLEM-005-dataset-spec-ocp-violation.md)).

Осложняющий фактор: единственная реализация `DatasetSpec` сейчас — `EmployeesSpec`, хардкодированная под один датасет. Планируется её замена на generic YAML-driven реализацию. При generic YAML-impl typed методы (`build_map_spec()` и т.д.) теряют смысл — YAML-impl читает конфигурацию по ключу, а не через предопределённые методы протокола.

---

## 🎯 Решение

**Двухфазная эволюция**:

- **Phase 1 (DEC-004 scope, пока жив `EmployeesSpec`)**: Сохранить typed `build_*_spec()` методы. Осознанный компромисс — DSL coupling ограничен периодом жизни `EmployeesSpec`.
- **Phase 2 (когда `EmployeesSpec` → generic YAML-driven impl)**: Заменить все `build_*_spec()` на единственный generic accessor `build_spec_for(stage_type: str) → object`. Это закроет OCP полностью и будет естественным fit для YAML-driven реализации.

---

## 🏗️ Архитектурное решение

### Phase 1: typed `build_*_spec()` (текущее состояние после DEC-004)

```python
class DatasetSpec(Protocol):
    """DSL-конфигуратор датасета. Phase 1: типизированные per-stage методы."""

    def build_map_spec(self) -> MappingSpec: ...
    def build_normalize_spec(self) -> NormalizeSpec: ...
    def build_enrich_spec(self) -> EnrichSpec: ...
    def build_match_spec(self) -> MatchSpec: ...
    def build_resolve_spec(self) -> ResolveSpec: ...
    def build_sink_spec(self) -> SinkSpec: ...
    def build_record_source(self) -> Iterable[SourceRecord]: ...
```

`PipelineContainer` обращается к методам напрямую:

```python
map_stage = providers.Factory(
    lambda f, spec, ctx, opts: f.create("map", spec.build_map_spec(), ctx, options=opts),
    ...
)
```

### Phase 2: generic `build_spec_for()` (целевое состояние)

```python
class DatasetSpec(Protocol):
    """DSL-конфигуратор датасета. Phase 2: generic accessor."""

    def build_spec_for(self, stage_type: str) -> object:
        """
        Вернуть DSL-спецификацию для стадии с указанным типом.

        Raises:
            UnsupportedStageError: если датасет не поддерживает данный тип стадии.
        """
        ...

    def build_sink_spec(self) -> SinkSpec: ...
    def build_record_source(self) -> Iterable[SourceRecord]: ...
```

`PipelineContainer` использует generic accessor:

```python
map_stage = providers.Factory(
    lambda f, spec, ctx, opts: f.create("map", spec.build_spec_for("map"), ctx, options=opts),
    ...
)
```

Добавление новой стадии `DeduplicateStage`:
1. Создать `DeduplicateSpec` dataclass
2. Добавить `StageDescriptor` в `_build_stage_factory()`
3. Добавить provider в `PipelineContainer`
4. **`DatasetSpec` не меняется** — generic impl читает конфиг по ключу `"dedup"`

### Инвариант для `build_spec_for()`

```python
def build_spec_for(self, stage_type: str) -> object:
    ...
```

- Возвращает `object` (тип-erased). Тип-safety на стороне `StageDescriptor.engine_factory` — factory знает ожидаемый тип spec для своего `stage_type`.
- Бросает `UnsupportedStageError` (не `KeyError`!) если датасет не поддерживает стадию.
- Generic accessor сохраняет единый stage-key контракт; текущая YAML-реализация может загружать stage-конфиг on demand.

### YAML-driven реализация (целевое состояние)

```python
class YamlDatasetSpec:
    """Generic YAML-driven реализация DatasetSpec. Заменяет EmployeesSpec."""

    def __init__(self, config: DatasetConfig) -> None:
        self._config = config

    def build_spec_for(self, stage_type: str) -> object:
        stage_config = self._config.stages.get(stage_type)
        if stage_config is None:
            raise UnsupportedStageError(stage_type, dataset=self._config.name)
        return _build_spec_by_type(stage_type, stage_config)

    def build_sink_spec(self) -> SinkSpec:
        return SinkSpec.from_config(self._config.sink)

    def build_record_source(self) -> Iterable[SourceRecord]:
        source_path = resolve_source_location(self._config.source)
        return CsvRecordSource(source_path, self._config.source.has_header)
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **Phase 1**: Нулевые затраты на внедрение. Typed методы поддерживаемы, пока `EmployeesSpec` существует
- ✅ **Bounded commitment**: компромисс явно ограничен жизненным циклом `EmployeesSpec` — не "технический долг навсегда"
- ✅ **Phase 2**: Полностью закрывает OCP. `DatasetSpec` больше не растёт с числом стадий
- ✅ **Natural fit**: YAML-driven реализация читает конфиг по ключу — `build_spec_for("map")` это именно то, что она делает
- ✅ **Alignment со StageFactory**: Registry Pattern в `StageFactory` уже использует `stage_type: str` как ключ — `build_spec_for(stage_type)` симметричен

**Недостатки (компромиссы)**:
- ⚠️ **Phase 2**: `build_spec_for()` возвращает `object` — теряется статическая типизация на уровне протокола. Но: `StageDescriptor.engine_factory` знает ожидаемый тип spec для своего stage_type, поэтому type-safety сохраняется на уровне factory, а не protocol
- ⚠️ **Phase 2**: Нет compile-time проверки, что датасет реализует нужный `stage_type`. Ошибка обнаруживается при wiring (runtime: `UnsupportedStageError`). Это приемлемо — `PipelineContainer` собирается при старте команды, не в глубине бизнес-логики

**Альтернативы, которые отклонили**:
- ❌ **Только Phase 2 сразу (без Phase 1)**: Пока `EmployeesSpec` существует — typed методы проще и безопаснее. Преждевременная миграция добавляет scope рефактора без выгоды
- ❌ **Sub-protocols per stage (Вариант C из PROBLEM-005)**: Взрывной рост числа протоколов. `PipelineContainer` становится зависимым от N мелких протоколов. Высокий overhead для малой выгоды
- ❌ **Никакой эволюции**: При замене `EmployeesSpec` на YAML-impl typed методы не подходят по природе — migration всё равно неизбежна

---

## 🛠️ Реализация

### Phase 1 (текущее состояние, зафиксировано в DEC-004)

Изменений не требуется. `DatasetSpec` с typed `build_*_spec()` методами — это Phase 1.

### Phase 2 (выполнять при замене `EmployeesSpec`)

| Файл | Изменение |
|------|-----------|
| `connector/datasets/spec.py` | Заменить все `build_*_spec()` на `build_spec_for(stage_type: str) → object` + добавить `UnsupportedStageError` |
| `connector/datasets/employees/spec.py` | Удалить (заменяется на `YamlDatasetSpec`) |
| `connector/datasets/yaml_spec.py` | Создать `YamlDatasetSpec` с `build_spec_for()` |
| `connector/delivery/cli/containers.py` | Обновить `PipelineContainer`: все `spec.build_*_spec()` → `spec.build_spec_for("...")` |
| Тесты | Обновить тесты `DatasetSpec` + добавить `test_yaml_dataset_spec_unsupported_stage()` |

### Инварианты Phase 2

1. `build_spec_for(stage_type)` сохраняет generic stage-key контракт, даже если YAML-реализация загружает stage-конфиг on demand
2. `UnsupportedStageError` (не `KeyError`) — чёткое сообщение об ошибке для unsupported stage
3. `build_record_source()` остаётся dataset-level accessor; `source.has_header` читается из source DSL, а не из CLI override

---

## 🧪 Валидация решения

**Phase 1 (текущее состояние)**:
- ✅ Все тесты из DEC-004 проходят с typed методами

**Phase 2 (при реализации)**:
- ✅ `test_yaml_spec_build_spec_for_known_stage()` — возвращает правильный тип spec
- ✅ `test_yaml_spec_build_spec_for_unknown_stage()` — бросает `UnsupportedStageError`
- ✅ `test_pipeline_container_uses_generic_accessor()` — `PipelineContainer` собирается через `build_spec_for()`
- ✅ `test_add_new_stage_no_datasetsspec_change()` — добавление stage не меняет `DatasetSpec`

**Метрика успеха Phase 2**:
- Количество файлов, затрагиваемых при добавлении новой стадии: **≤ 3** (stage class + StageDescriptor registration + container provider). `DatasetSpec` не меняется.

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Phase 2 возвращает `object` — IDE не подсказывает тип spec для конкретного stage_type. Документировать ожидаемые типы в `StageDescriptor.engine_factory` docstrings
- `UnsupportedStageError` обнаруживается в runtime (при wiring), не в compile time

**Риски**:
- ⚠️ Phase 2 может быть пропущена при замене `EmployeesSpec`, если задача не будет явно запланирована → Митигация: зафиксировать как обязательный шаг в задаче замены `EmployeesSpec`

---

## 🔄 Влияние на другие компоненты

| Компонент | Phase 1 | Phase 2 |
|-----------|---------|---------|
| `DatasetSpec` | Без изменений (typed методы) | Typed методы → `build_spec_for()` |
| `EmployeesSpec` | Без изменений | Удаляется (заменяется `YamlDatasetSpec`) |
| `PipelineContainer` | Без изменений | `spec.build_map_spec()` → `spec.build_spec_for("map")` |
| `StageFactory` / `StageDescriptor` | Без изменений | Без изменений |
| Тесты `DatasetSpec` | Без изменений | Обновить под новый API |

---

## 🔗 Связанные документы

- [TRANSFORM-PROBLEM-005](./TRANSFORM-PROBLEM-005-dataset-spec-ocp-violation.md) — решаемая проблема
- [TRANSFORM-DEC-004](./TRANSFORM-DEC-004-modular-pipeline-scoped-execution-context.md) — контекст: фиксирует Phase 1 компромисс
- `connector/datasets/spec.py` — `DatasetSpec` протокол (Phase 1)
- `connector/datasets/employees/spec.py` — `EmployeesSpec` (будет заменён в Phase 2)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-22 | Решение предложено при ревью DEC-004 |
| 2026-02-22 | Принято: двухфазная эволюция. Phase 1 закреплена в DEC-004 как known limitation |
