# CONFIG-DEC-001: Модульный Settings и slice-based wiring

> **Статус**: Принято / реализовано  
> **Дата решения**: 2026-02-12  
> **Связанная проблема**: [CONFIG-PROBLEM-001](./CONFIG-PROBLEM-001-settings-layer-complexity.md)

## Контекст

Старый конфигурационный слой был перегружен:
1. Плоская модель `Settings` с большим числом несвязанных параметров.
2. Ручной merge в нескольких местах.
3. Риск потери валидных значений (`0/False`) и неочевидных fallback.
4. Протекание полного settings-объекта в команды/use-cases.

## Принятое решение

1. Введена модульная модель `AppSettings` + профильные slices (`ApiSettings`, `PathsSettings`, `DatasetSettings`, `ObservabilitySettings`, `ExecutionSettings`, `RefreshSettings`, `MatchingRuntimeSettings`, `PendingSettings`).
2. Канонический вход в конфигурацию: `load_app_settings(...)`.
3. Полный `AppSettings` разрешён только в composition root (`delivery/cli/app.py`); в команды/use-cases передаются только нужные slices.
4. Для ошибок настроек используется типизированный контракт (`SettingsLoadError/*`) + трансляция в `DiagnosticItem`.
5. Добавлены архитектурные guardrails тестами (запрет legacy API и неверных границ).

## Как реализовано (кратко)

1. Production path переведён на `load_app_settings(...)`.
2. Legacy-path `loadSettings` и `from_legacy` убран из production use-path.
3. Runtime/commands/bootstrap/use-cases переключены на slice-wiring.
4. Тестовая матрица: unit + integration + architecture + CLI smoke.

## Плюсы

1. Чёткие границы: каждый слой получает только нужную часть конфигурации.
2. Проще добавлять новые параметры и сопровождать wiring.
3. Детерминированная обработка config-ошибок.
4. Архитектурные тесты защищают от возврата к legacy-подходу.

## Минусы и компромиссы

1. Увеличилось число DTO-классов настроек.
2. Требуется поддерживать mapping полей между плоской моделью и slices.
3. Строже требования к тестам и дисциплине границ.

## Риски

1. Регрессии при добавлении новых параметров без обновления slice-мэппинга.
2. Нарушение границ при прямом доступе к полному settings-объекту в новых командах.

## Критерии успеха (выполнено)

1. В production path нет legacy-конфигурационного API.
2. Commands/use-cases не принимают полный `Settings`.
3. Целевой набор тестов по config/wiring/guardrails зелёный.

## Связанные материалы

1. [CONFIG-PROBLEM-001](./CONFIG-PROBLEM-001-settings-layer-complexity.md)
2. `tests/architecture/config/test_settings_boundaries.py`
3. `connector/config/app_settings.py`
4. `connector/delivery/cli/app.py`

## История

| Дата | Событие |
|------|---------|
| 2026-02-12 | Решение зафиксировано |
| 2026-02-12 | Решение реализовано и переведено в статус `Принято / реализовано` |
