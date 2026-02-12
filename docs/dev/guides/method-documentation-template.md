# Шаблон документации сложного метода

> **Назначение**: Переиспользуемый шаблон для документирования методов 50+ строк или со сложной логикой

## Когда использовать

Документируйте метод, если выполняется **хотя бы одно** условие:
- ✅ Метод 50+ строк
- ✅ Содержит вложенные циклы или условия
- ✅ Реализует нетривиальный алгоритм (сортировка, поиск, state machine)
- ✅ Имеет сложную логику с несколькими edge cases
- ✅ Часто вызывает вопросы у других разработчиков

## Шаблон

```markdown
### Метод: `ClassName.method_name()`

**Расположение**: `connector/path/to/file.py:LINE_NUMBER`

**Сигнатура**:
```python
def method_name(
    self,
    param1: Type1,
    *,
    param2: Type2,
    param3: Type3 | None = None,
) -> ReturnType:
    """
    Docstring из кода (если есть).
    """
```

**Назначение**:
[1-2 предложения - что делает метод, какую задачу решает]

---

**Алгоритм** (выбрать формат):

*Вариант A: Pseudocode с номерами строк*
```
1. Step Name (lines X-Y)
   - Sub-step description
   - IF condition → action
   - ELSE → alternative action

2. Step Name (lines Y-Z)
   - FOR EACH item IN collection:
       → Process item
   - RETURN result

3. Cleanup (lines Z-W)
   - Finalize resources
```

*Вариант B: ASCII Flow диаграмма* (для более наглядных случаев с ветвлениями)
```
Input
  ↓
[Validation] → {Valid?} ─No→ Error Exit
  ↓ Yes
[Transform]
  ↓
[Decision Point]
  ├─ Case A → [Handle A]
  ├─ Case B → [Handle B] ──→ [Retry Loop] ──┐
  └─ Case C → [Handle C]                     │
                ↓                            │
          [Aggregate Results] ←──────────────┘
                ↓
             Output
```

---

**Временная сложность**:
- **Best case**: O(...) - когда [условие]
- **Average case**: O(...) - типичный сценарий
- **Worst case**: O(...) - когда [условие]

*Если есть зависимость от размера данных, определить переменные*:
- n = количество элементов в коллекции
- k = количество ключей
- m = количество правил

---

**Инварианты**:
1. **Инвариант 1**: [Что никогда не нарушается]
2. **Инвариант 2**: [Условие, всегда истинное]
3. **Инвариант 3**: [Гарантия возвращаемого значения]

---

**Edge cases**:
1. **Case name**: [Описание сценария] → [Поведение метода]
2. **Case name**: [Описание сценария] → [Поведение метода]
3. **Case name**: [Описание сценария] → [Поведение метода]

---

**Связанные методы**:
- `helper_method()` line XXX - [назначение вспомогательного метода]
- `OtherClass.method()` - [как используется]

**Performance заметки** (опционально):
- **Bottleneck**: [Описание узкого места]
- **Optimization**: [Текущая оптимизация]
- **Benchmark**: [Данные производительности, если есть]

---
```

## Примеры заполнения

### Пример 1: Простой алгоритм

```markdown
### Метод: `CacheDependencyGraph._topological_order()`

**Расположение**: `connector/domain/cache_core/cache_dependency_graph.py:91`

**Сигнатура**:
```python
def _topological_order(
    datasets: Sequence[str],
    dep_map: Mapping[str, Sequence[str]],
) -> tuple[str, ...]:
```

**Назначение**:
Вычислить топологический порядок датасетов для корректного выполнения операций. Использует алгоритм Кана.

**Алгоритм**:
```
1. Инициализация (lines 95-100)
   - Создать indegree для каждого датасета
   - Построить граф обратных рёбер

2. Начальная очередь (line 102)
   - Добавить все датасеты с indegree == 0

3. Обработка (lines 104-110)
   - WHILE очередь не пуста:
       → current = взять из очереди
       → добавить current в ordered
       → FOR EACH dependent OF current:
           → indegree[dependent] -= 1
           → IF indegree[dependent] == 0: добавить в очередь

4. Проверка циклов (lines 112-113)
   - IF len(ordered) != len(datasets): raise ValueError
