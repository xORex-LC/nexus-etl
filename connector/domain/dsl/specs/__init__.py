"""
Назначение:
    DSL спецификации (public API).

    Transform-специфичные спеки — connector.domain.transform_dsl.specs.
    Cache-специфичные спеки — connector.domain.cache_dsl.specs.
"""

from connector.domain.dsl.specs._base import DslBaseModel, OperationCall
from connector.domain.dsl.specs.transform import SourceOpsBlock

__all__ = [
    "DslBaseModel",
    "OperationCall",
    "SourceOpsBlock",
]
