# connector/domain/target_dsl

## Назначение

DSL конфигурации целевой системы. Описывает операции, схемы запросов, политики retry и fault-handling декларативно в YAML.

## Файлы

| Файл | Назначение |
|---|---|
| `specs.py` / `spec_models.py` | Pydantic-модели: `TargetSpec`, `OperationSpec`, `HealthSpec`, `FaultRule`, `RetryRule`, `RetryConfig` |
| `loader.py` | Загрузка YAML target-спек из `datasets/registry.yaml` |

## Зависимости

**Зависит от:** `pydantic`.  
**Используется:** `infra/target/core/kernel.py`, `infra/target/core/gateway.py`, `delivery/cli/containers.py`.
