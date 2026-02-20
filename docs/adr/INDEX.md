# Architecture Decision Records (ADR)

> **Назначение**: История архитектурных решений проекта AnkeyIDM

---

## 📋 Что такое ADR?

**Architecture Decision Records (ADR)** — это документы, фиксирующие:
- **Проблемы** ([LAYER]-PROBLEM-XXX) — что было не так, почему возникла необходимость в изменении
- **Решения** ([LAYER]-DEC-XXX) — какое архитектурное решение было принято и почему

**Зачем это нужно?**
- Сохранить контекст: "Почему мы сделали именно так?"
- Избежать повторения ошибок: "Мы уже пробовали это, и вот почему отказались"
- Передать знания: новый разработчик понимает историю проекта

---

## 🗂️ Структура

```
docs/adr/
├── cache/              # ADR для Cache слоя
│   ├── CACHE-PROBLEM-001-...md
│   ├── CACHE-DEC-001-...md
│   └── ...
├── dsl/                # ADR для DSL Core
│   ├── DSL-PROBLEM-001-...md
│   ├── DSL-DEC-001-...md
│   └── ...
├── vault/              # ADR для Vault/Security слоя
│   ├── VAULT-PROBLEM-001-...md
│   ├── VAULT-DEC-001-...md
│   └── ...
├── transform/          # ADR для Transform слоя (resolve, mapping, etc)
│   ├── RESOLVE-PROBLEM-001-...md
│   ├── RESOLVE-DEC-001-...md
│   └── ...
├── TEMPLATE-PROBLEM.md # Шаблон для проблем
├── TEMPLATE-DECISION.md # Шаблон для решений
└── INDEX.md           # Этот файл
```

---

## 📚 Все ADR (хронологически)

### Cache

| ID | Тип | Название | Статус | Дата |
|----|-----|----------|--------|------|
| [CACHE-PROBLEM-001](./cache/CACHE-PROBLEM-001-circular-refresh-deadlock.md) | Problem | Circular refresh deadlock | Решена в CACHE-DEC-001 | 2026-02-11 |
| [CACHE-DEC-001](./cache/CACHE-DEC-001-topological-sort-for-dependencies.md) | Decision | Топологическая сортировка для зависимостей | Принято | 2026-02-11 |
| [CACHE-PROBLEM-002](./cache/CACHE-PROBLEM-002-sqlite-infra-divergence.md) | Problem | Расхождение SQLite-инфраструктуры между Cache и Vault | Решена в CACHE-DEC-002 | 2026-02-19 |
| [CACHE-DEC-002](./cache/CACHE-DEC-002-unified-sqlite-infra-layer.md) | Decision | Единый SQLite-инфраструктурный слой (connector/infra/sqlite/) | Принято | 2026-02-19 |

### Config

| ID | Тип | Название | Статус | Дата |
|----|-----|----------|--------|------|
| [CONFIG-PROBLEM-001](./config/CONFIG-PROBLEM-001-settings-layer-complexity.md) | Problem | Перегруженный Settings-слой и неявные ошибки мерджа | Закрыта (решена) | 2026-02-12 |
| [CONFIG-DEC-001](./config/CONFIG-DEC-001-modular-settings-and-slice-wiring.md) | Decision | Модульный Settings и slice-based wiring | Принято / реализовано | 2026-02-12 |
| [CONFIG-PROBLEM-002](./config/CONFIG-PROBLEM-002-manual-settings-validation.md) | Problem | Ручная валидация Settings и отсутствие Pydantic в конфиг-слое | Решена в CONFIG-DEC-002 | 2026-02-19 |
| [CONFIG-DEC-002](./config/CONFIG-DEC-002-pydantic-settings-migration.md) | Decision | Миграция Settings на Pydantic BaseSettings | Принято (реализация отложена) | 2026-02-19 |

### DSL

