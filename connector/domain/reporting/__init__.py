"""
Назначение:
    Доменные объекты и сборщик отчётов.
"""

from connector.domain.reporting.assembler import CompositeReportEnricher, ReportAssembler
from connector.domain.reporting.bridge import ReportWritePortBridge
from connector.domain.reporting.context import IReportContext, InMemoryReportContext
from connector.domain.reporting.sink import IActivitySink, IReportSink, NullActivitySink, ReportSink
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
    "ReportPolicy",
    "ReportPolicyCapabilities",
    "ReportPolicyProfile",
    "ReportAssembler",
    "ReportSink",
    "ReportWritePortBridge",
    "resolve_report_policy",
]
