from connector.domain.diagnostics.catalog import CatalogEntry, ErrorCatalog, build_catalog
from connector.domain.diagnostics.core_catalog import build_core_catalog
from connector.domain.diagnostics.context import DiagnosticContext, configure, error, warning
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.exceptions import OperationError, UnknownDiagnosticCodeError
from connector.domain.diagnostics.factory import DiagnosticFactory
from connector.domain.diagnostics.policies import (
    ExitCodePolicy,
    RetryPolicy,
    StopPolicy,
    SystemErrorCode,
    default_exit_policy,
    default_retry_policy,
    default_stop_policy,
)

__all__ = [
    "CatalogEntry",
    "ErrorCatalog",
    "build_catalog",
    "build_core_catalog",
    "OperationError",
    "UnknownDiagnosticCodeError",
    "DiagnosticFactory",
    "DiagnosticContext",
    "configure",
    "error",
    "warning",
    "SystemErrorCode",
    "CommandResult",
    "RetryPolicy",
    "StopPolicy",
    "ExitCodePolicy",
    "default_exit_policy",
    "default_retry_policy",
    "default_stop_policy",
]