```

**Временная сложность**:
- **Best/Average/Worst**: O(V + E) - алгоритм Кана линеен

**Инварианты**:
1. Граф не содержит циклов (иначе ValueError)
2. Порядок всегда корректен для топологической сортировки

**Edge cases**:
1. **Один датасет**: Возвращает `(dataset,)`
2. **Линейная цепь** A→B→C: Возвращает `("A", "B", "C")`
3. **Цикл** A→B, B→A: ValueError "contains dependency cycle"

**Связанные методы**:
- `CacheDependencyGraph.__init__()` - вызывает при создании
```

### Пример 2: Сложный алгоритм с edge cases

```markdown
### Метод: `ResolveCore.resolve()`

**Расположение**: `connector/domain/transform/resolver/resolve_core.py:111`

**Сигнатура**:
```python
def resolve(
    self,
    matched: MatchedRow,
    *,
    target_id_map: dict[str, str],
    meta: dict[str, Any] | None = None,
    batch_index: dict[str, dict[str, list[str]]] | None = None,
) -> tuple[ResolvedRow | None, list[DiagnosticItem], list[DiagnosticItem]]:
```

**Назначение**:
Принять решение об операции (create/update/skip) и разрешить все FK ссылки в desired_state.

**Алгоритм**:
```
1. Validation (lines 132-150)
   - IF AMBIGUOUS or CONFLICT → early exit with error

2. Merge Policy (lines 152-172)
   - Apply merge_policy if configured
   - Protect explicitly set fields

3. Link Resolution (lines 174-183)
   - Resolve all FK fields
   - Create pending if unresolved

4. Sink Validation (lines 185-192)
   - Check immutable fields not changed

5. Target ID Resolution (lines 194-206)
   - Resolve target_id from map

6. Decide Op (line 208)
   - Determine create/update/skip

7. Build Result (lines 210-231)
   - Construct ResolvedRow
```

**Временная сложность**:
- **Best case**: O(1) - no links, direct passthrough
- **Average case**: O(n×k) - n links × k keys
- **Worst case**: O(n×k×m) - with m dedup rules

**Инварианты**:
1. Всегда возвращает tuple из 3 элементов
2. Если первый элемент None, errors непустой
3. Не мутирует входной matched.desired_state

**Edge cases**:
1. **AMBIGUOUS match**: None + error "RESOLVE_AMBIGUOUS"
2. **Missing cache_gateway**: Error if link rules exist
3. **Immutable field mutation**: Blocked by sink validation
4. **merge_policy overwrites**: Warning + preserve original

**Связанные методы**:
- `_resolve_links()` line 236 - обработка LinkFieldRule
- `_decide_op()` line 394 - определение операции

**Performance заметки**:
- **Bottleneck**: FK resolution без batch_index (N queries)
- **Optimization**: batch_index для in-memory lookup
- **Benchmark**: 10K records с 3 FK: 8 сек (с index) vs 45 сек (без)
```

## Советы по написанию

### ✅ Хорошие практики

- **Будь конкретным**: Используй номера строк, имена переменных из реального кода
- **Визуализируй**: ASCII диаграммы отлично показывают flow с ветвлениями
- **Определяй переменные**: Если используешь O(n×k), объясни что такое n и k
- **Реальные примеры**: Edge cases из реального кода, не гипотетические
- **Связанные методы**: Помогают понять контекст вызова

### ❌ Чего избегать

- ❌ Копировать весь код метода - используй pseudocode
- ❌ Слишком высокоуровнево: "Обрабатывает данные" → "Применяет топологическую сортировку"
- ❌ Игнорировать сложность: Если метод O(n²), укажи это
- ❌ Забывать про edge cases: Это самое ценное для понимания
- ❌ Писать "очевидные" вещи: "Возвращает result" не добавляет ценности

## Интеграция в документацию слоя

1. **Добавь в таблицу "Обзор сложных методов"**:
   ```markdown
   | Метод | Строк | Сложность | Назначение |
   |-------|-------|-----------|------------|
   | `ClassName.method()` | 118 | O(n log n) | Краткое описание |
   ```

2. **Создай детальную секцию** используя этот шаблон

3. **Сошлись на связанные методы** в их документации

## Дополнительные ресурсы

- [TEMPLATE.md](../TEMPLATE.md) - Полный шаблон документации слоя
- [cache-core.md](../layers/cache/cache-core.md) - Пример документации сложных методов
- [resolve-dsl.md](../layers/resolver/resolve-dsl.md) - Пример с визуальными диаграммами
