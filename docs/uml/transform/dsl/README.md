# Transform DSL UML

Диаграммы в каталоге показывают **dsl-core** (`connector/domain/dsl/*`) как общий слой.

## Основные диаграммы

- `dsl_class.puml` — классы и контракты dsl-core + интеграционные точки stage DSL.
- `dsl_architecture.puml` — компонентная схема: YAML -> loader/specs/options -> stage-specific DSL -> runtime.
- `dsl_core_activity_compile.puml` — алгоритм компиляции DSL (parse/validate/merge/compile/error).
- `dsl_core_sequence_stage_handshake.puml` — последовательность инициализации стадии через dsl-core.
- `dsl_core_errors_sequence.puml` — путь распространения DSL-ошибок в `DiagnosticItem`.
- `dsl_core_options_merge_activity.puml` — merge-цепочка build options.
- `dsl_core_registry_map.puml` — карта реестра операций и его потребителей.

## Границы

- Stage-specific DSL (`mapper_dsl`, `normalizer_dsl`, `enricher_dsl`, `match_dsl`, `resolve_dsl`, `cache_dsl`) отмечены как **integration points**.
- Бизнес-логика stage core намеренно не детализируется в этом наборе диаграмм.
