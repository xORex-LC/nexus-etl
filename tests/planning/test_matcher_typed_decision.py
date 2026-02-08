from __future__ import annotations

from connector.domain.transform.matcher.match_models import (
    MatchDecision,
    MatchDecisionStatus,
    MatchedRow,
    resolve_decision_status,
)
from connector.domain.models import Identity, RowRef


def test_resolve_decision_status_returns_typed_status():
    row = MatchedRow(
        row_ref=RowRef(line_no=1, row_id="r1", identity_primary="match_key", identity_value="mk"),
        identity=Identity(primary="match_key", values={"match_key": "mk"}),
        desired_state={},
        existing=None,
        fingerprint="fp",
        fingerprint_fields=(),
        match_decision=MatchDecision(status=MatchDecisionStatus.MATCHED, reason_code="identity_exact"),
    )
    assert resolve_decision_status(row) == MatchDecisionStatus.MATCHED


def test_matched_row_requires_match_decision():
    try:
        MatchedRow(
            row_ref=RowRef(line_no=1, row_id="r1", identity_primary="match_key", identity_value="mk"),
            identity=Identity(primary="match_key", values={"match_key": "mk"}),
            desired_state={},
            existing=None,
            fingerprint="fp",
            fingerprint_fields=(),
            # type: ignore[call-arg]
        )
    except TypeError:
        return
    raise AssertionError("MatchedRow must require match_decision")
