# connector/domain/transform_dsl/specs

## Назначение

Pydantic-модели DSL-правил для каждой стадии пайплайна. Загружаются из YAML-файлов датасета и валидируются при старте.

## Файлы

| Файл | Ключевые модели |
|---|---|
| `mapping.py` | `MappingSpec`, `MappingRule` (source/targets/ops/on_error), `MetaRule`, `MappingSchema` |
| `normalize.py` | `NormalizeSpec`, `NormalizeRule` (field/ops/on_error) |
| `enrich.py` | `EnrichSpec`, `EnrichRule` (build/when/then/provider/merge/on_conflict/run_when_errors), `EnrichBlock`, `SecretsSpec` |
| `match.py` | `MatchSpec`, `MatchBlock`, `IdentityRule`, `SourceDedupPolicy`, `FuzzyMatchPolicy`; topology policy подключается через `MatchBlock.topology` |
| `resolve.py` | `ResolveSpec`, `ResolveDesiredStateSpec`, `ResolveDiffSpec`, `ResolveMergeSpec`, `ResolveSecretsSpec`; topology-link policy подключается через `ResolveBlock.topology_link` |
| `sink.py` | `SinkSpec`, `SinkFieldSpec` (type/nullable/required/serialize), `SinkBoolLiteralMapSpec` |
| `source.py` | `SourceSpec` — описание CSV-источника |
| `topology.py` | `TopologySpec`, canonicalization whitelist ops, source/target topology contracts, `MatchTopologyPolicySpec`, `ResolveTopologyLinkSpec` |
| `validate.py` | `ValidateSpec` — правила валидации |

## Зависимости

**Зависит от:** `domain/dsl/specs/`, `pydantic`.  
**Используется:** `domain/transform_dsl/compilers/`, `datasets/yaml_spec.py`.
