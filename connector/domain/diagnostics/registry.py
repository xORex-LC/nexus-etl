from __future__ import annotations

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.core_catalog import build_core_catalog
from connector.datasets.registry import get_spec


def build_catalog(dataset: str | None, *, strict: bool) -> ErrorCatalog:
    """
    Назначение:
        Собрать итоговый каталог диагностик (core + dataset).

    Контракт:
        - dataset=None -> только core каталог.
        - dataset указан -> core + dataset catalog.
        - strict режим применяется единообразно.

    Ошибки/исключения:
        - ValueError при конфликте кодов (on_conflict=error).
    """
    core = build_core_catalog(strict=strict)
    if dataset is None:
        return core
    spec = get_spec(dataset)
    dataset_catalog = spec.get_diagnostic_catalog(strict=strict)
    return core.merge(dataset_catalog, on_conflict="error")


__all__ = ["build_catalog"]
