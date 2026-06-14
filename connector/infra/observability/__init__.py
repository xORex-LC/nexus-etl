"""Observability infrastructure — retention, ledger и runtime adapters

Пакет собирает infra-компоненты observability, которые работают поверх
value-object layout/policy из `common/observability/layout.py`. На текущем этапе здесь
живут безопасная ретенция observability-артефактов и append-only run ledger.
"""

from .ledger import (
    JsonlRunLedger,
    RunLedgerBackend,
    RunLedgerRecord,
    RunLedgerRowCounters,
    SqliteRunLedger,
    build_run_ledger_backend,
    build_run_ledger_record,
)
from .pointers import LatestArtifactPointerPublisher, PointerPublishResult
from .retention import ObservabilityRetentionSweeper, RetentionSweepResult
from .viewer import ObservabilityArtifactViewer

__all__ = [
    "JsonlRunLedger",
    "LatestArtifactPointerPublisher",
    "ObservabilityRetentionSweeper",
    "ObservabilityArtifactViewer",
    "PointerPublishResult",
    "RetentionSweepResult",
    "RunLedgerBackend",
    "RunLedgerRecord",
    "RunLedgerRowCounters",
    "SqliteRunLedger",
    "build_run_ledger_backend",
    "build_run_ledger_record",
]
