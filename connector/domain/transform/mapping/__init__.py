"""
Назначение:
    Пакет mapping-логики (DSL mapper + core).
"""

from connector.domain.transform.mapping.mapper_core import MapperCore
from connector.domain.transform.mapping.mapper_dsl import MapperDsl
from connector.domain.transform.mapping.mapper_engine import MapperEngine

__all__ = ["MapperCore", "MapperDsl", "MapperEngine"]
