# DSL-PROBLEM-003: DSL Core смешивает generic инфраструктуру с layer-специфичным кодом

> **Статус**: Решена в [DSL-DEC-003](./DSL-DEC-003-per-layer-dsl-modules.md)
> **Дата создания**: 2026-02-17
> **Затронутые компоненты**: `connector/domain/dsl/specs/*`, `connector/domain/dsl/loader/*`, `connector/domain/dsl/build_options.py`, `connector/domain/dsl/__init__.py`
> **Созависимая проблема**: [DSL-PROBLEM-004](./DSL-PROBLEM-004-inconsistent-transform-compile-architecture.md)

---

## 📋 Контекст

После DSL-DEC-002 (модульная декомпозиция и стабилизация контрактов) DSL Core получил
внутреннее разделение на `specs/transform.py`, `specs/cache.py`, `loader/transform.py`,
`loader/cache.py`. Это улучшило структуру, но разделение осталось **внутри одного модуля**.

Параллельно был реализован `connector/domain/target_dsl/` (TARGET-DEC-004), который показал
чистый паттерн: отдельный per-layer DSL модуль, опирающийся на generic инструменты dsl-core.
Это выявило контраст с тем, как организованы transform и cache DSL — они по-прежнему живут
внутри `connector/domain/dsl/`.

---

## ⚠️ Проблема

`connector/domain/dsl/` де-факто является не "DSL Core", а монолитом, содержащим:

1. **Generic DSL инфраструктуру** (используется всеми layer DSL):
   - `DslBaseModel`, `OperationCall` (specs/_base.py)
   - `DslLoadError`, `DslIssue`, `DslSeverity` (issues.py)
   - `TransformationEngine`, `OperationRegistry`, ops (engine.py, registry.py, ops.py)
   - Generic loader utils: `read_yaml`, `find_repo_root`, `load_registry`, `validate_spec` (loader/_common.py)
   - `BaseDslBuildOptions`, `build_options_from_mapping` (build_options.py)
   - `diagnostics.py`, `helpers.py`

2. **Transform-специфичные артефакты**:
   - `MappingSpec`, `EnrichSpec`, `ResolveSpec` и ещё ~40 моделей (specs/transform.py, 660+ строк)
   - Transform loaders: `load_mapping_spec_for_dataset()` и ещё ~15 функций (loader/transform.py)
   - `_resolve_dataset_path()`, `_load_dataset_stage_spec()` в _common.py — знают о структуре `registry.datasets.{name}.{stage}`
   - Per-stage build options: `MapDslBuildOptions`, `EnrichDslBuildOptions` и т.д.

3. **Cache-специфичные артефакты**:
   - `CacheRegistrySpec`, `CacheDatasetSpec`, `CacheSyncSpec` и ~15 моделей (specs/cache.py, 316 строк)
   - Cache loaders: `load_cache_registry_spec()` и т.д. (loader/cache.py)
   - `CacheDslBuildOptions`

---

## 🔍 Симптомы

- **Симптом 1**: `dsl/__init__.py` экспортирует ~80+ символов разом — specs, loaders, build options, engine, registry. Потребитель не может импортировать только generic инструменты без утаскивания transform/cache графа зависимостей.
- **Симптом 2**: `target_dsl/` — чистый per-layer модуль с 2 файлами. Transform DSL и Cache DSL — внутри монолита dsl/ с ~15 файлами. Архитектурная асимметрия.
- **Симптом 3**: `_common.py` содержит и generic (`_read_yaml`, `_repo_root`), и transform-специфичные (`_resolve_dataset_path`, `_load_dataset_stage_spec`) функции в одном файле.
- **Симптом 4**: добавление нового layer DSL (например, для нового ETL процесса) требует правки `dsl/` — модуля, который должен быть стабильным фундаментом.
- **Симптом 5**: `DSL-DEC-002` зафиксировала в ограничениях: "Публичный фасад `connector.domain.dsl.__init__` остаётся широким и требует дальнейшей рационализации API."

