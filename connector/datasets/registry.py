from __future__ import annotations

from connector.datasets.spec import DatasetSpec
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
