"""
Назначение:
    DSL ядро: движок, операции, реестр, issues, base models.

    Transform-специфичные спеки, загрузчики и build options — connector.domain.transform_dsl.
    Cache-специфичные спеки, загрузчики и build options — connector.domain.cache_dsl.
"""

from connector.domain.dsl.engine import EngineResult, TransformationEngine
from connector.domain.dsl.issues import DslIssue, DslSeverity, DslLoadError
from connector.domain.dsl.specs._base import DslBaseModel, OperationCall
from connector.domain.dsl.build_options import BaseDslBuildOptions
from connector.domain.dsl.registry import OperationRegistry, register_core_ops

__all__ = [
    # Core engine
    "EngineResult",
    "TransformationEngine",
    # Base models
    "DslBaseModel",
    "OperationCall",
    # Issues
    "DslIssue",
    "DslSeverity",
    "DslLoadError",
    # Build options (generic base only)
    "BaseDslBuildOptions",
    # Registry
    "OperationRegistry",
    "register_core_ops",
]
