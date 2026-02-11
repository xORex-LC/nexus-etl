# Как добавить новую операцию в DSL

> **Практическое руководство** по добавлению новых операций для любого DSL-слоя (mapping, normalize, resolve, cache и т.д.)

## 📋 Общий паттерн

Все DSL в проекте следуют единому паттерну:

```
1. Реализация в Core → 2. Регистрация в DSL → 3. Валидация → 4. Использование в YAML
```

## 🎯 Пошаговая инструкция

### Шаг 1: Реализовать операцию в Core

**Где**: `connector/domain/transform/*/core.py` или `connector/domain/dsl/ops.py`

**Сигнатура**: Все операции DSL имеют одинаковую сигнатуру

```python
def op_my_operation(
    value: Any,           # Входное значение
    **kwargs: Any         # Параметры из YAML
) -> Any:                 # Результат
    """
    Назначение:
        Краткое описание операции.

    Параметры:
        value: Что приходит на вход
        kwargs: Доп. параметры (например, separator, format и т.д.)

    Возвращает:
        Преобразованное значение

    Пример:
        >>> op_my_operation("hello", suffix="!")
        "hello!"
    """
    # Реализация
    pass
```

**Пример**: Операция добавления суффикса

```python
# connector/domain/dsl/ops.py

def op_add_suffix(value: Any, suffix: str = "", **_: Any) -> str | None:
    """
    Назначение:
        Добавить суффикс к строковому значению.

    Параметры:
        value: Исходная строка
        suffix: Суффикс для добавления
    """
    if value is None:
        return None

    text = str(value)
    return f"{text}{suffix}"
```

### Шаг 2: Зарегистрировать в DSL

**Где**: `connector/domain/dsl/registry.py` или соответствующий `*_dsl.py`

```python
# connector/domain/dsl/registry.py

from connector.domain.dsl.ops import op_add_suffix

# Глобальный реестр операций
OPERATION_REGISTRY = {
    "trim": op_trim,
    "lower": op_lower,
    "upper": op_upper,
    "add_suffix": op_add_suffix,  # ← Добавить
    # ...
}
```

**Важно**: Имя в реестре (`"add_suffix"`) — это то, что будет в YAML

### Шаг 3: Добавить валидацию (опционально)

Если операция требует обязательных параметров, добавь валидацию:

```python
# connector/domain/dsl/loader.py или validator.py

def validate_operation(op_name: str, params: dict[str, Any]) -> None:
    """Валидация параметров операции."""

    if op_name == "add_suffix":
        if "suffix" not in params:
            raise ValueError("Operation 'add_suffix' requires parameter 'suffix'")

        if not isinstance(params["suffix"], str):
            raise ValueError("Parameter 'suffix' must be a string")
```

### Шаг 4: Обновить схему (если есть JSON Schema)

```python
# connector/domain/dsl/specs.py

OPERATION_SCHEMAS = {
    "add_suffix": {
        "type": "object",
        "properties": {
            "suffix": {"type": "string"}
        },
        "required": ["suffix"]
    }
}
```

### Шаг 5: Использовать в YAML

```yaml
# datasets/employees/transform/mapping.yaml
mapping:
  fields:
    - source: employee_id
      target: id
      operations:
        - type: add_suffix
          suffix: "@company.com"
```

### Шаг 6: Добавить тесты

```python
# tests/domain/dsl/test_ops.py

def test_op_add_suffix():
    """Тест: добавление суффикса."""
    result = op_add_suffix("user123", suffix="@mail.com")
    assert result == "user123@mail.com"

def test_op_add_suffix_none():
    """Тест: None возвращает None."""
    result = op_add_suffix(None, suffix="@mail.com")
    assert result is None
```

---

## 🔄 Примеры для разных слоёв

### Transform Operations (mapping/normalize/enrich)

```python
# connector/domain/dsl/ops.py

def op_mask_email(value: Any, mask_char: str = "*", **_: Any) -> str | None:
    """Маскировать email: u***@example.com"""
    if not value:
        return None

    email = str(value)
    if "@" not in email:
        return email

    local, domain = email.split("@", 1)
    masked_local = local[0] + mask_char * (len(local) - 1)
    return f"{masked_local}@{domain}"
```

```yaml
# YAML
operations:
  - type: mask_email
    mask_char: "×"
```

### Resolve Operations

```python
# connector/domain/transform/resolver/resolve_core.py

class ResolveCore:
    @staticmethod
    def resolve_by_regex_match(
        values: list[Any],
        pattern: str,
        **kwargs: Any
    ) -> Any:
        """Выбрать значение, соответствующее regex."""
        import re

        regex = re.compile(pattern)
        for value in values:
            if value and regex.match(str(value)):
                return value
        return None
```

```yaml
# YAML
resolve:
  rules:
    - field: employee_id
      strategy: custom
      operation: resolve_by_regex_match
      pattern: "^EMP\\d{6}$"
```

### Cache Operations (если применимо)

```python
# connector/domain/cache_core/policies.py

def cache_policy_time_based(
    dataset: str,
    max_age_hours: int = 24,
    **kwargs: Any
) -> bool:
    """Кэшировать на основе времени."""
    # Логика
    pass
```

---

## 📌 Чек-лист добавления операции

Используй этот чеклист, чтобы ничего не забыть:

- [ ] Реализовал операцию в Core/ops.py
- [ ] Добавил docstring с описанием и примером
- [ ] Зарегистрировал в `OPERATION_REGISTRY`
- [ ] Добавил валидацию параметров (если нужна)
- [ ] Обновил схему (если есть)
- [ ] Написал тесты (минимум 2: happy path + edge case)
- [ ] Проверил, что операция работает в YAML
- [ ] Обновил документацию слоя (добавил в таблицу операций)

---

## ❓ FAQ

### Q: Можно ли переиспользовать существующую операцию?

**A**: Да! Создай алиас:

```python
OPERATION_REGISTRY = {
    "trim": op_trim,
    "strip": op_trim,  # Алиас для trim
}
```

### Q: Как сделать операцию с несколькими параметрами?

**A**: Просто добавь параметры в kwargs:

```python
def op_replace(
    value: Any,
    old: str,
    new: str,
    count: int = -1,
    **_: Any
) -> str | None:
    if value is None:
        return None
    return str(value).replace(old, new, count)
```

```yaml
operations:
  - type: replace
    old: "foo"
    new: "bar"
    count: 1
```

### Q: Что если операция нужна только для одного датасета?

**A**: Создай `custom_ops.py` в директории датасета:

```python
# datasets/employees/transform/custom_ops.py

def op_normalize_employee_id(value: Any, **_: Any) -> str:
    """Специфичная логика для employee_id."""
    # ...
```

Импортируй и зарегистрируй локально:
```python
# datasets/employees/transform/__init__.py
from .custom_ops import op_normalize_employee_id

LOCAL_OPS = {
    "normalize_employee_id": op_normalize_employee_id
}
```

---

## 🔗 Связанные документы

- [Resolve DSL](../layers/resolve-dsl.md) - Resolve операции
- [Transform DSL](../layers/transform-dsl.md) - Transform операции
- [DSL Patterns](./dsl-patterns.md) - Общие паттерны DSL