| ID | Тип | Название | Статус | Дата |
|----|-----|----------|--------|------|
| [DSL-PROBLEM-001](./dsl/DSL-PROBLEM-001-dsl-core-fail-late-and-weak-compile-contract.md) | Problem | DSL Core fail-late поведение и слабый compile-контракт | Закрыта (решена) | 2026-02-12 |
| [DSL-DEC-001](./dsl/DSL-DEC-001-strict-compile-validation-and-diagnostics-hardening.md) | Decision | Усиление compile/load контракта и диагностик DSL Core | Принято / реализовано | 2026-02-12 |
| [DSL-PROBLEM-002](./dsl/DSL-PROBLEM-002-dsl-core-coupling-and-contract-drift-under-scale.md) | Problem | Архитектурная связность DSL Core и дрейф контрактов при росте | Решена в DSL-DEC-002 | 2026-02-13 |
| [DSL-DEC-002](./dsl/DSL-DEC-002-modular-dsl-core-and-contract-stabilization.md) | Decision | Модульная декомпозиция DSL Core и стабилизация compile/runtime контрактов | Принято / реализовано | 2026-02-13 |
| [DSL-PROBLEM-003](./dsl/DSL-PROBLEM-003-dsl-core-mixed-responsibilities.md) | Problem | DSL Core смешивает generic инфраструктуру с layer-специфичным кодом | Решена в DSL-DEC-003 | 2026-02-17 |
| [DSL-PROBLEM-004](./dsl/DSL-PROBLEM-004-inconsistent-transform-compile-architecture.md) | Problem | Неконсистентная compile-архитектура transform стейджей | Решена в DSL-DEC-004 | 2026-02-17 |
| [DSL-DEC-003](./dsl/DSL-DEC-003-per-layer-dsl-modules.md) | Decision | Per-layer DSL модули и чистый DSL Core | Принято | 2026-02-17 |
| [DSL-DEC-004](./dsl/DSL-DEC-004-standardized-compile-contract.md) | Decision | Стандартизированный compile-контракт transform стейджей | Принято | 2026-02-17 |

### Transform

| ID | Тип | Название | Статус | Дата |
|----|-----|----------|--------|------|
| [TRANSFORM-PROBLEM-001](./transform/TRANSFORM-PROBLEM-001-enrich-dictionary-runtime-gap.md) | Problem | Отсутствует runtime-реализация справочников для enrich lookup | Открыта (кандидат решения: TRANSFORM-DEC-001) | 2026-02-19 |
| [TRANSFORM-DEC-001](./transform/TRANSFORM-DEC-001-columnar-dictionary-runtime-for-enricher.md) | Decision | Справочная подсистема enrich (Polars v1, migration-ready для v2: Polars+DuckDB+Parquet) | Предложено | 2026-02-19 |
| [TRANSFORM-PROBLEM-002](./transform/TRANSFORM-PROBLEM-002-transform-provider-deps-coupling.md) | Problem | TransformProviderDeps coupling: обязательный cache_gateway нарушает pay-for-what-you-use | Открыта (митигация применена, цель: TRANSFORM-DEC-002) | 2026-02-20 |
| [TRANSFORM-DEC-002](./transform/TRANSFORM-DEC-002-transform-context-capability-registry.md) | Decision | TransformContext — typed capability registry как целевая архитектура для transform-зависимостей | Предложено (реализация отложена до trigger-критериев) | 2026-02-20 |

### Target

| ID | Тип | Название | Статус | Дата |
|----|-----|----------|--------|------|
| [TARGET-PROBLEM-001](./target/TARGET-PROBLEM-001-load-layer-target-wiring.md) | Problem | Нечистая граница load-слоя (apply/refresh/check) и зависимость CLI wiring от конкретного target | Закрыта (решена в TARGET-DEC-001, уточнена TARGET-DEC-003) | 2026-02-13 |
| [TARGET-DEC-001](./target/TARGET-DEC-001-target-runtime-target-spec-slice.md) | Decision | TargetRuntime + target-spec slice для изоляции load-слоя от target-инфры | Принято / реализовано (частично superseded TARGET-DEC-003) | 2026-02-13 |
| [TARGET-PROBLEM-002](./target/TARGET-PROBLEM-002-usecase-output-infra-leaks.md) | Problem | Use-case Apply загрязнён output/infra деталями и размывает границы ответственности | Закрыта (решена в TARGET-DEC-002) | 2026-02-13 |
| [TARGET-DEC-002](./target/TARGET-DEC-002-usecase-apply-result-presenter.md) | Decision | Apply use-case возвращает ApplyResult, а отчёт формируется презентером | Принято / реализовано | 2026-02-13 |
| [TARGET-PROBLEM-003](./target/TARGET-PROBLEM-003-target-core.md) | Problem | “Коммодити”-механики Target слоя | Закрыта (решена в TARGET-DEC-003) | 2026-02-16 |
| [TARGET-DEC-003](./target/TARGET-DEC-003-target-core.md) | Decision | TargetCore как plugin-core (core механики + provider-правила) | Принято / реализовано (каноничное для target-core) | 2026-02-16 |
| [TARGET-PROBLEM-004](./target/TARGET-PROBLEM-004-hardcoded-provider-spec.md) | Problem | Поведенческая spec провайдера захардкожена в Python | Решена в TARGET-DEC-004 | 2026-02-17 |
| [TARGET-DEC-004](./target/TARGET-DEC-004-target-dsl-declarative-provider.md) | Decision | target-dsl — YAML-описание поведенческой spec провайдера | Принято / реализовано | 2026-02-17 |

