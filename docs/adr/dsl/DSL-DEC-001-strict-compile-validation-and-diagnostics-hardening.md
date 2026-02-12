# DSL-DEC-001: Ужесточение compile/load контракта и диагностик DSL Core

> **Статус**: Принято ✅
> **Дата принятия**: 2026-02-12
> **Решает проблему**: [DSL-PROBLEM-001](./DSL-PROBLEM-001-dsl-core-fail-late-and-weak-compile-contract.md)
> **Участники решения**: @xorex

---

## 📋 Контекст

В DSL Core часть ошибок конфигурации и компиляции выявлялась поздно (на runtime), что противоречило целевому контракту fail-fast для декларативных стадий.  
Ключевые проблемы были зафиксированы в [DSL-PROBLEM-001](./DSL-PROBLEM-001-dsl-core-fail-late-and-weak-compile-contract.md):
1. слабая валидация unknown keys,
2. мягкое поведение loader для неизвестного dataset,
3. частично no-op compile-policy flags,
4. позднее выявление unknown ops,
5. бедный контекст runtime DSL-ошибок.

---

## 🎯 Решение

**Реализовать единый fail-fast контракт для DSL Core на этапе load/compile и усилить диагностический контекст runtime ошибок.**

### Архитектурные компоненты решения

1. **Строгая модельная валидация DSL-спеков**
   - unknown keys запрещаются на уровне pydantic-моделей.

2. **Fail-fast для stage build options**
   - неизвестный dataset в `build_options` теперь считается ошибкой wiring.

3. **Единая интерпретация strict policy**
   - `strict` принудительно включает защитные compile-флаги.

4. **Compile-time проверка DSL операций**
   - unknown ops блокируются до runtime потока данных.

5. **Расширенная runtime диагностика**
   - `DSL_OP_UNKNOWN` / `DSL_OP_FAILED` включают структурный context (`op`, `args`, `step`, `error`).

---

## 🏗️ Архитектурное решение

### Изменения в компонентах

| Компонент | Изменение |
|-----------|-----------|
| `connector/domain/dsl/specs.py` | Жёсткая валидация неизвестных полей |
| `connector/domain/dsl/loader.py` | Ошибка на неизвестный dataset в stage build options |
| `connector/domain/dsl/build_options.py` | `strict` теперь усиливает compile-policy consistently |
| `connector/domain/dsl/engine.py` | Улучшен diagnostics context для runtime ошибок |
| `connector/domain/transform/mapping/mapper_dsl.py` | Compile-check unknown ops |
| `connector/domain/transform/normalize/normalizer_dsl.py` | Compile-check unknown ops |
| `connector/domain/transform/enrich/enricher_dsl.py` | Compile-check unknown ops |
| `connector/domain/cache_core/cache_dsl.py` | Compile-check unknown ops для cache DSL путей |

### Инварианты после решения

1. **Unknown config keys fail-fast**: ошибки структуры DSL не пропускаются молча.
2. **Unknown dataset fail-fast**: wiring-ошибки не уводят в defaults.
3. **Unknown ops fail-fast**: compile блокирует некорректные операции.
4. **Diagnostics context is structured**: runtime ошибки содержат достаточный контекст для triage.

---

## ✅ Почему это решение?

### Преимущества:

- ✅ Переносит ошибки в раннюю фазу (`load/compile`) вместо runtime.
- ✅ Повышает надёжность DSL-пайплайна при росте числа датасетов.
- ✅ Упрощает диагностику массовых ошибок в execution path.
- ✅ Делает strict mode предсказуемым и реально рабочим.
- ✅ Выравнивает поведение compile-пути между transform и cache DSL.

### Недостатки (компромиссы):

- ⚠️ Более строгий контракт может сломать исторические «мягкие» спек-файлы.
  - **Приемлемо, потому что**: это целевой fail-fast режим и явное обнаружение ошибок.
