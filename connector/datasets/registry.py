"""
Назначение:
    Реестр датасетов с auto-discovery из registry.yml.

Граница ответственности:
    - Owns: получение DatasetSpec по имени, список всех датасетов, identity index plan.
    - Does NOT: загрузка DSL-конфигурации (dataset_dsl.loader), сборка spec (yaml_spec).
"""

from __future__ import annotations

import importlib
from functools import partial
from typing import Callable

from connector.datasets.spec import DatasetSpec
from connector.domain.dsl.loader import load_registry
from connector.domain.ports.secrets.provider import SecretProviderProtocol


def _make_yaml_spec(
    dataset_name: str,
    secrets: SecretProviderProtocol | None = None,
) -> DatasetSpec:
    from connector.datasets.yaml_spec import YamlDatasetSpec
    from connector.domain.dataset_dsl.loader import load_dataset_dsl_spec

    dsl_spec = load_dataset_dsl_spec(dataset_name)
    return YamlDatasetSpec(dataset_name, dsl_spec, secrets)


def _import_spec_factory(spec_class_ref: str) -> Callable[..., DatasetSpec]:
    """
    Назначение:
        Импортировать фабрику DatasetSpec по строковой ссылке (escape hatch).

    Формат ref:
        "module.path:factory_function" или "module.path:ClassName"
    """
    module_path, _, attr_name = spec_class_ref.rpartition(":")
    if not module_path or not attr_name:
        raise ValueError(
            f"Invalid spec_class reference '{spec_class_ref}'. "
            f"Expected format: 'module.path:factory_or_class'"
        )
    module = importlib.import_module(module_path)
    factory = getattr(module, attr_name)
    return factory


def _build_registry() -> dict[str, Callable[..., DatasetSpec]]:
    """
    Назначение:
        Auto-discovery датасетов из registry.yml.
    """
    registry_data = load_registry()
    datasets = registry_data.get("datasets") or {}
    result: dict[str, Callable[..., DatasetSpec]] = {}
    for name, entry in datasets.items():
        spec_class_ref = entry.get("spec_class") if isinstance(entry, dict) else None
        if spec_class_ref:
            result[name] = _import_spec_factory(spec_class_ref)
        else:
            result[name] = partial(_make_yaml_spec, name)
    return result


_registry: dict[str, Callable[..., DatasetSpec]] | None = None


def _get_registry() -> dict[str, Callable[..., DatasetSpec]]:
    global _registry  # noqa: PLW0603
    if _registry is None:
        _registry = _build_registry()
    return _registry


def get_spec(dataset: str, secrets: SecretProviderProtocol | None = None) -> DatasetSpec:
    """
    Возвращает DatasetSpec по имени или ValueError, если не зарегистрирован.
    """
    registry = _get_registry()
    try:
        factory = registry[dataset]
        return factory(secrets=secrets)
    except KeyError as exc:
        raise ValueError(f"Unsupported dataset: {dataset}") from exc


def list_specs(secrets: SecretProviderProtocol | None = None) -> list[DatasetSpec]:
    registry = _get_registry()
    return [factory(secrets=secrets) for factory in registry.values()]


def validate_registry() -> None:
    """
    Назначение:
        Eagerly validate all dataset registrations (spec_class imports).
        Вызывается при старте, чтобы ошибки в spec_class обнаруживались сразу.
    """
    _get_registry()


def resolve_dataset_name(dataset: str | None, default: str) -> str:
    """
    Назначение:
        Определить имя датасета с учётом значения по умолчанию.
    """
    return dataset if dataset is not None else default


def build_identity_index_plan(
    secrets: SecretProviderProtocol | None = None,
) -> tuple[dict[str, set[str]], dict[str, str]]:
    """
    Возвращает:
        keys_by_dataset: какие ключи индексировать для identity_index (dataset -> set[key_name]).
        id_field_by_dataset: поле resolved_id для датасета (dataset -> field_name).
    """
    keys_by_dataset: dict[str, set[str]] = {}
    id_field_by_dataset: dict[str, str] = {}
    for spec in list_specs(secrets=secrets):
        resolve_spec = spec.build_spec_for("resolve")
        for link_spec in resolve_spec.resolve.links:
            dataset = link_spec.target_dataset
            if dataset in id_field_by_dataset and id_field_by_dataset[dataset] != link_spec.target_id_field:
                raise ValueError(
                    "conflicting target_id_field for dataset "
                    f"{dataset}: {id_field_by_dataset[dataset]} vs {link_spec.target_id_field}"
                )
            id_field_by_dataset.setdefault(dataset, link_spec.target_id_field)
            keys = keys_by_dataset.setdefault(dataset, set())
            keys.update(key_rule.name for key_rule in link_spec.resolve_keys)
            for dedup in link_spec.dedup_rules:
                keys.update(dedup)
    return keys_by_dataset, id_field_by_dataset
