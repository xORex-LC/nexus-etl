# CONFIG-DEC-001: Модульный Settings и slice-based wiring

> **Статус**: Принято / Реализовано
> **Дата принятия**: 2026-02-12
> **Решает проблему**: [CONFIG-PROBLEM-001](./CONFIG-PROBLEM-001-settings-layer-complexity.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

Конфигурационный слой был перегружен: один плоский `Settings` использовался во множестве точек и протекал в команды/use-cases целиком.  
Это приводило к высокой связности и рискам регрессий при добавлении параметров (см. [CONFIG-PROBLEM-001](./CONFIG-PROBLEM-001-settings-layer-complexity.md)).

Ключевая проблема: отсутствовали жёсткие архитектурные границы для передачи настроек по слоям.

---

## 🎯 Решение

**Ввести модульную модель настроек (`AppSettings`) и slice-based wiring как канонический путь конфигурации.**

### Архитектурные компоненты:

1. **`AppSettings` + профильные slices**
   - `ApiSettings`
   - `PathsSettings`
   - `ObservabilitySettings`
   - `DatasetSettings`
   - `ExecutionSettings`
   - `RefreshSettings`
   - `MatchingRuntimeSettings`
   - `PendingSettings`

2. **Канонический загрузчик**
   - `load_app_settings(config_path, cli_overrides)` как единственная точка входа в production path.

3. **Граница composition root**
   - полный `AppSettings` допустим только в `delivery/cli/app.py`,
   - далее в команды и use-cases передаются только целевые slices.

4. **Типизированный error-contract**
   - `SettingsLoadError` и специализированные наследники:
     `SettingsSourceError`, `SettingsParseError`, `SettingsValidationError`, `SettingsConflictError`.

5. **Архитектурные guardrails**
   - тесты на границы импортов и на недопустимое протекание полного settings-объекта.

---

## 🏗️ Архитектурное решение

### Новые/ключевые компоненты

**Файл**: `connector/config/app_settings.py`

```python
@dataclass(frozen=True)
class AppSettings:
    api: ApiSettings
    paths: PathsSettings
    observability: ObservabilitySettings
    dataset: DatasetSettings
    execution: ExecutionSettings
    refresh: RefreshSettings
    matching_runtime: MatchingRuntimeSettings
    pending: PendingSettings


def load_app_settings(config_path: str | None, cli_overrides: dict[str, Any]) -> LoadedAppSettings:
    loaded = load_settings_model(config_path=config_path, cli_overrides=cli_overrides)
    ...
    return LoadedAppSettings(...)
```

### Изменения в существующих компонентах

**Файл**: `connector/delivery/cli/app.py`
- точка композиции переведена на `load_app_settings(...)`;
- команды получают только нужные slices, а не полный `Settings`.

### Поток данных

```
config.yml + ENV + CLI
        ↓
load_settings_model(...)   # merge + parse + validate
        ↓
load_app_settings(...)     # projection в AppSettings slices
        ↓
composition root (CLI)
        ↓
commands/use-cases получают только нужные slices
```

---

## ✅ Почему это решение?

### Преимущества:

- ✅ Чёткие архитектурные границы по слоям.
- ✅ Проще добавлять новые параметры без каскада правок.
- ✅ Повышена читаемость и трассируемость источников значений.
- ✅ Типизированные ошибки загрузки конфигурации.
- ✅ Guardrail-тесты предотвращают возврат к legacy-пути.

### Недостатки (компромиссы):

- ⚠️ Увеличилось число DTO-классов (slices).
  - **Приемлемо, потому что**: это цена за явные границы и масштабируемость.
- ⚠️ Появился mapping между плоским `Settings` и slice-моделью.
  - **Приемлемо, потому что**: mapping централизован в одном месте (`app_settings.py`).

### Отклонённые альтернативы:

- ❌ Оставить плоский `Settings` и точечные рефакторинги:
  - не решает проблему границ и высокую связность.
- ❌ Сразу удалить `Settings` и перейти только на slices:
  - слишком высокий миграционный риск; выбран контролируемый путь.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Описание изменения |
|------|-------------------|
| `connector/config/app_settings.py` | Создана модульная модель `AppSettings` + slices |
| `connector/config/config.py` | Сохранён плоский loader как низкоуровневый merge/parse слой |
| `connector/delivery/cli/app.py` | Production wiring переведён на `load_app_settings(...)` |
| `tests/architecture/config/test_settings_boundaries.py` | Guardrails на архитектурные границы |
| `tests/integration/config/test_settings_runtime_boundary.py` | Проверка runtime границ конфигурации |
| `tests/unit/config/test_runtime_settings_boundary.py` | Unit-проверки slice-передачи |

### Ключевые инварианты

1. **Полный `AppSettings` не должен протекать в доменные/usecase слои.**
2. **Commands/use-cases получают только релевантные slices.**
3. **`load_app_settings(...)` — канонический production entrypoint.**
4. **Ошибки загрузки конфигурации должны быть типизированы.**

---

## 🧪 Валидация решения

### Тесты

- ✅ Unit:
  - `tests/unit/config/test_settings_merge.py`
  - `tests/unit/config/test_settings_parsing.py`
  - `tests/unit/config/test_settings_validation.py`
  - `tests/unit/config/test_runtime_settings_boundary.py`
- ✅ Integration:
  - `tests/integration/config/test_config_priority.py`
  - `tests/integration/config/test_settings_runtime_boundary.py`
  - `tests/integration/config/test_settings_errors.py`
- ✅ Architecture:
  - `tests/architecture/config/test_settings_boundaries.py`

### Критерии успеха

1. Production path использует `load_app_settings(...)`.
2. Нет зависимости usecase-команд от полного settings-контракта.
3. CI ловит нарушения границ на архитектурном уровне.

---

## ⚠️ Риски и ограничения

### Известные ограничения:

1. Плоский `Settings` пока сохраняется как базовый слой merge/parse (транзитный элемент архитектуры).
2. При добавлении новых полей нужен явный апдейт `_SLICE_FIELD_MAP`.

### Риски:

- ⚠️ Риск: забыть добавить новое поле в slice mapping.
  - **Митигация**: тесты полноты и boundary guardrails.
- ⚠️ Риск: новые команды начнут принимать полный объект настроек.
  - **Митигация**: архитектурные тесты на импортные и контрактные границы.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| CLI composition root | Прямое | Перевод на `load_app_settings(...)` |
| Delivery commands | Прямое | Приём только нужных slices |
| UseCases | Косвенное | Сужение входных конфиг-контрактов |
| Diagnostics layer | Косвенное | Трансляция типизированных config-ошибок |

---

## 📚 Документация

**Обновлена документация**:
- ✅ [CONFIG-PROBLEM-001](./CONFIG-PROBLEM-001-settings-layer-complexity.md)
- ✅ `docs/adr/INDEX.md` (раздел Config)
- ✅ `docs/Project_Structure.md` (слой config и runtime wiring)

---

## 🔗 Связанные документы

- [CONFIG-PROBLEM-001](./CONFIG-PROBLEM-001-settings-layer-complexity.md)
- `connector/config/app_settings.py`
- `connector/delivery/cli/app.py`

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-12 | Решение предложено |
| 2026-02-12 | Решение принято после обсуждения |
| 2026-02-12 | Реализовано и переведено в production path |
