"""
Unit-тесты для connector/domain/transform/resolver/pending_codec.py

Zone 1: pending_codec.load_pending_rows() — чистые unit-тесты.
Не используют порты, SQLite или стабы — передают list[PendingRow] напрямую.
"""

from __future__ import annotations

import json

from connector.domain.ports.cache.models import PendingRow
from connector.domain.transform.matcher.match_models import MatchDecisionReason, MatchDecisionStatus
from connector.domain.transform.resolver.pending_codec import load_pending_rows


# ─── Builder helpers ─────────────────────────────────────────────────────────


def _candidate(
    *,
    target_id: str | None = "t-1",
    identity: str | None = "key-1",
    score: float | None = 1.0,
    mode: str = "exact",
) -> dict:
    return {
        "target_id": target_id,
        "identity": identity,
        "score": score,
        "match_mode": mode,
        "evidence": None,
    }


def _decision(
    *,
    status: MatchDecisionStatus,
    reason_code: str,
    selected: dict | None,
    candidates: list[dict],
    score: float | None = None,
) -> dict:
    return {
        "status": status.value,
        "reason_code": reason_code,
        "message": None,
        "selected": selected,
        "candidates": candidates,
        "score": score,
        "meta": {"match_mode": "test"},
    }


def _payload(
    *,
    row_id: str = "row-1",
    match_key: str = "mk-1",
    match_decision: dict,
    existing: dict | None = None,
    source_links: dict | None = None,
    target_id: str | None = None,
) -> str:
    return json.dumps(
        {
            "identity": {
                "primary": "match_key",
                "values": {"match_key": match_key},
            },
            "row_ref": {
                "line_no": 1,
                "row_id": row_id,
                "identity_primary": "match_key",
                "identity_value": match_key,
            },
            "desired_state": {"match_key": match_key},
            "existing": existing,
            "fingerprint": "fp-test",
            "fingerprint_fields": ["match_key"],
            "match_decision": match_decision,
            "source_links": source_links or {},
            "target_id": target_id or f"target:{row_id}",
            "meta": {},
        }
    )


def _matched_decision() -> dict:
    return _decision(
        status=MatchDecisionStatus.MATCHED,
        reason_code=MatchDecisionReason.IDENTITY_EXACT,
        selected=_candidate(target_id="t-1", identity="mk-1", score=1.0, mode="exact"),
        candidates=[_candidate(target_id="t-1", identity="mk-1", score=1.0, mode="exact")],
        score=1.0,
    )


def _pending_row(payload_str: str, *, row_id: str = "row-1") -> PendingRow:
    return PendingRow(dataset="employees", source_row_id=row_id, payload=payload_str)


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_load_pending_rows_empty_list():
    result = load_pending_rows([])
    assert result.rows == []
    assert result.skipped == 0


def test_load_pending_rows_valid_matched_decision():
    row = _pending_row(_payload(match_decision=_matched_decision()))
    result = load_pending_rows([row])
    assert len(result.rows) == 1
    assert result.skipped == 0
    tr = result.rows[0]
    assert tr.row is not None
    assert tr.row.match_decision.status == MatchDecisionStatus.MATCHED


def test_load_pending_rows_all_decision_statuses():
    rows = [
        _pending_row(
            _payload(
                row_id="row-match",
                match_key="matched",
                match_decision=_decision(
                    status=MatchDecisionStatus.MATCHED,
                    reason_code=MatchDecisionReason.IDENTITY_EXACT,
                    selected=_candidate(target_id="t-3", identity="matched", score=1.0),
                    candidates=[_candidate(target_id="t-3", identity="matched", score=1.0)],
                    score=1.0,
                ),
                existing={"_id": "t-3", "match_key": "matched"},
            ),
            row_id="row-match",
        ),
        _pending_row(
            _payload(
                row_id="row-miss",
                match_key="missing",
                match_decision=_decision(
                    status=MatchDecisionStatus.NOT_FOUND,
                    reason_code=MatchDecisionReason.IDENTITY_NOT_FOUND,
                    selected=None,
                    candidates=[],
                ),
            ),
            row_id="row-miss",
        ),
        _pending_row(
            _payload(
                row_id="row-amb",
                match_key="amb",
                match_decision=_decision(
                    status=MatchDecisionStatus.AMBIGUOUS,
                    reason_code=MatchDecisionReason.FUZZY_TIE,
                    selected=None,
                    candidates=[
                        _candidate(target_id="t-1", identity="amb", score=0.81, mode="fuzzy"),
                        _candidate(target_id="t-2", identity="amb", score=0.81, mode="fuzzy"),
                    ],
                ),
            ),
            row_id="row-amb",
        ),
    ]

    result = load_pending_rows(rows)
    assert len(result.rows) == 3
    assert result.skipped == 0

    by_row_id = {tr.row.row_ref.row_id: tr.row for tr in result.rows}
    assert by_row_id["row-match"].match_decision.status == MatchDecisionStatus.MATCHED
    assert by_row_id["row-miss"].match_decision.status == MatchDecisionStatus.NOT_FOUND
    assert by_row_id["row-amb"].match_decision.status == MatchDecisionStatus.AMBIGUOUS