- ⚠️ Потребовалась корректировка тестов и части документации.
  - **Приемлемо, потому что**: изменения системные и повышают качество платформы.

### Отклонённые альтернативы:

- ❌ Оставить мягкий режим и усиливать только runtime fallback:
  - не решает root cause fail-late поведения.
- ❌ Частично ужесточить только loader или только engine:
  - даёт неполный эффект и сохраняет пробелы в контракте.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Описание изменения |
|------|-------------------|
| `connector/domain/dsl/specs.py` | Запрет unknown keys в DSL-моделях |
| `connector/domain/dsl/loader.py` | Ошибка для неизвестного dataset в build options |
| `connector/domain/dsl/build_options.py` | Нормализация strict -> compile policy |
| `connector/domain/dsl/engine.py` | Расширенные details для `DSL_OP_UNKNOWN/FAILED` |
| `connector/domain/cache_core/cache_dsl.py` | Compile-time unknown op validation |
| `connector/domain/transform/mapping/mapper_dsl.py` | Compile-time unknown op validation |
| `connector/domain/transform/normalize/normalizer_dsl.py` | Compile-time unknown op validation |
| `connector/domain/transform/enrich/enricher_dsl.py` | Compile-time unknown op validation |

### Ключевые тесты

| Файл | Покрытие |
|------|----------|
| `tests/integration/transform/test_dsl_build_options.py` | Поведение build options и strict policy |
| `tests/unit/cache/test_cache_compiler.py` | Compile validation для cache DSL |
| `tests/unit/transform/test_mapping_dsl.py` | Compile validation mapping DSL |

---

## 🧪 Валидация решения

### Что проверено

1. Unknown keys в DSL-моделях больше не игнорируются.
2. Неизвестный dataset в stage build options вызывает явную ошибку.
3. Unknown ops выявляются на compile фазе.
4. Runtime diagnostics включают контекст операции и шага.
5. Целевой набор unit/integration тестов проходит.

### Критерии успеха

1. Нет fail-late для указанных классов ошибок DSL.
2. Снижен риск «тихих» конфигурационных регрессий.
3. Логи/диагностика достаточны для быстрого triage.

---

## ⚠️ Риски и ограничения

### Известные ограничения

1. Ужесточение контракта не устраняет автоматически все legacy-артефакты в существующих YAML — требуется миграционная дисциплина.
2. Новые кастомные ops всё равно требуют корректной регистрации и тестов.

### Риски

- ⚠️ Риск: временный рост числа compile-ошибок после включения строгих правил.
  - **Митигация**: постепенная правка спеков + CI gate на compile.
- ⚠️ Риск: неодинаковая интерпретация флагов в новых DSL компонентах.
  - **Митигация**: reuse существующего policy pipeline и тестов build options.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| Transform stage DSL (mapping/normalize/enrich) | Прямое | Поддерживать compile-time op validation |
| Cache DSL compile path | Прямое | Поддерживать compile-time op validation |
| CI / тесты DSL | Прямое | Проверять fail-fast и diagnostics context |
| Dataset YAML авторинг | Косвенное | Учитывать строгий контракт unknown keys/ops |

---

## 📚 Документация

**Обновлена/добавлена документация**:
- ✅ [DSL-PROBLEM-001](./DSL-PROBLEM-001-dsl-core-fail-late-and-weak-compile-contract.md)
- ✅ `docs/adr/INDEX.md` (раздел DSL)
- ✅ `docs/DSL_Core_Issues.md` (статус проблем и прогресс)

---

## 🔗 Связанные документы

- [DSL-PROBLEM-001](./DSL-PROBLEM-001-dsl-core-fail-late-and-weak-compile-contract.md)
- `docs/DSL_Core_Issues.md`
- `docs/dev/layers/dsl/dsl-specs.md`

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-12 | Решение предложено |
| 2026-02-12 | Решение принято после согласования |
| 2026-02-12 | Реализовано в ветках `dsl/cache-layer` и `dsl-core` |
