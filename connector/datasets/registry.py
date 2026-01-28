from __future__ import annotations

from connector.datasets.spec import DatasetSpec
from connector.domain.planning.rules import LinkRules
from connector.domain.ports.secrets import SecretProviderProtocol
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
        rules: LinkRules = spec.build_link_rules()
        for field_rule in rules.fields:
            dataset = field_rule.target_dataset
            if dataset in id_field_by_dataset and id_field_by_dataset[dataset] != field_rule.target_id_field:
                raise ValueError(
                    "conflicting target_id_field for dataset "
                    f"{dataset}: {id_field_by_dataset[dataset]} vs {field_rule.target_id_field}"
                )
            id_field_by_dataset.setdefault(dataset, field_rule.target_id_field)
            keys = keys_by_dataset.setdefault(dataset, set())
            keys.update(key_rule.name for key_rule in field_rule.resolve_keys)
            for dedup in field_rule.dedup_rules:
                keys.update(dedup)
    return keys_by_dataset, id_field_by_dataset