def test_load_pending_rows_skips_legacy_without_typed_decision():
    legacy_payload = json.dumps(
        {
            "identity": {"primary": "match_key", "values": {"match_key": "legacy"}},
            "row_ref": {"line_no": 1, "row_id": "legacy-row"},
            "desired_state": {"match_key": "legacy"},
            "target_id": "target:legacy-row",
            "meta": {},
        }
    )
    row = _pending_row(legacy_payload, row_id="legacy-row")
    result = load_pending_rows([row])
    assert result.rows == []
    assert result.skipped == 1


def test_load_pending_rows_skips_invalid_json():
    row = PendingRow(dataset="employees", source_row_id="bad", payload="not-valid-json{{{")
    result = load_pending_rows([row])
    assert result.rows == []
    assert result.skipped == 1


def test_load_pending_rows_skips_missing_required_field():
    # Missing "identity" field
    bad_payload = json.dumps(
        {
            "row_ref": {"line_no": 1, "row_id": "row-1"},
            "desired_state": {"match_key": "mk"},
            "fingerprint": "fp",
            "fingerprint_fields": ["match_key"],
            "match_decision": _matched_decision(),
            "source_links": {},
            "target_id": "t-1",
            "meta": {},
        }
    )
    result = load_pending_rows([_pending_row(bad_payload)])
    assert result.rows == []
    assert result.skipped == 1


def test_load_pending_rows_skips_invalid_decision_status():
    decision_with_bad_status = {
        "status": "TOTALLY_UNKNOWN_STATUS",
        "reason_code": "some_code",
        "message": None,
        "selected": None,
        "candidates": [],
        "score": None,
        "meta": {},
    }
    row = _pending_row(_payload(match_decision=decision_with_bad_status))
    result = load_pending_rows([row])
    assert result.rows == []
    assert result.skipped == 1


def test_load_pending_rows_result_has_empty_record_values():
    row = _pending_row(_payload(match_decision=_matched_decision()))
    result = load_pending_rows([row])
    assert result.rows[0].record.values == {}


def test_load_pending_rows_preserves_source_links():
    source_links = {
        "manager_id": {
            "primary": "employee_id",
            "values": {"employee_id": "mgr-42"},
        }
    }
    row = _pending_row(
        _payload(match_decision=_matched_decision(), source_links=source_links)
    )
    result = load_pending_rows([row])
    assert len(result.rows) == 1
    assert "manager_id" in result.rows[0].row.source_links
    assert result.rows[0].row.source_links["manager_id"].primary_value == "mgr-42"


def test_load_pending_rows_result_carries_target_id():
    row = _pending_row(
        _payload(match_decision=_matched_decision(), target_id="target:row-abc"),
        row_id="row-abc",
    )
    result = load_pending_rows([row])
    assert result.rows[0].row.target_id == "target:row-abc"


def test_load_pending_rows_returns_skipped_count():
    valid_row = _pending_row(_payload(match_decision=_matched_decision(), row_id="row-ok"), row_id="row-ok")
    invalid_row = PendingRow(dataset="employees", source_row_id="bad", payload="oops-not-json")
    legacy_row = _pending_row(
        json.dumps(
            {
                "identity": {"primary": "match_key", "values": {"match_key": "x"}},
                "row_ref": {"line_no": 1, "row_id": "legacy"},
                "desired_state": {},
                "target_id": "t",
                "meta": {},
            }
        ),
        row_id="legacy",
    )

    result = load_pending_rows([valid_row, invalid_row, legacy_row])
    assert len(result.rows) == 1
    assert result.skipped == 2
