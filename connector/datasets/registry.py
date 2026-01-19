from __future__ import annotations

from connector.datasets.spec import DatasetSpec
from connector.datasets.employees.spec import make_employees_spec

_registry: dict[str, callable] = {
    "employees": make_employees_spec,
}

def get_spec(dataset: str, *, conn) -> DatasetSpec:
    """
    Возвращает DatasetSpec по имени или ValueError, если не зарегистрирован.
    """
    try:
        factory = _registry[dataset]
        return factory(conn)
    except KeyError as exc:
        raise ValueError(f"Unsupported dataset: {dataset}") from exc
