# Settings UML

Диаграммы фиксируют итоговую модель settings-рефактора (фазы 5-7).

## Диаграммы

1. `settings_component.puml` — компонентная схема settings-потока и точек использования slices.
2. `settings_sequence_load.puml` — последовательность загрузки/валидации настроек и error-path.
3. `settings_class.puml` — класс-диаграмма `AppSettings`, slices и загрузочного контракта.
4. `settings_boundary.puml` — архитектурные границы: где разрешён полный `AppSettings`, где только slices.

## Экспорт

```bash
plantuml -tpng docs/uml/config/*.puml
```
