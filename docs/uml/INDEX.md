# UML Index

Этот индекс — единая точка входа для UML-диаграмм проекта.

## Каталоги

1. `cache/`
- `core/` — доменные сценарии кэша (refresh/status/clear, pending lifecycle, runtime роли).
- `infra/` — инфраструктурная реализация gateway/handlers/backends.

2. `transform/`
- `mapper/`
- `normalize/`
- `enricher/`
- `matcher/`
- `resolver/`
- `dsl/` — общий dsl-core и точки интеграции со stage DSL.
  - `dsl_class.*` — классы и контракты DSL core (с учётом split `specs/*`, `loader/*`).
  - `dsl_architecture.*` — архитектура YAML→loader/specs/options→stage DSL.
  - `dsl_core_activity_compile.*` — activity загрузки/валидации/компиляции.
  - `dsl_core_options_merge_activity.*` — merge build options (+ strict/ambiguous ветки).
  - `dsl_core_sequence_stage_handshake.*` — последовательность инициализации стадии.
  - `dsl_core_errors_sequence.*` — распространение DslIssue/DslLoadError в diagnostics.
  - `dsl_core_registry_map.*` — карта OperationRegistry и потребителей.

3. `pipeline/`
- `cli_layer/`
- `diagnostic_layer/`
- `report_layer/`

4. `config/`
- итоговая модель settings, загрузка, границы и contracts.

5. `vault/`
- `management/` — lifecycle `vault-management` (class/sequence/activity/state machine):
  manual rotate protocol, maintenance flow, metadata states, startup touchpoints.

## Правила размещения

1. Для каждой предметной области используем отдельный каталог.
2. Форматы файлов:
- исходник: `*.puml`
- экспорт: `*.png` (с тем же basename)
3. Имена диаграмм:
- `<domain>_class.puml`
- `<domain>_sequence.puml`
- `<domain>_activity.puml`
- `<domain>_state_machine.puml`
- при необходимости: `<domain>_component.puml`, `<domain>_boundary.puml`.

## Стиль и шаблон

1. Канонический стиль описан в `docs/uml/TEMPLATE_STYLE.md`.
2. При создании новых диаграмм сначала копируй шаблон из этого файла, затем наполняй содержимым.

## Экспорт

Локально:

```bash
plantuml -tpng docs/uml/**/**/*.puml
```

Точечно:

```bash
plantuml -tpng docs/uml/config/*.puml
plantuml -tpng docs/uml/transform/dsl/*.puml
```
