"""HTTP-модели операций транспорта (совместимый alias на текущую модель)."""

from __future__ import annotations

from connector.infra.target.core.spec_models import HttpOperationData

HttpOperationDataModel = HttpOperationData

__all__ = ["HttpOperationDataModel"]
