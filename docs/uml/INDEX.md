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

3. `pipeline/`
- `cli_layer/`
- `diagnostic_layer/`
- `report_layer/`

4. `config/`
- итоговая модель settings, загрузка, границы и contracts.

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
