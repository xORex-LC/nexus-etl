from __future__ import annotations

import json
from dataclasses import dataclass

from connector.domain.transform.matcher.match_models import MatchDecisionStatus
from connector.usecases.import_plan_service import _load_pending_rows


@dataclass(frozen=True)
class _PendingRow:
    source_row_id: str
    payload: str


class _PendingReplay:
    def __init__(self, rows: list[_PendingRow], by_identity: dict[str, list[dict]]) -> None:
        self._rows = rows
        self._by_identity = by_identity

    def list_pending_rows(self, dataset: str) -> list[_PendingRow]:
        _ = dataset
        return list(self._rows)

    def find(self, dataset: str, filters: dict[str, str], *, include_deleted: bool = False):
        _ = dataset, include_deleted
        value = next(iter(filters.values()))
        return self._by_identity.get(str(value), [])


def _payload(*, row_id: str, match_key: str) -> str:
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
            "target_id": f"target:{row_id}",
            "meta": {},
        }
    )


def test_pending_replay_rows_include_typed_match_decision_for_all_statuses():
    pending_replay = _PendingReplay(
        [
            _PendingRow(source_row_id="row-amb", payload=_payload(row_id="row-amb", match_key="amb")),
            _PendingRow(source_row_id="row-match", payload=_payload(row_id="row-match", match_key="matched")),
            _PendingRow(source_row_id="row-miss", payload=_payload(row_id="row-miss", match_key="missing")),
        ],
        {
            "amb": [{"_id": "u-1"}, {"_id": "u-2"}],
            "matched": [{"_id": "u-3"}],
        },
    )

    rows = _load_pending_rows(
        dataset="employees",
        pending_replay=pending_replay,
        include_deleted=False,
        ignored_fields=set(),
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
