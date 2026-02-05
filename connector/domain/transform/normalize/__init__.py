"""
Нормализация данных на основе DSL.
"""

from .normalizer import DslNormalizer

# Backward-compatible alias (to be removed after migration).
Normalizer = DslNormalizer

__all__ = ["DslNormalizer", "Normalizer"]
