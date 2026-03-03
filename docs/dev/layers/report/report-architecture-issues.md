# Report Layer — Реестр Архитектурных Проблем

> Назначение: единый backlog проблем report-слоя (архитектура, SOLID, SRP, data abstraction) для поэтапного разбора.

## Статусы

- `OPEN` — проблема зафиксирована, решение не начато.
- `IN_PROGRESS` — идёт проработка/рефакторинг.
- `DONE` — проблема закрыта и проверена тестами.

## Реестр

| ID | Уровень границы | Проблема | Нарушение | Где в коде | Риск | Приоритет | Первый шаг разбора | Статус |
|----|------------------|----------|-----------|------------|------|-----------|--------------------|--------|
| RPT-001 | Layer | `exit code` и `report.status` могут расходиться (ошибка есть, отчёт `SUCCESS`) | Consistency, SRP | `connector/delivery/cli/runtime.py` (`_apply_cli_result_to_report`, `_exit_code_from_result`) | Неверный мониторинг и пост-анализ инцидентов | P0 | Унифицировать контракт результата команды и обязательное отражение фатальных кодов в отчёте | DONE |
| RPT-002 | Class/Method | `ReportCollector._derive_status()` игнорирует `rows_blocked` и опирается только на `errors_total/rows_passed` | Data abstraction, correctness | `connector/domain/reporting/collector.py` (`_derive_status`) | `FAILED` строки могут привести к `SUCCESS` | P0 | Определить целевую формулу статуса на основе `rows_blocked` + системных кодов | DONE |
| RPT-003 | Layer | Часть runtime-исключений не материализуется в `items.diagnostics` | SRP, observability boundaries | `connector/delivery/cli/runtime.py` (`except RuntimeErrorWithCode`, `except Exception`, init/shutdown paths) | Потеря причин падения в report JSON | P0 | Ввести единый runtime error presenter в report | DONE |
| RPT-004 | Method | `items_truncated` не отражает усечение для `SKIPPED` и других статусов вне `OK/FAILED` | Correctness | `connector/domain/reporting/collector.py` (`add_item`) | Тихая потеря данных при лимите `items_limit` | P1 | Делать truncate-флаг независимым от статуса item (см. `REPORT-DEC-007`) | DONE |
| RPT-005 | Class boundary | `ApplyReportPresenter` напрямую мутирует `collector.summary/items/status`, обходя API коллектора | Data abstraction, encapsulation | `connector/delivery/presenters/apply_report_presenter.py` | Нарушение инвариантов `ReportCollector` | P1 | Ограничить запись в collector через `ReportWritePort` (см. `REPORT-DEC-003`) | DONE |
| RPT-006 | Class/Method | В `ApplyReportPresenter` продублирован подсчёт diagnostics и summary-агрегатов | SRP, DRY | `connector/delivery/presenters/apply_report_presenter.py` | Расхождение агрегатов между сценариями | P1 | Вынести apply-агрегацию в canonical adapter/presenter path (см. `REPORT-DEC-003`) | DONE |
| RPT-007 | Module | `runtime.py` — перегруженный orchestrator (логирование, DI lifecycle, error policy, report write, adapter logic) | SRP | `connector/delivery/cli/runtime.py` | Сложность изменений и высокая цена регрессий | P1 | Декомпозировать runtime orchestration и boundaries (см. `REPORT-DEC-005`) | DONE |
| RPT-008 | Class/Method | `TransformResultProcessor.process()` и `PlanningResultProcessor.process()` перегружены и частично дублируются | SRP, OCP | `connector/domain/transform/core/result_processor.py` | Трудная поддержка и ошибки при изменении правил отчётности | P1 | Единый `StageResultReporter` через composition/strategy (см. `REPORT-DEC-002`) | DONE |
| RPT-009 | Scenario boundary | Разная стратегия upstream ошибок в `match` и `resolve` приводит к несопоставимым отчётам | Responsibility boundaries | `connector/usecases/match_usecase.py`, `connector/usecases/resolve_usecase.py` | Сложно сравнивать quality-метрики стадий | P1 | Stage-only policy и unified processing contract (см. `REPORT-DEC-002`) | DONE |
| RPT-010 | Layer | Повторная установка `dataset/items_limit` в runtime, handler и usecase | SRP | `connector/delivery/cli/runtime.py`, `connector/delivery/commands/*`, `connector/usecases/*` | Скрытые конфликты настроек и дублирование | P2 | Зафиксировать owner policy для `ReportMeta` (см. `REPORT-DEC-006`) | DONE |
| RPT-011 | Layer boundary | Зафиксированный техдолг: usecases импортируют infra logging | Clean architecture boundary | `connector/usecases/cache_command_service.py`, `connector/usecases/cache_refresh_service.py` | Усиление связности usecase ↔ infra | P2 | Вынести логирование на delivery/application boundary | OPEN |
| RPT-012 | Layer | Две модели результата команды (`domain.CommandResult` и `delivery.cli.CommandResult`) | Abstraction inconsistency | `connector/domain/diagnostics/command_result.py`, `connector/delivery/cli/result.py` | Неявное поведение и дефекты маппинга в report | P1 | Канонический `DomainCommandResult` + boundary adapter (см. `REPORT-DEC-004`, `REPORT-DEC-005`) | DONE |
| RPT-013 | Model semantics | `meta.dataset` может устанавливаться для dataset-agnostic команд | Data semantics | `connector/delivery/cli/runtime.py` (`_resolve_dataset_opt`) | Шум и ложные допущения в отчётах | P2 | Убрать runtime fallback dataset, owner = dataset-aware handler (см. `REPORT-DEC-006`) | DONE |
| RPT-014 | Module/API | `context` и `summary.ops` основаны на магических строках без typed schema | Data abstraction | `connector/domain/reporting/*`, `connector/delivery/commands/*`, `connector/usecases/*` | Ломкость интеграций при эволюции структуры | P1 | Ввести typed schema v2 и контрактные ключи (см. `REPORT-DEC-007`) | DONE |
| RPT-015 | Class | `ReportCollector.build()` возвращает живые mutable ссылки, не snapshot-копию | Encapsulation | `connector/domain/reporting/collector.py` (`build`) | Непредсказуемая мутация уже собранного envelope | P2 | Возвращать snapshot/deep-copy из `build()` (см. `REPORT-DEC-003`) | DONE |
| RPT-016 | Delivery contract | Опция `--report-include-skipped` объявлена, но не подключена к execution path | API contract consistency | `connector/delivery/cli/app.py` (`import plan` options) | Неверные ожидания пользователей CLI | P2 | Полный wiring + skipped-reporting contract (см. `REPORT-DEC-007`) | DONE |
| RPT-017 | Model semantics | Принудительная нормализация `line_no=None -> 0` в apply report | Data semantics | `connector/delivery/presenters/apply_report_presenter.py` | Потеря различия между "unknown" и "real zero" | P2 | `RowRef.line_no: int | None` и запрет coercion в presenter (см. `REPORT-DEC-007`) | DONE |
| RPT-018 | Delivery runtime | Dispatch handler через `inspect.signature` создаёт хрупкий неявный контракт | SRP, robustness | `connector/delivery/cli/runtime.py` (`_call_handler`) | Риски при рефакторинге сигнатур handlers | P2 | Явный handler interface без reflection dispatch (см. `REPORT-DEC-005`) | DONE |
| RPT-019 | Policy contract | `ReportPolicy` уровни `minimal/standard/debug` не формализованы как capability-контракт | Data abstraction, contract stability | `connector/domain/reporting/assembler.py`, `connector/domain/reporting/policy.py` (target) | Непредсказуемая детализация отчёта между сценариями | P2 | Зафиксировать capability-based policy + presets matrix (см. `REPORT-DEC-008`) | DONE |

