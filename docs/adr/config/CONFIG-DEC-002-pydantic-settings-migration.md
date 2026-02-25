# CONFIG-DEC-002: Миграция Settings на Pydantic BaseSettings

> **Статус**: Принято (реализация отложена)
> **Дата принятия**: 2026-02-19
> **Решает проблему**: [CONFIG-PROBLEM-002](./CONFIG-PROBLEM-002-manual-settings-validation.md)
> **Участники решения**: @xorex-LC

---

## 📋 Контекст

Текущий `Settings` — замороженный dataclass с ручной валидацией в `_validate_settings()`.
Pydantic уже используется в проекте. С добавлением `SqliteSettings` и других новых слайсов
стоимость сопровождения ручной валидации становится неоправданной
([CONFIG-PROBLEM-002](./CONFIG-PROBLEM-002-manual-settings-validation.md)).

---

## 🎯 Решение

Перевести `Settings` на `pydantic-settings` (`BaseSettings`), слайсы `AppSettings` — на
`pydantic` (`BaseModel`). `_validate_settings()` удаляется; валидация становится декларативной
через типы (`Literal`, `Field`). Трёхуровневый merge (CLI > ENV > config-file > defaults)
реализуется через кастомный `settings_customise_sources()`.

---

## 🏗️ Архитектурное решение

### Плоская модель Settings

```python
# connector/config/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Literal

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ANKEY_",
        frozen=True,
        extra="ignore",
    )

    # Пример: было str + ручная проверка, стало Literal
    sqlite_journal_mode: Literal["WAL", "DELETE", "MEMORY", "TRUNCATE", "PERSIST", "OFF"] = "WAL"
    sqlite_synchronous: Literal["OFF", "NORMAL", "FULL", "EXTRA"] = "NORMAL"

    # Пример: было int + ручной range, стало Field с ge/le
    sqlite_busy_timeout_ms: int = Field(default=5000, ge=1000, le=30000)
    vault_canary_percent: int = Field(default=100, ge=0, le=100)

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):
        # Приоритет: CLI-overrides > env vars > config-file > defaults
        # CLI-overrides передаются как InitSettingsSource
        ...
```

### Слайсы AppSettings

```python
# connector/config/app_settings.py
from pydantic import BaseModel, ConfigDict

class SqliteSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    journal_mode: Literal["WAL", "DELETE", "MEMORY", "TRUNCATE", "PERSIST", "OFF"] = "WAL"
    synchronous: Literal["OFF", "NORMAL", "FULL", "EXTRA"] = "NORMAL"
    busy_timeout_ms: int = Field(default=5000, ge=1000, le=30000)
    wal_autocheckpoint: int = Field(default=1000, ge=0)
    vault_transaction_mode: Literal["deferred", "immediate", "exclusive"] = "immediate"
    vault_busy_timeout_ms: int | None = Field(default=None, ge=1000, le=30000)
    vault_journal_mode: Literal["WAL", "DELETE", "MEMORY", "TRUNCATE", "PERSIST", "OFF"] | None = None
    vault_schema_retry_count: int = Field(default=2, ge=0, le=10)
    vault_db_path: str | None = None
    cache_transaction_mode: Literal["deferred", "immediate", "exclusive"] = "deferred"
    cache_busy_timeout_ms: int | None = Field(default=None, ge=1000, le=30000)
    cache_journal_mode: Literal["WAL", "DELETE", "MEMORY", "TRUNCATE", "PERSIST", "OFF"] | None = None
```

### Трёхуровневый merge (CLI > ENV > file > defaults)

```python
class Settings(BaseSettings):
    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        return (
            init_settings,     # CLI overrides (переданы при создании Settings(**cli_overrides))
            env_settings,      # ENV vars с префиксом ANKEY_
            YamlConfigSource(settings_cls),  # config.yaml
            # defaults — автоматически из Field(default=...)
        )
```

### Что удаляется

