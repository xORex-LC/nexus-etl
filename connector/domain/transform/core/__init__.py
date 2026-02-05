"""Core data-transform primitives and helpers."""

from connector.domain.transform.core.result import TransformResult, TransformResultBuilder
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.core.iterators import iter_ok
from connector.domain.transform.core.result_processor import TransformResultProcessor, PlanningResultProcessor

__all__ = [
    "TransformResult",
    "TransformResultBuilder",
    "SourceRecord",
    "iter_ok",
    "TransformResultProcessor",
    "PlanningResultProcessor",
]
