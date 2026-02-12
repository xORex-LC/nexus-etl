# CACHE-DEC-001: Топологическая сортировка для порядка refresh зависимых датасетов

> **Статус**: Принято ✅
> **Дата принятия**: 2026-02-11
> **Решает проблему**: [CACHE-PROBLEM-001](./CACHE-PROBLEM-001-circular-refresh-deadlock.md)
> **Участники решения**: @xorex

---

## 📋 Контекст

При refresh кэша датасеты обновлялись в произвольном порядке, что нарушало целостность данных при наличии зависимостей. Датасет B, зависящий от A, мог обновиться раньше A, что приводило к массовым pending links и некорректному FK resolution ([CACHE-PROBLEM-001](./CACHE-PROBLEM-001-circular-refresh-deadlock.md)).

**Ключевая проблема**: Отсутствие гарантий порядка refresh → нарушение data integrity.

---

## 🎯 Решение

**Реализовать автоматическую топологическую сортировку датасетов на основе `dep_map` с использованием алгоритма Кана.**

### Архитектурные компоненты:

1. **`CacheDependencyGraph`** — новый класс для управления графом зависимостей
   - Строится при инициализации из `dep_map`
   - Вычисляет топологический порядок один раз, кэширует результат
   - Выбрасывает `ValueError` при обнаружении циклов (fail-fast)

2. **`_topological_order()` static method** — реализация алгоритма Кана
   - Входные данные: `datasets`, `dep_map`
   - Выход: `tuple[str, ...]` — датасеты в топологическом порядке
   - Сложность: O(V + E) где V = датасеты, E = зависимости

3. **`refresh_order()` public API** — публичный метод для получения порядка
   - Опциональная фильтрация по scope
   - Опциональное расширение зависимостей

---

## 🏗️ Архитектурное решение

### Новые компоненты

**Файл**: `connector/domain/cache_core/cache_dependency_graph.py`

```python
class CacheDependencyGraph:
    """Граф зависимостей между датасетами для определения порядка операций."""

    def __init__(self, dep_map: Mapping[str, Sequence[str]]):
        """
        Args:
            dep_map: Словарь {dataset: [dependencies]}
                     Пример: {"employee_mappings": ["employees"]}

        Raises:
            ValueError: Если граф содержит циклы
        """
        self._dep_map = dep_map
        self._topo = _topological_order(list(dep_map.keys()), dep_map)

    def refresh_order(
        self,
        scope: Sequence[str] | None = None,
        include_dependencies: bool = False
    ) -> list[str]:
        """Получить порядок refresh для датасетов в scope."""
        ...

    @staticmethod
    def _topological_order(
        datasets: Sequence[str],
        dep_map: Mapping[str, Sequence[str]]
    ) -> tuple[str, ...]:
        """Kahn's algorithm для топологической сортировки."""
        ...
```

### Изменения в существующих компонентах

**Файл**: `connector/domain/cache_core/cache_refresh_planner.py`

```python
class CacheRefreshPlanner:
    def __init__(self, dependency_graph: CacheDependencyGraph):
        self._graph = dependency_graph

    def plan(
        self,
        scope: list[str],
        include_dependencies: bool = True
    ) -> CacheRefreshPlan:
        # БЫЛО: datasets = list(scope)
        # СТАЛО: datasets = self._graph.refresh_order(scope, include_dependencies)
        ordered = self._graph.refresh_order(
            scope=scope,
            include_dependencies=include_dependencies
        )
        return CacheRefreshPlan(datasets=tuple(ordered))
```

### Поток данных

```
Configuration (cache.yaml)
    ↓
dep_map: {"employee_mappings": ["employees"]}
    ↓
CacheDependencyGraph.__init__(dep_map)
    ↓
_topological_order(datasets, dep_map)  # Kahn's algorithm
    ↓
cached: self._topo = ("employees", "employee_mappings")
    ↓
refresh_order(scope) → filter by scope → ordered list
    ↓
CacheRefreshPlanner.plan() → CacheRefreshPlan
    ↓
UseCase: for dataset in plan.datasets: refresh(dataset)
```

---

## ✅ Почему это решение?

### Преимущества:

- ✅ **Математическая гарантия корректности**: Топологическая сортировка всегда даёт правильный порядок для DAG
- ✅ **Автоматизация**: Не требует ручного указания порядка — вычисляется из `dep_map`
- ✅ **Fail-fast**: Циклические зависимости выявляются на этапе инициализации, а не в runtime
- ✅ **Эффективность**: O(V+E) — линейная сложность, быстро даже для больших графов
- ✅ **Переиспользование**: `CacheDependencyGraph` может использоваться и для других операций (clear, analyze)
- ✅ **Документированность**: Явное указание зависимостей в конфигурации улучшает понимание системы

### Недостатки (компромиссы):

