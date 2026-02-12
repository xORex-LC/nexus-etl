# Testing Guide — Как добавлять тесты и покрывать код

> **Руководство по тестированию** для разработчиков проекта AnkeyIDM

---

## 📑 Содержание

- [Типы тестов](#типы-тестов)
- [Где добавлять тесты](#где-добавлять-тесты)
- [Как писать тесты](#как-писать-тесты)
- [Как запускать тесты](#как-запускать-тесты)
- [Coverage](#coverage)
- [Performance тесты](#performance-тесты)

---

## Типы тестов

### 1. Unit Tests

**Определение**: Изолированные тесты классов/функций с mock зависимостями

**Когда использовать**:
- Тестируешь один класс/функцию
- Нужно проверить внутреннюю логику
- Хочешь быстрый feedback (<1 сек)

**Паттерн**:
- Mock все зависимости (DummyClient, DummyExecutor)
- Используй SQLite in-memory если нужна DB
- Не делай real HTTP calls или file I/O

**Пример**:
```python
# tests/unit/infrastructure/test_request_executor.py
from connector.infra.http.request_executor import AnkeyRequestExecutor

class DummyClient:
    def requestAny(self, **kwargs):
        return 200, {"ok": True}, None

def test_executor_passes_payload():
    client = DummyClient()
    executor = AnkeyRequestExecutor(client)
    payload = {"name": "Jane"}

    result = executor.execute(RequestSpec.put("/user/1", payload=payload))

    assert result.ok is True
```

**Расположение**: `tests/unit/{слой}/`

---

### 2. Integration Tests

**Определение**: Тесты взаимодействия компонентов (реальный SQLite, config loader)

**Когда использовать**:
- Тестируешь взаимодействие 2+ компонентов
- Нужно проверить работу с реальной DB
- Проверяешь конфигурацию

**Паттерн**:
- Используй реальные компоненты (SQLite, config loader)
- Mock только внешние системы (HTTP API)
- Средние по скорости (1-5 сек)

**Пример**:
```python
# tests/integration/cache/test_sqlite_engine_transactions.py
def test_transaction_rollback():
    engine = SqliteEngine(in_memory=True)

    with engine.transaction():
        engine.execute("INSERT INTO cache ...")
        raise Exception("Rollback!")

    # Verify: data not persisted
    rows = engine.query("SELECT * FROM cache")
    assert len(rows) == 0
```

**Расположение**: `tests/integration/{слой}/`

---

### 3. E2E (End-to-End) Tests

**Определение**: Полный pipeline от CLI до результата

**Когда использовать**:
- Тестируешь полный user flow
- Проверяешь CLI команды
- Нужно убедиться что всё работает вместе

**Паттерн**:
- Используй `CliRunner`
- Создавай temporary directories
- Mock HTTP API (httpx.MockTransport)
- Медленные (5-30 сек)

**Пример**:
```python
# tests/e2e/pipelines/test_enrich_pipeline.py
from typer.testing import CliRunner
from connector.main import app

def test_enrich_creates_cache(tmp_path):
    csv = tmp_path / "data.csv"
    csv.write_text("id,name\\n1,John")

    runner = CliRunner()
    result = runner.invoke(app, [
        "--cache-dir", str(tmp_path / "cache"),
        "enrich",
        "--csv", str(csv)
    ])

    assert result.exit_code == 0
    assert (tmp_path / "cache" / "employees.db").exists()
```

**Расположение**: `tests/e2e/{категория}/`

---

### 4. Architecture Tests

**Определение**: Проверка архитектурных ограничений (layer boundaries)

**Когда использовать**:
- Проверяешь что domain не импортирует infrastructure
- Проверяешь зависимости между слоями
- Enforcing architectural rules

**Пример**:
```python
# tests/architecture/test_cache_layer_boundaries.py
def test_cache_core_does_not_import_infrastructure():
    cache_core_path = Path("connector/domain/cache_core")

    for py_file in cache_core_path.rglob("*.py"):
        content = py_file.read_text()
        assert "from connector.infra" not in content, \
            f"{py_file} violates layer boundary"
```

**Расположение**: `tests/architecture/`

---

### 5. Performance Tests

**Определение**: Измерение производительности, throughput, latency

**Когда использовать**:
- Проверяешь performance критичного кода
- Хочешь измерить speedup от оптимизации
- Regression testing для performance

**Пример**:
```python
# tests/performance/test_resolve_core_perf.py
import time

def test_batch_index_speedup():
    rows = [make_row() for _ in range(1000)]

    # Without batch_index
    start = time.perf_counter()
    for row in rows:
        resolver.resolve(row, target_id_map={})
    time_without = time.perf_counter() - start

    # With batch_index
    batch_index = resolver.build_batch_index(rows, "employees")
    start = time.perf_counter()
    for row in rows:
        resolver.resolve(row, target_id_map={}, batch_index=batch_index)
    time_with = time.perf_counter() - start

    speedup = time_without / time_with
    print(f"Speedup: {speedup:.1f}x")
    assert speedup > 1.5
```

**Расположение**: `tests/performance/`

**Важно**: Performance тесты запускаются **отдельно** (не в обычном CI)

---

## Где добавлять тесты

### Decision Tree

```
Я хочу протестировать...

1. Один класс/функцию с mock зависимостями?
   → tests/unit/{слой}/

2. Взаимодействие компонентов (SQLite, config)?
   → tests/integration/{слой}/

3. CLI команду или полный pipeline?
   → tests/e2e/{категория}/

4. Архитектурное ограничение?
   → tests/architecture/

5. Performance/benchmark?
   → tests/performance/
```

### Примеры по слоям

**Cache**:
- Unit: `tests/unit/cache/test_cache_planners.py`
- Integration: `tests/integration/cache/test_sqlite_engine.py`
- E2E: `tests/e2e/pipelines/test_cache_refresh_pipeline.py`

**Transform**:
- Unit: `tests/unit/transform/test_resolver.py`
- Integration: `tests/integration/transform/test_dsl_build_options.py`
- E2E: `tests/e2e/pipelines/test_enrich_pipeline.py`

**Infrastructure**:
- Unit: `tests/unit/infrastructure/test_ankey_client.py`
- Integration: `tests/integration/config/test_config_priority.py`
- E2E: `tests/e2e/api/test_api_cache_refresh.py`

---

## Как писать тесты

### Best Practices

#### 1. Названия тестов

**Хорошо**:
```python
def test_executor_returns_error_on_409():
    """Тест: RequestExecutor возвращает CONFLICT при 409 статусе"""

def test_cache_refresh_respects_dependencies():
    """Тест: cache refresh выполняется в топологическом порядке"""
```

**Плохо**:
```python
def test1():  # Непонятно что тестируем
def test_everything():  # Слишком общее
```

#### 2. Arrange-Act-Assert

```python
def test_resolve_creates_plan_for_new_record():
    # Arrange
    matched = MatchedRow(
        desired_state={"name": "John"},
        existing=None,  # Нет existing → create
        match_decision=MatchDecision(status=NOT_FOUND),
    )

    # Act
    resolved, errors, warnings = resolver.resolve(matched, target_id_map={})

    # Assert
    assert resolved is not None
    assert resolved.op == "create"
    assert errors == []
```

#### 3. Fixtures

Используй fixtures для переиспользования setup:

```python
# tests/unit/conftest.py
@pytest.fixture
def dummy_executor():
    """Mock executor для тестов"""
    class DummyExecutor:
        def execute(self, spec):
            return ExecutionResult(ok=True, status_code=200)
    return DummyExecutor()

# tests/unit/usecases/test_apply.py
def test_apply_calls_executor(dummy_executor):
    use_case = ApplyUseCase(executor=dummy_executor)
    use_case.execute(plan)
    # ...
```

#### 4. Mocking

**Используй Dummy Objects** для простых случаев:

```python
class DummyClient:
    def requestAny(self, **kwargs):
        return 200, {"ok": True}, None
```

**Используй httpx.MockTransport** для HTTP:

```python
def responder(request):
    if request.url.path == "/users":
        return httpx.Response(200, json=[{"id": 1}])
    return httpx.Response(404)

transport = httpx.MockTransport(responder)
client = AnkeyApiClient(transport=transport, ...)
```

#### 5. Assertions

**Хорошо**:
```python
assert resolved.op == "create", f"Expected create, got {resolved.op}"
assert len(errors) == 0, f"Expected no errors, got {errors}"
```

**Плохо**:
```python
assert resolved  # Непонятно что проверяем
assert True  # Бесполезная проверка
```

---

## Как запускать тесты

### Все тесты

```bash
pytest tests/ -v
```

### По типу

```bash
# Unit тесты (быстрые)
pytest tests/unit/ -v

# Integration тесты
pytest tests/integration/ -v

# E2E тесты (медленные)
pytest tests/e2e/ -v

# Architecture тесты
pytest tests/architecture/ -v
```

### По слою

```bash
# Все тесты для cache
pytest tests/unit/cache/ tests/integration/cache/ -v

# Все тесты для transform
pytest tests/unit/transform/ tests/integration/transform/ -v
```

### С markers

```bash
# Только unit тесты
pytest -m unit

# Только integration тесты
pytest -m integration

# Исключить медленные тесты
pytest -m "not slow"

# Unit + integration (без E2E)
pytest -m "unit or integration"
```

### С coverage

```bash
# С coverage отчётом
pytest --cov=connector --cov-report=term

# С HTML отчётом
pytest --cov=connector --cov-report=html
# Открыть: htmlcov/index.html
```

### Отдельный файл

```bash
pytest tests/unit/cache/test_cache_planners.py -v
```

### Отдельный тест

```bash
pytest tests/unit/cache/test_cache_planners.py::test_refresh_planner_orders_datasets -v
```

---

## Coverage

### Измерение coverage

```bash
# Terminal отчёт
pytest --cov=connector --cov-report=term

# HTML отчёт (детальный)
pytest --cov=connector --cov-report=html
open htmlcov/index.html

# Fail если coverage < 80%
pytest --cov=connector --cov-fail-under=80
```

### Целевые уровни

| Слой | Target Coverage | Текущий |
|------|----------------|---------|
| Cache Core | 90%+ | ✅ ~85% |
| Transform | 85%+ | ✅ ~80% |
| Use Cases | 80%+ | ✅ ~75% |
| Infrastructure | 70%+ | ⚠️ ~65% |

### Что покрывать

**Высокий приоритет**:
- ✅ Domain logic (cache_core, transform)
- ✅ Use cases
- ✅ Critical algorithms (resolve, match)

**Средний приоритет**:
- ⚠️ Infrastructure (SQLite repos, HTTP clients)
- ⚠️ DSL compilers

**Низкий приоритет**:
- ❌ CLI entry points (покрываются E2E)
- ❌ Config loading (покрывается integration)

### Игнорирование

Добавь в `.coveragerc` если нужно:

```ini
[run]
omit =
    */tests/*
    */migrations/*
    */__pycache__/*
```

---

## Performance тесты

### Структура

```
tests/performance/
├── conftest.py              # Fixtures для performance
├── README.md                # Как запускать, как интерпретировать
└── test_resolve_core_perf.py  # Benchmark для ResolveCore
```

### Запуск

```bash
# Только performance тесты (не запускаются в обычном CI)
pytest tests/performance/ -v -s

# С pytest-benchmark (если установлен)
pytest tests/performance/ --benchmark-only
```

### Пример

```python
# tests/performance/test_resolve_core_perf.py
import time

def test_batch_index_speedup(resolver, make_rows):
    """
    Benchmark: batch_index optimization для ResolveCore.

    Измеряет speedup от использования batch_index vs cache queries.

    Expected: 3-5x speedup для 1000 записей
    """
    rows = make_rows(1000)

    # Baseline: без batch_index
    start = time.perf_counter()
    for row in rows:
        resolver.resolve(row, target_id_map={})
    time_without = time.perf_counter() - start

    # Optimized: с batch_index
    batch_index = resolver.build_batch_index(rows, "employees")
    start = time.perf_counter()
    for row in rows:
        resolver.resolve(row, target_id_map={}, batch_index=batch_index)
    time_with = time.perf_counter() - start

    speedup = time_without / time_with

    print(f"\n{'='*60}")
    print(f"Performance Test: batch_index optimization")
    print(f"{'='*60}")
    print(f"Rows: {len(rows)}")
    print(f"Without batch_index: {time_without:.3f}s ({len(rows)/time_without:.0f} rec/sec)")
    print(f"With batch_index:    {time_with:.3f}s ({len(rows)/time_with:.0f} rec/sec)")
    print(f"Speedup: {speedup:.1f}x")
    print(f"{'='*60}\n")

    # Regression check
    assert speedup > 2.0, f"Performance regression: expected >2x, got {speedup:.1f}x"
```

### Интерпретация

**Что смотреть**:
- Throughput (rec/sec)
- Speedup (ratio)
- Latency (time per operation)

**Регрессия**:
- Если speedup упал > 20% → investigate
- Если throughput упал > 30% → investigate

---

## Частые вопросы

### 1. Куда добавить тест для нового компонента?

**Если это domain logic** (без внешних зависимостей):
→ `tests/unit/{слой}/`

**Если использует SQLite/config**:
→ `tests/integration/{слой}/`

**Если это CLI команда**:
→ `tests/e2e/`

### 2. Нужно ли покрывать тестами всё?

**Нет!** Приоритезируй:
1. ✅ Critical business logic (domain)
2. ✅ Complex algorithms (resolve, match)
3. ⚠️ Infrastructure (SQLite, HTTP)
4. ❌ Glue code, config

### 3. Как тестировать приватные методы?

**Не тестируй напрямую!** Тестируй через публичный API:

```python
# ПЛОХО
def test_resolve_core_private_apply_dedup():
    resolver._apply_dedup_rules(...)  # ❌ Тестируем private

# ХОРОШО
def test_resolve_core_deduplicates_candidates():
    # Setup: multiple candidates
    matched = MatchedRow(...)

    # Act: public API вызовет _apply_dedup_rules внутри
    resolved, _, _ = resolver.resolve(matched, ...)

    # Assert: dedup сработал
    assert resolved.desired_state["manager_id"] == 42  # ✅ Один кандидат
```

### 4. Как ускорить тесты?

**Используй markers** для фильтрации:
```bash
# Только быстрые тесты (unit)
pytest -m unit

# Исключить медленные
pytest -m "not slow"
```

**Параллельный запуск** (pytest-xdist):
```bash
pip install pytest-xdist
pytest -n auto  # Использовать все CPU
```

### 5. Что делать если тест flaky (нестабильный)?

**Проблема**: Тест иногда падает

**Решения**:
1. Убрать race conditions (time.sleep → wait_until)
2. Изолировать state (каждый тест создаёт свою DB)
3. Пометить `@pytest.mark.flaky` и investigate

---

## CI/CD Integration

### GitHub Actions (пример)

```yaml
# .github/workflows/tests.yml
name: Tests

on: [push, pull_request]

jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/unit/ -v --cov=connector

  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/integration/ -v

  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/e2e/ -v
```

**Раздельные jobs** дают:
- ✅ Быстрый feedback (unit тесты проходят за 10 сек)
- ✅ Параллельный запуск
- ✅ Видно где именно падает (unit/integration/e2e)

---

## Заключение

**Ключевые принципы**:
1. ✅ **Пиши тесты** для критичной логики
2. ✅ **Используй правильный тип** теста (unit/integration/e2e)
3. ✅ **Поддерживай тесты** актуальными
4. ✅ **Запускай тесты** перед commit
5. ✅ **Проверяй coverage** для новых компонентов

**Помни**: Хороший тест — это тест который:
- Быстрый (unit < 1 сек)
- Понятный (clear name + AAA pattern)
- Изолированный (не зависит от других тестов)
- Детерминированный (всегда одинаковый результат)

---

**Вопросы?** Смотри [INDEX.md](../INDEX.md) или спроси в команде!