### Vault

| ID | Тип | Название | Статус | Дата |
|----|-----|----------|--------|------|
| [VAULT-PROBLEM-001](./vault/VAULT-PROBLEM-001-plaintext-dev-vault-and-missing-crypto-lifecycle.md) | Problem | Plaintext dev-vault и отсутствующий production-контур секретов | Решена в VAULT-DEC-001 | 2026-02-18 |
| [VAULT-DEC-001](./vault/VAULT-DEC-001-envelope-encrypted-vault-with-hexagonal-ports.md) | Decision | Envelope-encrypted vault с hexagonal разделением crypto/storage | Принято | 2026-02-18 |

### Observability

| ID | Тип | Название | Статус | Дата |
|----|-----|----------|--------|------|
| [OBSERVABILITY-PROBLEM-001](./observability/OBSERVABILITY-PROBLEM-001-inconsistent-logging.md) | Problem | Непоследовательное использование logging и structlog | Решена в OBSERVABILITY-DEC-001 | 2026-02-19 |
| [OBSERVABILITY-DEC-001](./observability/OBSERVABILITY-DEC-001-structlog-as-standard.md) | Decision | structlog как единственный стандарт логирования | Принято (миграция постепенная) | 2026-02-19 |

_(Список поддерживается как актуальный реестр ADR по слоям.)_

---

## 🎯 Как использовать

### Когда создавать PROBLEM?

Создавай документ PROBLEM когда:
- ✅ Обнаружена архитектурная проблема (не баг, а design issue)
- ✅ Текущий подход не масштабируется
- ✅ Возникла необходимость в значительном изменении архитектуры
- ✅ Нужно зафиксировать контекст для будущего обсуждения

**Не создавай PROBLEM для**:
- ❌ Простых багов (используй issue tracker)
- ❌ Мелких рефакторингов
- ❌ Очевидных улучшений без архитектурного влияния

### Когда создавать DECISION?

Создавай документ DECISION когда:
- ✅ Принято архитектурное решение, которое влияет на структуру проекта
- ✅ Выбрана одна из нескольких альтернатив (и нужно зафиксировать почему)
- ✅ Решение затрагивает несколько компонентов
- ✅ Решение имеет компромиссы, которые нужно объяснить будущим разработчикам

### Workflow

1. **Обнаружена проблема** → Создаётся `[LAYER]-PROBLEM-XXX.md`
2. **Обсуждение** → Возможные решения записываются в раздел "Возможные решения"
3. **Решение принято** → Создаётся `[LAYER]-DEC-XXX.md`, статус PROBLEM обновляется
4. **Реализация** → Код изменяется, ссылки на ADR добавляются в dev-документацию
5. **Обновление** → История в обоих документах обновляется

---

## 📝 Шаблоны

- [TEMPLATE-PROBLEM.md](./TEMPLATE-PROBLEM.md) — для фиксации проблем
- [TEMPLATE-DECISION.md](./TEMPLATE-DECISION.md) — для фиксации решений

**Как использовать шаблон**:
1. Скопируй соответствующий шаблон
2. Переименуй в `[LAYER]-{PROBLEM|DEC}-XXX-short-name.md`
3. Заполни все секции
4. Добавь в таблицу выше

---

## 🔗 Связанные документы

- [Dev Documentation INDEX](../dev/INDEX.md) — основная документация слоёв
- [TEMPLATE.md](../dev/TEMPLATE.md) — шаблон документации слоя

---

## 💡 Советы

### Хороший PROBLEM документ:
- ✅ Конкретный: чёткое описание проблемы с примерами
- ✅ Воспроизводимый: шаги как повторить проблему
- ✅ Обоснованный: объяснение почему это проблема (последствия)
- ✅ Краткий: 1-2 страницы, не эссе

### Хороший DECISION документ:
- ✅ Обоснованный: почему выбрали это решение, а не другие
- ✅ Практичный: конкретная реализация, файлы, методы
- ✅ Честный: фиксирует компромиссы и ограничения
- ✅ Связанный: ссылки на код, документацию, UML

### Что НЕ писать в ADR:
- ❌ Детали реализации (код) — для этого есть dev-документация
- ❌ Инструкции по использованию — для этого есть user guides
- ❌ История всех багов — ADR только для архитектурных решений

---

**Совет**: ADR — это не замена dev-документации! ADR объясняет "почему", dev-документация объясняет "как".