- ⚠️ **Требует явных зависимостей**: Пользователь должен указать `dependencies` в `cache.yaml`
  - **Приемлемо, потому что**: Это улучшает документированность и делает зависимости explicit
- ⚠️ **Дополнительный класс**: Увеличивает кодовую базу на ~100 строк
  - **Приемлемо, потому что**: Абстракция оправдана — граф переиспользуется, логика изолирована
- ⚠️ **Не поддерживает динамические изменения**: Граф строится один раз при инициализации
  - **Приемлемо, потому что**: Зависимости статичны, меняются только при изменении конфигурации

### Отклонённые альтернативы:

- ❌ **Manual ordering в конфигурации**: Высокий риск ошибок, не масштабируется, дублирование информации
- ❌ **Lazy resolution с retry**: Скрывает root cause, высокий performance overhead, не решает циклы
- ❌ **DFS-based topological sort**: Kahn's algorithm проще для понимания и естественно выявляет циклы

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Описание изменения |
|------|-------------------|
| `cache_dependency_graph.py` | **Создан** новый класс (115 строк) |
| `cache_refresh_planner.py` | **Изменён**: использует `dependency_graph.refresh_order()` вместо `list(scope)` |
| `cache_clear_planner.py` | **Изменён**: переиспользует `dependency_graph` для clear операций |
| `tests/cache_core/test_dependency_graph.py` | **Создан**: тесты на cycles, ordering, edge cases |

### Ключевые методы