## Порядок поэтапного разбора

1. Сначала закрыть `P0`: `RPT-001`, `RPT-002`, `RPT-003`.
2. Затем стабилизировать архитектурные границы `P1`: `RPT-005`, `RPT-006`, `RPT-007`, `RPT-008`, `RPT-009`, `RPT-012`, `RPT-014`.
3. После этого добрать `P2` и API/semantics-хвосты.

## Журнал изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 2026-03-01 | Создан реестр архитектурных проблем report-слоя | xORex-LC |
| 2026-03-01 | Закрыты `RPT-001..003`: единый runtime result->report mapping, materialization runtime ошибок, новая формула `_derive_status()` по `rows_blocked/rows_passed` | xORex-LC |
| 2026-03-02 | Добавлен ADR-пакет `REPORT-PROBLEM/DEC-005..007` для закрытия хвостов `RPT-004`, `RPT-007`, `RPT-010`, `RPT-013`, `RPT-014`, `RPT-016`, `RPT-017`, `RPT-018` | xORex-LC |
| 2026-03-02 | Уточнён `REPORT-DEC-001` (single public sink API, hybrid tracing rule, lifecycle через `run_with_report` на первом этапе), добавлен ADR-пакет `REPORT-PROBLEM/DEC-008` по формализации `ReportPolicy` | xORex-LC |
| 2026-03-02 | Закрыт этап `DEC-003`: введён `ReportWritePort`, `ApplyReportPresenter` переведён на API collector без direct mutation, `ReportCollector.build()` возвращает snapshot (`RPT-005/006/015`) | xORex-LC |
| 2026-03-02 | Закрыт этап `DEC-002`: введён canonical `StageResultReporter` (+ strategy/sanitizer/stats/resolver), usecase переведены на resolver, legacy `TransformResultProcessor/PlanningResultProcessor` оставлены как thin alias (`RPT-008/009`) | xORex-LC |
| 2026-03-02 | Закрыт этап `DEC-007`: внедрён schema v2 (`schema_version=2.0`, `SKIPPED`, `rows_skipped`, nullable `RowRef.line_no`), добавлены typed contracts для `context/ops`, подключён `import plan --report-include-skipped` по формуле capability AND CLI (`RPT-004/014/016/017`) | xORex-LC |
| 2026-03-02 | Закрыт этап `Post-Window Cleanup`: удалены legacy compatibility windows (`Transform/PlanningResultProcessor`, `CliCommandResult/int`, `ReportWritePort bridge`, `report_writer`), runtime и продюсеры переведены на `IReportSink.emit(...)`; добавлены архитектурные guard-тесты (`RPT-007/010/012/013/018/019`) | xORex-LC |
