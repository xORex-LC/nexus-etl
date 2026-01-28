from __future__ import annotations

from connector.datasets.spec import ReportAdapter

employees_report_adapter = ReportAdapter(
    identity_label="match_key",
    conflict_code="MATCH_CONFLICT",
    conflict_field="matchKey",
)
