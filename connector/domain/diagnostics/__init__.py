from connector.domain.diagnostics.catalog import CatalogEntry, ErrorCatalog, build_catalog
from connector.domain.diagnostics.core_catalog import build_core_catalog
from connector.domain.diagnostics.context import DiagnosticContext, configure, error, get_catalog, warning
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.exceptions import UnknownDiagnosticCodeError
from connector.domain.diagnostics.catalog import build_error, build_warning
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
    "UnknownDiagnosticCodeError",
    "DiagnosticContext",
    "configure",
    "error",
    "get_catalog",
    "warning",
    "build_error",
    "build_warning",
    "SystemErrorCode",
    "CommandResult",
    "RetryPolicy",
    "StopPolicy",
    "ExitCodePolicy",
    "default_exit_policy",
    "default_retry_policy",
    "default_stop_policy",
]
