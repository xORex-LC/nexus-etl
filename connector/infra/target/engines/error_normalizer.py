"""
Совместимый вход в error-normalizer target-core (legacy import path).
"""

from __future__ import annotations

from connector.infra.target.core.engines.error_normalizer import (
    NormalizedFault,
    TargetErrorNormalizer,
)

__all__ = ["NormalizedFault", "TargetErrorNormalizer"]
