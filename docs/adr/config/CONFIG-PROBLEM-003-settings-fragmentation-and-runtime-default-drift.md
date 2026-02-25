# CONFIG-PROBLEM-003: Фрагментация контуров Settings и дрейф runtime-дефолтов

> **Статус**: Открыта
> **Дата создания**: 2026-02-24
> **Затронутые компоненты**: `connector/config/config.py`, `connector/config/app_settings.py`, `connector/delivery/cli/containers.py`, `connector/domain/transform/resolver/resolve_core.py`, `connector/delivery/commands/enrich.py`, `connector/delivery/commands/import_plan.py`, `connector/delivery/commands/import_apply.py`

---

## 📋 Контекст

После внедрения `AppSettings` и slice-based wiring (CONFIG-DEC-001) settings-слой стал заметно
более управляемым для CLI/app-контура. Одновременно в проекте началась forward-adoption миграция
на `Pydantic` для новых runtime-настроек (`SqliteSettings`, `DictionaryRuntimeSettings`).

На фоне этих улучшений проявилась новая архитектурная проблема: внутри приложения сформировались
несколько разных способов задания и преобразования настроек, которые выглядят похожими по имени
(`*Settings`), но имеют разную роль, источник данных и поведение по умолчанию.

---

## ⚠️ Проблема

В config-ландшафте приложения отсутствует целостная и явно зафиксированная модель
конфигурационных контуров. В результате:

- часть настроек проходит через канонический путь `CLI > ENV > config > defaults`
  (`Settings` -> `AppSettings` slices),
- часть runtime-настроек создаётся отдельно через `Pydantic BaseSettings` в DI composition root,
- часть доменных настроек (`ResolverSettings`, `VaultRolloutPolicySettings`) задаётся как value-object
  и дополнительно маппится вручную в delivery-слое,
- часть runtime-поведения использует скрытые fallback-дефолты внутри доменного кода.

Это создаёт расхождение между "где объявлены дефолты" и "что реально используется в runtime".

---

## 🔍 Симптомы

- **Симптом 1**: `load_app_settings(...)` является каноническим entrypoint для app/CLI-настроек, но
  `SqliteSettings` и `DictionaryRuntimeSettings` инстанциируются отдельно в `AppContainer`, минуя
  общий merge/source-trace путь.
- **Симптом 2**: `ResolveCore` допускает `settings=None` и использует собственные fallback-дефолты,
  которые могут отличаться от значений, заданных в центральном `Settings`.
- **Симптом 3**: Преобразование `VaultRolloutSettings -> VaultRolloutPolicySettings` дублируется
  в нескольких command handlers, что повышает риск drift при добавлении новых полей.
- **Симптом 4**: В публичном контуре термин `*Settings` используется для разных сущностей
  (config slices, runtime settings, domain policy value objects, component-local settings),
  но их таксономия не закреплена архитектурно.

---

## 📊 Масштаб проблемы

- **Частота**: Постоянно при сопровождении settings-слоя; в runtime проявляется выборочно
- **Критичность**: Высокая
- **Затронуто**: Config layer, DI composition root, resolver runtime, vault rollout wiring,
  будущая миграция `PipelineOrchestrator` и любые новые settings-контракты

---

## 🧪 Как воспроизвести

1. Открыть `connector/delivery/cli/app.py` и проследить канонический путь загрузки через
   `load_app_settings(config_path, cli_overrides)`.
2. Открыть `connector/delivery/cli/containers.py` и проверить, что `SqliteSettings` и
   `DictionaryRuntimeSettings` создаются отдельными `providers.Singleton(...)`.
3. Открыть `connector/domain/transform/resolver/resolve_core.py` и найти fallback-ветки при
   `ResolverSettings | None`.
4. Открыть `connector/delivery/commands/enrich.py`, `import_plan.py`, `import_apply.py` и сравнить
   повторяющиеся `_rollout_settings(...)`.
5. **Ожидаемый результат**: единый и явно описанный механизм для источников/дефолтов/адаптеров
   настроек, без скрытых runtime-fallback и дублирующих маппингов.
6. **Фактический результат**: несколько механизмов сосуществуют параллельно, а правила их
   применения не зафиксированы как единое архитектурное решение.

---

## 🚫 Почему это проблема?

- Размывается источник истины для дефолтов и приоритетов настроек.
- Усложняется ревью: одинаково выглядящие `*Settings` имеют разную семантику.
- Возрастает риск регрессий при добавлении новых полей (особенно в `vault_rollout` и runtime policy).
- Legacy/fallback-ветки в доменном runtime маскируют отсутствие корректного wiring вместо явного
  архитектурного контракта.
- Будущая миграция pipeline orchestration становится сложнее, потому что конфигурационные границы
  не полностью детерминированы.

---

## 💡 Возможные решения (обсуждение)

> Этот раздел может содержать первоначальные идеи до принятия финального решения

### Вариант 1: Оставить текущий split и только задокументировать исключения
- **Идея**: Сохранить текущие механизмы (`load_app_settings`, `BaseSettings`, domain value-objects)
  как есть и ограничиться комментариями/документацией.
- **Плюсы**: Минимум изменений в коде, не мешает текущим миграциям.
- **Минусы**: Не устраняет hidden defaults и дублирующие adapters; drift продолжит накапливаться.

### Вариант 2: Ввести явную таксономию settings-контуров и централизовать adapters/границы
- **Идея**: Формально разделить типы настроек по роли (app/runtime/domain/component),
  зафиксировать допустимые entrypoints и убрать скрытые fallback в пользу явного wiring/adapter-контракта.
- **Плюсы**: Снижает риск drift, делает миграции предсказуемыми, улучшает boundary-review.
- **Минусы**: Требует дополнительного архитектурного слоя (policy/adapters/tests) и поэтапной миграции.

---

## 🔗 Связанные документы

- [CONFIG-DEC-001](./CONFIG-DEC-001-modular-settings-and-slice-wiring.md)
- [CONFIG-PROBLEM-002](./CONFIG-PROBLEM-002-manual-settings-validation.md)
- [CONFIG-DEC-002](./CONFIG-DEC-002-pydantic-settings-migration.md)
- [CONFIG-DEC-003](./CONFIG-DEC-003-settings-taxonomy-and-boundary-adapters.md) (если решена)
- [ADR Index](../INDEX.md)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-24 | Проблема зафиксирована по результатам архитектурного обзора config/settings-слоя |