- `_validate_settings()` — вся ручная валидация: enum-проверки, range-проверки, consistency-check
- Ручная коэрция типов (`int(os.getenv(...))`, `bool(os.getenv(...))`) — Pydantic делает автоматически
- Отдельный `_SLICE_FIELD_MAP` — слайсы строятся напрямую из `Settings.model_dump()` или через `model_validate`

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ **Декларативность**: `Literal[...]` вместо `if val not in {...}`, `Field(ge=..., le=...)` вместо `if not (lo <= x <= hi)`
- ✅ **Автоматическая коэрция**: `"5000"` из ENV → `int 5000` без ручного кода
- ✅ **Единообразие**: Pydantic уже в проекте; Settings перестаёт быть исключением
- ✅ **IDE-поддержка**: `Literal` даёт autocomplete для enum-полей
- ✅ **Ошибки при старте**: Pydantic валидирует при инициализации модели, не в середине выполнения
- ✅ **Документируемость**: `Settings.model_json_schema()` → автогенерация схемы параметров деплоя

**Недостатки (компромиссы)**:
- ⚠️ Миграция затрагивает весь `config.py` + `app_settings.py` — однократная, но объёмная работа
- ⚠️ Кастомный `settings_customise_sources()` для трёхуровневого merge требует тестирования

**Альтернативы, которые отклонили**:
- ❌ **Частичный рефакторинг**: не решает коэрцию типов, не устраняет ручной код, не унифицирует подход

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `pyproject.toml` / `requirements.txt` | Добавить `pydantic-settings` |
| `connector/config/config.py` | `Settings(BaseSettings)` вместо `@dataclass(frozen=True)` + удалить `_validate_settings()` |
| `connector/config/app_settings.py` | Слайсы → `BaseModel` с `ConfigDict(frozen=True)` |
| `connector/config/diagnostics.py` | Обновить error-mapping под Pydantic `ValidationError` |

### Стратегия миграции

Миграция проводится в одном PR, не поэтапно — Settings — центральная модель, частичная
миграция создаёт несогласованность. Порядок:

1. Добавить `pydantic-settings` в зависимости
2. `Settings` → `BaseSettings`; убрать `_validate_settings()`
3. Слайсы `AppSettings` → `BaseModel`
4. Обновить `load_app_settings()` (упрощение или замена)
5. Обновить тесты settings

### Инварианты

1. Поведение `Settings` для существующих параметров не меняется (те же дефолты, тот же приоритет)
2. CLI-overrides имеют наивысший приоритет над ENV и config-файлом
3. Ошибки конфигурации выбрасываются при инициализации `Settings`, не при первом использовании поля

---

## 🧪 Валидация решения

**Тесты**:
- `test_settings_env_override()` — ENV переменная переопределяет default
- `test_settings_cli_override_beats_env()` — CLI override имеет приоритет над ENV
- `test_settings_invalid_journal_mode()` — `ValidationError` при неизвестном значении
- `test_settings_busy_timeout_range()` — `ValidationError` при выходе за диапазон
- `test_sqlite_settings_coercion()` — `"5000"` из ENV → `int 5000`

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `connector/delivery/cli/app.py` | Косвенное | CLI-overrides передаются как `**kwargs` при создании `Settings` |
| `connector/config/diagnostics.py` | Прямое | Маппинг `pydantic.ValidationError` → `ConfigurationError` |
| Все тесты settings | Прямое | Обновить создание `Settings` в тестах |
| DI-контейнер (`containers.py`) | Нет | Получает готовый `AppSettings`, не зависит от реализации |

---

## 🔗 Связанные документы

- [CONFIG-PROBLEM-002](./CONFIG-PROBLEM-002-manual-settings-validation.md) — решаемая проблема
- [CONFIG-DEC-001](./CONFIG-DEC-001-modular-settings-and-slice-wiring.md) — предыдущее решение (slice-архитектура сохраняется)
- [CACHE-DEC-002](../cache/CACHE-DEC-002-unified-sqlite-infra-layer.md) — `SqliteSettings` как первый новый slice (будет на Pydantic)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-19 | Решение принято при проектировании SqliteSettings; реализация отложена |
