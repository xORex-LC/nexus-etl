from __future__ import annotations

from connector.datasets.spec import DatasetSpec
from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.datasets.employees.spec import make_employees_spec

_registry: dict[str, callable] = {"employees": make_employees_spec}

def get_spec(dataset: str, secrets: SecretProviderProtocol | None = None) -> DatasetSpec:
    """
    Возвращает DatasetSpec по имени или ValueError, если не зарегистрирован.
    """
    try:
        factory = _registry[dataset]
        return factory(secrets=secrets)
    except KeyError as exc:
        raise ValueError(f"Unsupported dataset: {dataset}") from exc


def list_specs(secrets: SecretProviderProtocol | None = None) -> list[DatasetSpec]:
    return [factory(secrets=secrets) for factory in _registry.values()]


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
        resolve_spec = spec.build_resolve_spec()
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
