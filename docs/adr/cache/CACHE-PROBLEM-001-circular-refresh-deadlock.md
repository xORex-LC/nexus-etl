# CACHE-PROBLEM-001: Circular refresh deadlock при зависимых датасетах

> **Статус**: Решена в [CACHE-DEC-001](./CACHE-DEC-001-topological-sort-for-dependencies.md)
> **Дата создания**: 2026-02-11
> **Затронутые компоненты**: `CacheRefreshPlanner`, cache refresh workflow

---

## 📋 Контекст

Проект AnkeyIDM растёт, количество датасетов увеличилось с начальных 10 до 50+. Появились сложные цепочки зависимостей между датасетами:
- `employees` → базовый датасет
- `employee_mappings` → зависит от `employees` (использует FK на employee_id)
- `employee_projects` → зависит от `employees`

При обновлении кэша (cache refresh) начали возникать ситуации, когда зависимые датасеты обновлялись **раньше**, чем их зависимости, что приводило к некорректным данным и массовому созданию pending links.

---

## ⚠️ Проблема

**Суть**: При refresh кэша датасеты обновляются в произвольном порядке, что нарушает целостность данных когда:
- Датасет B зависит от датасета A (B ссылается на A через FK)
- Если B обновляется первым, он пытается резолвить FK на устаревшие/отсутствующие данные из A
- Это приводит к массовому созданию pending links, даже когда данные есть в source

**Технически**:
- `CacheRefreshPlanner.plan()` возвращает датасеты в порядке `list(dep_map.keys())`
- Порядок ключей в dict не гарантирован относительно зависимостей
- UseCase выполняет refresh в полученном порядке

---

## 🔍 Симптомы

- **FK resolution failures**: `_resolve_links()` в ResolveCore не находит записи, которые должны быть в кэше
- **Массовые pending links**: Создаются pending для записей, которые на следующем refresh резолвятся без проблем
- **Race condition**: При повторном refresh проблема иногда исчезает (если порядок случайно правильный)
- **Логи**: `WARNING: Created pending link for employee_mapping.employee_id → employees.id (not found in cache)`

**Пример из логов**:
```
[INFO] Refreshing cache for datasets: ['employee_mappings', 'employees']
[INFO] Refresh 'employee_mappings' - 1000 records
[WARNING] Created 950 pending links for employee_mappings.employee_id
[INFO] Refresh 'employees' - 1000 records
[INFO] Resolving pending links: 950 resolved, 0 failed
```
^ Порядок неправильный: `employee_mappings` обновился **до** `employees`

---

## 📊 Масштаб проблемы

- **Частота**: Всегда при refresh более 2 зависимых датасетов одновременно
- **Критичность**: Высокая (не блокирующая полностью, но создаёт много лишней работы)
- **Затронуто**:
  - Все ETL pipelines с зависимостями между датасетами (~80% pipelines)
  - UseCase `RefreshCacheUseCase`
  - Все датасеты с FK: `employee_mappings`, `employee_projects`, `departments`, и др.

**Метрики**:
- Pending links создаются для ~90% записей зависимых датасетов при неправильном порядке
- На повторный resolve тратится дополнительное время (~30% overhead)

---

## 🧪 Как воспроизвести

1. Настроить зависимость в `cache.yaml`:
   ```yaml
   dependencies:
     employee_mappings:
       - employees
   ```

2. Вызвать refresh для обоих датасетов:
   ```python
   use_case.refresh_cache(["employees", "employee_mappings"])
   ```

3. Проверить логи и порядок обновления

4. **Ожидаемый результат**: `employees` обновляется перед `employee_mappings`

5. **Фактический результат**: Порядок произвольный:
   - Иногда `['employees', 'employee_mappings']` ✓ (правильно)
   - Иногда `['employee_mappings', 'employees']` ✗ (неправильно)

---

## 🚫 Почему это проблема?

1. **Data integrity**: FK resolution работает некорректно при неправильном порядке
2. **Performance**: Создаются лишние pending links → дополнительный resolve pass
3. **Непредсказуемость**: Behaviour зависит от порядка ключей в dict (implementation detail Python)
4. **Масштабируемость**: Проблема усиливается с ростом количества датасетов и сложности зависимостей
5. **Сложность отладки**: Race condition затрудняет воспроизведение и диагностику

---

## 💡 Возможные решения (обсуждение)

### Вариант 1: Manual ordering в конфигурации
- **Идея**: Пользователь вручную указывает порядок refresh в `cache.yaml`
  ```yaml
  refresh_order:
    - employees
    - employee_mappings
    - employee_projects
  ```
- **Плюсы**: Простота реализации (~10 строк кода)
- **Минусы**:
  - Высокая вероятность ошибки при ручном указании
  - Не масштабируется (нужно обновлять при добавлении датасетов)
  - Дублирование информации (зависимости уже есть в `dependencies`)

### Вариант 2: Топологическая сортировка (алгоритм Кана)
- **Идея**: Автоматически вычислять порядок refresh на основе `dep_map` с использованием topological sort
- **Плюсы**:
  - Гарантирует корректность математически
  - Автоматический — не требует ручной настройки
  - Выявляет циклические зависимости на этапе инициализации (fail-fast)
- **Минусы**:
  - Нужно реализовать алгоритм Кана (~30 строк)
  - Дополнительный класс `CacheDependencyGraph` для абстракции

### Вариант 3: Lazy resolution с retry
- **Идея**: Всегда создавать pending, делать несколько проходов resolve до стабилизации
- **Плюсы**: Не требует изменений в архитектуре
- **Минусы**:
  - Скрывает root cause проблемы
  - Высокий overhead (многократные проходы)
  - Не решает проблему циклических зависимостей

---

## 🔗 Связанные документы

- [CACHE-DEC-001](./CACHE-DEC-001-topological-sort-for-dependencies.md) — принятое решение
- [cache-core.md](../../dev/layers/cache/cache-core.md) — документация Cache Core слоя
- `connector/domain/cache_core/cache_refresh_planner.py` — текущая реализация

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-11 | Проблема обнаружена в production (массовые pending links) |
| 2026-02-11 | Решение принято в CACHE-DEC-001 (топологическая сортировка) |
| 2026-02-11 | Реализован `CacheDependencyGraph` с алгоритмом Кана |
