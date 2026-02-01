from connector.domain.diagnostics.catalog import CatalogEntry, ErrorCatalog
from connector.domain.diagnostics.exceptions import OperationError, UnknownDiagnosticCodeError
from connector.domain.diagnostics.factory import DiagnosticFactory
from connector.domain.diagnostics.context import configure, error, get_factory, warning
from connector.domain.diagnostics.system_codes import SystemErrorCode
from connector.domain.diagnostics.core_catalog import build_core_catalog
from connector.domain.diagnostics.registry import build_catalog
from connector.domain.diagnostics.translator import Translator
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import (
    RetryPolicy,
    StopPolicy,
    ExitCodePolicy,
    default_exit_policy,
    default_retry_policy,
    default_stop_policy,
    map_system_code,
    resolve_primary_code,
)

__all__ = [
    "CatalogEntry",
    "ErrorCatalog",
    "OperationError",
    "UnknownDiagnosticCodeError",
    "DiagnosticFactory",
    "configure",
    "error",
    "get_factory",
    "warning",
    "SystemErrorCode",
    "build_core_catalog",
    "build_catalog",
    "Translator",
    "CommandResult",
    "RetryPolicy",
    "StopPolicy",
    "ExitCodePolicy",
    "default_exit_policy",
    "default_retry_policy",
    "default_stop_policy",
    "map_system_code",
    "resolve_primary_code",
]
