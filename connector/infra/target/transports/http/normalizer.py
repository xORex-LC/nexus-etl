"""HTTP normalizer (совместимый alias на текущий error normalizer)."""

from __future__ import annotations

from connector.infra.target.core.engines.error_normalizer import (
    NormalizedFault,
    TargetErrorNormalizer,
)

__all__ = ["NormalizedFault", "TargetErrorNormalizer"]