- [`CacheDependencyGraph._topological_order()`](../../dev/layers/cache-core.md#метод-_topological_order) — алгоритм Кана (24 строки, O(V+E))
- [`CacheDependencyGraph.refresh_order()`](../../dev/layers/cache-core.md) — публичный API для получения порядка

### Инварианты

1. **Граф без циклов**: `_topological_order()` выбросит `ValueError` если цикл обнаружен
   - **Где**: line 112-113 в `_topological_order()`
   - **Сообщение**: `"Dependency graph for datasets {datasets} contains a cycle"`

2. **Детерминированный порядок**: Для одного и того же графа порядок всегда одинаков
   - **Где**: Алгоритм Кана детерминирован при фиксированном порядке входных данных

3. **Зависимости перед зависимыми**: Датасет A всегда в порядке раньше B, если B зависит от A
   - **Где**: Гарантируется свойствами топологической сортировки

---

## 🧪 Валидация решения

### Тесты

**Unit tests** (`tests/cache_core/test_dependency_graph.py`):

```python
def test_topological_order_linear_chain():
    """Тест: линейная цепь A→B→C"""
    dep_map = {
        "A": [],
        "B": ["A"],
        "C": ["B"]
    }
    graph = CacheDependencyGraph(dep_map)
    assert graph.topological_order() == ("A", "B", "C")

def test_topological_order_detects_cycle():
    """Тест: цикл A→B→A должен выбросить ValueError"""
    dep_map = {
        "A": ["B"],
        "B": ["A"]
    }
    with pytest.raises(ValueError, match="contains a cycle"):
        CacheDependencyGraph(dep_map)

def test_refresh_order_with_scope():
    """Тест: фильтрация по scope"""
    dep_map = {
        "employees": [],
        "employee_mappings": ["employees"],
        "departments": []
    }
    graph = CacheDependencyGraph(dep_map)
    order = graph.refresh_order(scope=["employees", "employee_mappings"])
    assert order == ["employees", "employee_mappings"]
```

**Integration test** (`tests/usecases/test_refresh_cache.py`):

```python
def test_refresh_cache_respects_dependencies(use_case, mock_gateway):
    """Тест: refresh выполняется в правильном порядке"""
    # Setup: employee_mappings зависит от employees
    result = use_case.execute(["employees", "employee_mappings"])

    # Verify: employees обновился раньше employee_mappings
    calls = mock_gateway.refresh.call_args_list
    assert calls[0][0][0] == "employees"
    assert calls[1][0][0] == "employee_mappings"
```

### Проверка в production

**Метрики до внедрения** (baseline):
- Pending links для `employee_mappings`: ~950 из 1000 записей (~95%)
- Время resolve: ~45 секунд (включая 2 прохода)
- Частота ошибок FK resolution: ~5-10% записей

**Метрики после внедрения** (expected):
- Pending links для `employee_mappings`: 0 (все резолвятся сразу)
- Время resolve: ~8 секунд (один проход)
- Частота ошибок FK resolution: 0%

**Как проверить**:
1. Развернуть на staging
2. Запустить `RefreshCacheUseCase` для зависимых датасетов
3. Проверить логи:
   ```
   [INFO] Refreshing cache for datasets: ['employees', 'employee_mappings']
   [INFO] Computed refresh order: ['employees', 'employee_mappings']  # ← Новое
   [INFO] Refresh 'employees' - 1000 records
   [INFO] Refresh 'employee_mappings' - 1000 records
   [INFO] Created 0 pending links  # ← Было 950
   ```

---

## 📐 Диаграммы

**UML диаграммы**:
- [Class Diagram](../../../uml/cache/core/cache_domain_class.png) — структура `CacheDependencyGraph`
- [Activity Diagram](../../../uml/cache/core/cache_activity_refresh.png) — процесс refresh с топологическим порядком

**Пример использования**:

```python
# 1. Конфигурация
dep_map = {
    "employees": [],
    "employee_mappings": ["employees"],
    "employee_projects": ["employees"]
}

# 2. Создание графа
graph = CacheDependencyGraph(dep_map)

# 3. Получение порядка
order = graph.refresh_order(scope=["employees", "employee_mappings"])
# → ["employees", "employee_mappings"]  # Всегда правильный порядок!

# 4. Refresh в правильном порядке
for dataset in order:
    refresh_dataset(dataset)
```

**Визуализация алгоритма**:

```
Пример: employees → employee_mappings

Шаг 1: Инициализация
  indegree = {"employees": 0, "employee_mappings": 1}
  edges = {"employees": ["employee_mappings"]}

Шаг 2: Queue = ["employees"]  # indegree == 0

Шаг 3: Обработка
  current = "employees"
  ordered = ["employees"]
  → process dependent "employee_mappings"
  → indegree["employee_mappings"] = 0
  → add to queue

  current = "employee_mappings"
  ordered = ["employees", "employee_mappings"]

Результат: ("employees", "employee_mappings") ✓
```

---

## ⚠️ Риски и ограничения

### Известные ограничения:

1. **Статический граф**: Не поддерживает динамическое изменение зависимостей в runtime
   - Требуется пересоздание `CacheDependencyGraph` при изменении конфигурации
   - **Приемлемо**: Зависимости меняются редко (только при изменении `cache.yaml`)

2. **Порядок независимых датасетов undefined**:
   - Если A и B независимы, порядок между ними не гарантирован
   - **Приемлемо**: Для независимых датасетов порядок не важен

3. **Требует явных зависимостей**:
   - Пользователь должен указать все зависимости в `cache.yaml`
   - **Приемлемо**: Это явно документирует архитектуру

### Риски:

- ⚠️ **Очень большое количество датасетов (>1000) может замедлить построение графа**
  - **Вероятность**: Низкая (текущий проект ~50 датасетов)
  - **Митигация**: Граф строится один раз при инициализации, ~0.5ms для 50 датасетов, ~50ms для 1000

- ⚠️ **Некорректная конфигурация `dep_map` приведёт к ValueError**
  - **Вероятность**: Средняя (ошибки в конфигурации)
  - **Митигация**:
    - Fail-fast при инициализации (не в runtime)
    - Чёткое сообщение об ошибке с указанием проблемных датасетов
    - Можно добавить валидацию конфигурации при старте приложения

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `CacheRefreshPlanner` | ✅ Прямое | Инициализировать с `CacheDependencyGraph`, использовать `refresh_order()` |
| `CacheClearPlanner` | ✅ Косвенное | Может переиспользовать граф для clear в обратном порядке |
| `RefreshCacheUseCase` | ⚪ Минимальное | Передать `dep_map` при создании планировщика |
| `ResolveCore` | ⚪ Нет | Косвенная выгода: меньше pending links |
| Configuration loader | ⚪ Нет | `dep_map` уже загружается из `cache.yaml` |

---

## 📚 Документация

**Обновлена документация**:
- ✅ [cache-core.md](../../dev/layers/cache-core.md) — добавлена секция про `CacheDependencyGraph`
- ✅ [cache-core.md: метод _topological_order()](../../dev/layers/cache-core.md#метод-_topological_order) — детальное описание алгоритма Кана
- ✅ UML диаграммы обновлены: добавлен `CacheDependencyGraph` в class diagram

**Документация кода**:
- Все публичные методы имеют docstrings с примерами
- Алгоритм Кана прокомментирован inline

---

## 🔗 Связанные документы

- [CACHE-PROBLEM-001](./CACHE-PROBLEM-001-circular-refresh-deadlock.md) — решаемая проблема
- [cache-core.md](../../dev/layers/cache-core.md) — документация Cache Core слоя
- [cache-core.md: Инварианты](../../dev/layers/cache-core.md#инварианты-системы) — инвариант "Граф без циклов"

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-11 | Решение предложено после обнаружения CACHE-PROBLEM-001 |
| 2026-02-11 | Решение принято (единогласно, альтернативы отклонены) |
| 2026-02-11 | Реализовано: `CacheDependencyGraph` с алгоритмом Кана |
| 2026-02-11 | Документация обновлена, UML диаграммы добавлены |
