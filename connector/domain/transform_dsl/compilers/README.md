# connector/domain/transform_dsl/compilers

## Назначение

Компиляторы DSL-спек в runtime-объекты стадий пайплайна. Каждый компилятор принимает `*Spec` → возвращает сконфигурированный объект ядра стадии.

## Файлы

| Файл | Что компилирует |
|---|---|
| `canonicalization.py` | `CanonicalizationSpec` → `CompiledCanonicalizerPlan` для shared comparison/lookups runtime |
| `mapping.py` | `MappingSpec` → `MapperCore` |
| `normalize.py` | `NormalizeSpec` → `NormalizerEngine` |
| `enrich.py` | `EnrichSpec` → `EnricherCore` (с `ProviderGateway`, `SecretProvider`); provider-level canonicalization компилируется через shared canonicalization DSL |
| `match.py` | `MatchSpec` → `MatchEngine` |
| `resolve.py` | `ResolveSpec` → `ResolveEngine` |
| `topology.py` | `TopologySpec` → `CompiledTopologyCanonicalizerPlan`, который строится поверх shared canonicalization layer из `domain/transform/common/` и затем может исполняться через Python runtime или infra-level Polars adapter |

## Зависимости

**Зависит от:** `domain/transform_dsl/specs/`, `domain/transform/` (все ядра стадий), `domain/dsl/engine.py`.  
**Используется:** `datasets/yaml_spec.py` через `DatasetSpec.build_spec_for(stage_type)`.

## Правило

Компилятор не запускает трансформацию — только конструирует объект. Не должен бросать ошибки времени выполнения: все валидации — при компиляции.
