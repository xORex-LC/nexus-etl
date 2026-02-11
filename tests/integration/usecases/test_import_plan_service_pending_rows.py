from __future__ import annotations

import json
from dataclasses import dataclass

from connector.domain.transform.matcher.match_models import MatchDecisionReason, MatchDecisionStatus
from connector.usecases.import_plan_service import _load_pending_rows


@dataclass(frozen=True)
class _PendingRow:
    source_row_id: str
    payload: str


class _PendingReplay:
    def __init__(self, rows: list[_PendingRow]) -> None:
        self._rows = rows

    def list_pending_rows(self, dataset: str) -> list[_PendingRow]:
        _ = dataset
        return list(self._rows)


def _candidate(*, target_id: str | None, identity: str | None, score: float | None, mode: str) -> dict:
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


def _payload(*, row_id: str, match_key: str, match_decision: dict, existing: dict | None = None) -> str:
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
            "source_links": {},
            "target_id": f"target:{row_id}",
            "meta": {},
        }
    )


def test_pending_replay_rows_include_typed_match_decision_for_all_statuses():
    pending_replay = _PendingReplay(
        [
            _PendingRow(
                source_row_id="row-amb",
                payload=_payload(
                    row_id="row-amb",
                    match_key="amb",
                    match_decision=_decision(
                        status=MatchDecisionStatus.AMBIGUOUS,
                        reason_code=MatchDecisionReason.FUZZY_TIE,
                        selected=None,
                        candidates=[
                            _candidate(target_id="u-1", identity="amb", score=0.81, mode="fuzzy"),
                            _candidate(target_id="u-2", identity="amb", score=0.81, mode="fuzzy"),
                        ],
                    ),
                ),
            ),
            _PendingRow(
                source_row_id="row-match",
                payload=_payload(
                    row_id="row-match",
                    match_key="matched",
                    match_decision=_decision(
                        status=MatchDecisionStatus.MATCHED,
                        reason_code=MatchDecisionReason.IDENTITY_EXACT,
                        selected=_candidate(target_id="u-3", identity="matched", score=1.0, mode="exact"),
                        candidates=[_candidate(target_id="u-3", identity="matched", score=1.0, mode="exact")],
                        score=1.0,
                    ),
                    existing={"_id": "u-3", "match_key": "matched"},
                ),
            ),
            _PendingRow(
                source_row_id="row-miss",
                payload=_payload(
                    row_id="row-miss",
                    match_key="missing",
                    match_decision=_decision(
                        status=MatchDecisionStatus.NOT_FOUND,
                        reason_code=MatchDecisionReason.IDENTITY_NOT_FOUND,
                        selected=None,
                        candidates=[],
                    ),
                ),
            ),
        ],
    )

    rows = _load_pending_rows(
        dataset="employees",
        pending_replay=pending_replay,
    )
    assert len(rows) == 3
    by_row_id = {item.row.row_ref.row_id: item.row for item in rows if item.row is not None}

    ambiguous = by_row_id["row-amb"]
    assert ambiguous.match_decision.status == MatchDecisionStatus.AMBIGUOUS

    matched = by_row_id["row-match"]
    assert matched.match_decision.status == MatchDecisionStatus.MATCHED
    assert matched.match_decision.selected is not None

    missing = by_row_id["row-miss"]
    assert missing.match_decision.status == MatchDecisionStatus.NOT_FOUND


def test_pending_replay_rows_skip_legacy_payload_without_typed_decision():
    pending_replay = _PendingReplay(
        [
            _PendingRow(
                source_row_id="legacy-row",
                payload=json.dumps(
                    {
                        "identity": {"primary": "match_key", "values": {"match_key": "legacy"}},
                        "row_ref": {"line_no": 1, "row_id": "legacy-row"},
                        "desired_state": {"match_key": "legacy"},
                        "target_id": "target:legacy-row",
                        "meta": {},
                    }
                ),
            )
        ]
    )

    rows = _load_pending_rows(
        dataset="employees",
        pending_replay=pending_replay,
    )
    assert rows == []
