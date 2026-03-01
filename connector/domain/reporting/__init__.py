"""
Назначение:
    Доменные объекты и сборщик отчётов.
"""

from connector.domain.reporting.assembler import CompositeReportEnricher, ReportAssembler
from connector.domain.reporting.context import IReportContext, InMemoryReportContext
from connector.domain.reporting.sink import (
    IActivitySink,
    IReportSink,
    NullActivitySink,
    NullReportSink,
    ReportSink,
)
from connector.domain.reporting.policy import (
    ReportPolicy,
    ReportPolicyCapabilities,
    ReportPolicyProfile,
    resolve_report_policy,
)

__all__ = [
    "CompositeReportEnricher",
    "IActivitySink",
    "IReportContext",
    "IReportSink",
    "InMemoryReportContext",
    "NullActivitySink",
    "NullReportSink",
    "ReportPolicy",
    "ReportPolicyCapabilities",
    "ReportPolicyProfile",
    "ReportAssembler",
    "ReportSink",
    "resolve_report_policy",
]
