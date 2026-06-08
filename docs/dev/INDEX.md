# Dev Documentation Index

> **Быстрая навигация** по dev-документации проекта

## 🗺️ Карта слоёв

### DSL Core
- [DSL Specs](layers/dsl/dsl-specs.md) — Pydantic-модели, YAML-загрузка, build options
- [DSL Engine](layers/dsl/dsl-engine.md) — Реестр операций, движок трансформаций, 25 core operations
- [DSL Diagnostics](layers/dsl/dsl-diagnostics.md) — Модель ошибок, диагностика, карта интеграции со слоями
- [DSL UML](../uml/transform/dsl/README.md) — Актуальные диаграммы dsl-core и integration points

### Cache
- [Cache Core](layers/cache/cache-core.md) — Логика планирования и анализа кэша
- [Cache DSL](layers/cache/cache-dsl.md) — Декларативные cache-политики через YAML
- [Cache Ports](layers/cache/cache-ports.md) — Интерфейсы для работы с кэшем (Protocols)
- [Cache Infrastructure](layers/cache/cache-infra.md) — Реализация хранилища кэша (SQLite)

### Config
- [CLI/Settings Layer](layers/config/cli-settings-layer.md) — Загрузка/валидация настроек и CLI runtime boundary

### Vault/Security
- [Vault Core](layers/vault/vault-core.md) — Бизнес-логика жизненного цикла секретов (`enrich -> plan -> apply`) и портовые границы

### Transform
- [Resolve DSL](layers/resolver/resolve-dsl.md) — Правила разрешения конфликтов
- [Resolve Core](layers/resolver/resolve-core.md) — Алгоритмы resolve и FK resolution
- Transform Core _(TODO)_ — Основная логика трансформации
- Mapping DSL _(TODO)_ — Маппинг полей
- Normalize DSL _(TODO)_ — Нормализация данных
- Enrich DSL _(TODO)_ — Обогащение данных

### Topology (dependency_tree)
- [Topology Core](layers/topology/topology-core.md) — Построение/query графа иерархии, comparison ladder, anchoring
- [Topology DSL](layers/topology/topology-dsl.md) — `TopologySpec`, source/target ingress, dual-form canonicalizer, consumer policies
- [Topology Ports](layers/topology/topology-ports.md) — Узкие порты и DTO boundary-слоя
- [Topology Infrastructure](layers/topology/topology-infra.md) — Cache/polars-ридеры и structlog event sink
- [Topology Runtime](layers/topology/topology-runtime.md) — Bootstrap-lifecycle, activation matrix, build-vs-wire, short-circuit
- [Topology Consumers](layers/topology/topology-consumers.md) — FK match/resolve (Phase 1a/1b) и source anchoring (Stage G)

### Observability
- [Observability Model](layers/observability/observability-model.md) — `ServiceComponent`/`ComponentIdentity`/`ObservabilityArtifactKind`, `ObservabilityLayout` как единственный владелец имён, canonical artifact layout
- [Observability Config](layers/observability/observability-config.md) — вложенная `ObservabilityConfig` + проекции; почему config, а не DSL
- [Observability Logging](layers/observability/observability-logging.md) — structlog runtime, processors/корреляция, redaction surface, sinks (daily+size файл, JSON→stderr), dual-transport
- [Observability Artifacts](layers/observability/observability-artifacts.md) — отчёты/планы (atomic), run ledger (jsonl/sqlite), retention sweeper, latest pointers
- [Observability Runtime](layers/observability/observability-runtime.md) — wiring в lifecycle команды, best-effort, DI-тиры, CLI (`maintenance prune`, `obs latest|tail`)

### Load/Extract
- Extract _(TODO)_ — Извлечение данных из источников
- Load _(TODO)_ — Загрузка данных в целевую систему

### Infrastructure
- Ports _(TODO)_ — Интерфейсы между слоями
- Adapters _(TODO)_ — Адаптеры к внешним системам

## 📚 Практические руководства

- [Как добавить DSL операцию](guides/how-to-add-dsl-operation.md) — Пошаговое руководство
- [Как добавить стадию пайплайна](guides/how-to-add-pipeline-stage.md) — Два пути: StageFactory и Singleton (TRANSFORM-DEC-007)
- [Как документировать сложный метод](guides/method-documentation-template.md) — Шаблон для методов 50+ строк
- Как создать новый слой _(TODO)_
- DSL паттерны _(TODO)_

## 📜 Architecture Decision Records (ADR)

> История архитектурных решений и проблем проекта

- [ADR Index](../adr/INDEX.md) — Полный список всех ADR с описанием формата
- [Шаблон PROBLEM](../adr/TEMPLATE-PROBLEM.md) — Как зафиксировать проблему
- [Шаблон DECISION](../adr/TEMPLATE-DECISION.md) — Как зафиксировать решение

**Недавние решения**:
- [CACHE-DEC-001](../adr/cache/CACHE-DEC-001-topological-sort-for-dependencies.md) — Топологическая сортировка для зависимостей
- [TRANSFORM-DEC-010](../adr/transform/TRANSFORM-DEC-010-topology-bootstrap-before-main-pipeline.md) — Topology bootstrap до основного planning pipeline
- _(Другие ADR появятся по мере возникновения проблем и принятия решений)_

**Зачем ADR?**
- 💡 Сохраняет контекст: "Почему мы сделали именно так?"
- 🚫 Предотвращает повторение ошибок
- 📖 Помогает новым разработчикам понять историю проекта

## 🗒️ Working Notes

> Рабочие заметки для исследований и обсуждений до фиксации проблемы или решения в ADR

- [Working Notes Index](../notes/INDEX.md)
- [Dependency Tree Worknote](../notes/dependency-tree/DEPENDENCY_TREE_WORKNOTE.md)

## 🎯 С чего начать?

### Я хочу добавить новую функциональность

1. **Найди слой**, который отвечает за нужную область (см. Карту слоёв)
2. **Прочитай документацию слоя** (секция "🛠️ Как расширять")
3. **Следуй чек-листу** в соответствующем руководстве

### Я забыл, как что-то работает

1. **Открой документацию слоя** (см. Карту слоёв)
2. **Посмотри секции**:
   - "🔑 Ключевые абстракции" — назначение классов/интерфейсов
   - "💡 Типичные сценарии" — примеры использования
   - "📌 Важные детали" — особенности реализации

### Я не знаю, где искать нужный код

1. **Посмотри "Расположение в кодовой базе"** в документации слоя
2. **Проверь таблицы компонентов** — там указаны файлы и классы
3. **Используй секцию "🔄 Взаимодействие"** — связи с другими слоями

## 🔧 Maintenance

### Когда обновлять документацию?

- ✅ Добавил новый интерфейс/класс → обнови таблицу "Ключевые абстракции"
- ✅ Изменил способ расширения → обнови секцию "Как расширять"
- ✅ Обнаружил частую ошибку → добавь в "Частые ошибки"
- ✅ Рефакторинг архитектуры → обнови весь документ слоя

### Шаблон

Для создания новой документации используй [TEMPLATE.md](TEMPLATE.md)

---

**Совет**: Держи эту документацию актуальной! Лучше потратить 5 минут на обновление документа, чем 30 минут на вспоминание через месяц.