---

## 📊 Масштаб проблемы

- **Частота**: Постоянно — каждый новый layer DSL усугубляет смешение.
- **Критичность**: Высокая — блокирует масштабирование DSL-системы на новые ETL процессы.
- **Затронуто**: Все потребители DSL (transform stages, cache_core, dataset specs, CLI runtime), будущие per-layer DSL модули.

---

## 🧪 Как воспроизвести

1. Попытаться создать DSL для нового ETL слоя (аналогично target_dsl).
2. Обнаружить, что generic инструменты (`read_yaml`, `load_registry`, `validate_spec`, `DslBaseModel`) доступны через `connector.domain.dsl`, но импорт утаскивает всю transform/cache специфику.
3. Обнаружить, что `_resolve_dataset_path` в `_common.py` жёстко привязана к структуре `datasets.{name}.{stage}` — непригодна для нового слоя.
4. **Ожидаемый результат**: dsl-core предоставляет чистый toolkit, layer DSL строит на нём свою специфику.
5. **Фактический результат**: dsl-core = monolith, приходится либо добавлять в него ещё одну зону, либо дублировать generic утилиты.

---

## 🚫 Почему это проблема?

- Нарушает Single Responsibility: один модуль отвечает за generic infra + 2 layer-специфики.
- Нарушает Open/Closed: расширение DSL на новые слои требует модификации «фундамента».
- `target_dsl/` показал, что чистый per-layer подход работает — отсутствие его для transform/cache — это архитектурный долг.
- DSL-DEC-002 частично разделила внутреннюю структуру, но не завершила разделение до уровня модулей.

---

## 💡 Возможные решения (обсуждение)

### Вариант 1: Извлечь per-layer DSL модули (transform_dsl/, cache_dsl/)
- **Идея**: Вынести transform specs/loaders/build_options в `connector/domain/transform_dsl/`, cache — в `connector/domain/cache_dsl/`. В `dsl/` остаётся только generic инфраструктура.
- **Плюсы**: Единообразие с target_dsl, чистый dsl-core, стрелки зависимостей идут только вниз.
- **Минусы**: Массовое обновление импортов по проекту (~20+ файлов), необходимость решить судьбу `*_dsl` компиляторов в transform стейджах (→ DSL-PROBLEM-004).

### Вариант 2: Подпапки внутри dsl/ без выноса в отдельные модули
- **Идея**: `dsl/specs/transform/`, `dsl/specs/cache/`, `dsl/loader/transform/` — внутренняя реорганизация.
- **Плюсы**: Минимальное изменение import paths.
- **Минусы**: Не решает root cause: dsl/ остаётся единым модулем, ответственным за всё.

### Вариант 3: Только slim-down `__init__.py`, разделение через re-exports
- **Идея**: `dsl.__init__` экспортирует только generic API. Transform/cache доступны через `dsl.specs.transform`, `dsl.loader.transform`.
- **Плюсы**: Без перемещения файлов.
- **Минусы**: Половинчатое решение — файлы всё ещё в одном пакете, зависимости не разделены.

---

## 🔗 Связанные документы

- [DSL-DEC-002](./DSL-DEC-002-modular-dsl-core-and-contract-stabilization.md) — предыдущее решение (зафиксировало ограничение широкого фасада)
- [TARGET-DEC-004](../target/TARGET-DEC-004-target-dsl-declarative-provider.md) — эталонный per-layer DSL модуль
- [DSL-PROBLEM-004](./DSL-PROBLEM-004-inconsistent-transform-compile-architecture.md) — созависимая проблема
- [DSL-DEC-003](./DSL-DEC-003-per-layer-dsl-modules.md) — решение

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-02-17 | Проблема зафиксирована после анализа асимметрии target_dsl vs dsl/ |
| 2026-02-17 | Решение принято в DSL-DEC-003 |
