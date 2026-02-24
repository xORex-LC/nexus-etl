"""
Назначение:
    Сериализация и десериализация pending payload.

Единственная ответственность (SRP):
    PendingCodecAdapter — реализует IPendingCodec: serialize() пакует MatchedRow
    в JSON-строку для storage, deserialize() восстанавливает список TransformResult
    из raw PendingRow.

    load_pending_rows() — public helper для legacy-кода (ResolveUseCase).

Границы:
    - Зависит только от domain-типов и stdlib ``json``.
    - Не вызывает порты, не обращается к storage.
    - Не логирует — счётчик ``skipped`` возвращается caller'у (``ResolveUseCase``),
      который принимает решение о наблюдаемости.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from connector.domain.models import Identity, RowRef
from connector.domain.ports.cache.models import PendingRow
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.matcher.match_models import (
    MatchCandidate,
    MatchDecision,
    MatchDecisionStatus,
    MatchedRow,
)


@dataclass
class PendingLoadResult:
    """
    Назначение:
        Результат десериализации pending-строк.

    Атрибуты:
        rows    — типизированные ``TransformResult[MatchedRow]``, готовые к pipeline.
        skipped — количество записей, пропущенных из-за невалидного payload.
                  Caller (``ResolveUseCase``) решает, нужно ли логировать.
    """

    rows: list[TransformResult]
    skipped: int


class PendingCodecAdapter:
    """
    Назначение:
        Реализация IPendingCodec — пара serialize/deserialize для pending payload.

    Граница ответственности:
        - serialize(): упаковывает MatchedRow + desired_state + meta в JSON-строку.
        - deserialize(): делегирует load_pending_rows(), возвращает PendingLoadResult.
        - Не вызывает порты и не знает о storage.
    """

    def serialize(
        self,
        matched: MatchedRow,
        desired_state: dict[str, Any],
        meta: dict[str, Any] | None,
    ) -> str:
        """
        Назначение:
            Сериализовать pending-пейлоад в JSON-строку для записи в storage.
        """
        payload = {
            "identity": {
                "primary": matched.identity.primary,
                "values": dict(matched.identity.values),
            },
            "row_ref": {
                "line_no": matched.row_ref.line_no,
                "row_id": matched.row_ref.row_id,
                "identity_primary": matched.row_ref.identity_primary,
                "identity_value": matched.row_ref.identity_value,
            },
            "desired_state": desired_state,
            "existing": matched.existing,
            "fingerprint": matched.fingerprint,
            "fingerprint_fields": list(matched.fingerprint_fields),
            "match_decision": _serialize_match_decision(matched),
            "source_links": _serialize_source_links(matched),
            "target_id": matched.target_id,
            "meta": meta or {},
        }
        return json.dumps(payload, ensure_ascii=True, default=str)

    def deserialize(self, pending_rows: list[PendingRow]) -> PendingLoadResult:
        """
        Назначение:
            Десериализовать список PendingRow → PendingLoadResult.
        """
        return load_pending_rows(pending_rows)


def load_pending_rows(pending_rows: list[PendingRow]) -> PendingLoadResult:
    """
    Назначение:
        Десериализует список ``PendingRow`` → ``PendingLoadResult(rows, skipped)``.

    Невалидные записи (невалидный JSON, отсутствующие поля, неизвестный статус)
    пропускаются без исключений; их количество возвращается в ``skipped``.
    """
    results: list[TransformResult] = []
    skipped = 0
    for pending in pending_rows:
        try:
            payload = json.loads(pending.payload)
        except (TypeError, json.JSONDecodeError):
            skipped += 1
            continue
        parsed = _deserialize_pending_matched_row(payload)
        if parsed is None:
            skipped += 1
            continue
        matched_row, meta = parsed
        row_ref = matched_row.row_ref
        record = SourceRecord(line_no=row_ref.line_no, record_id=row_ref.row_id, values={})
        results.append(
            TransformResult(
                record=record,
                row=matched_row,
                row_ref=row_ref,
                match_key=None,
                meta=meta,
                secret_candidates={},
                errors=[],
                warnings=[],
            )
        )
    return PendingLoadResult(rows=results, skipped=skipped)


# ════════════════════════════════════════════════════════════════════════════════
# Serialization helpers (used by PendingCodecAdapter.serialize)
# ════════════════════════════════════════════════════════════════════════════════

def _serialize_source_links(matched: MatchedRow) -> dict[str, dict[str, Any]]:
    return {
        field: {
            "primary": identity.primary,
            "values": dict(identity.values),
        }
        for field, identity in matched.source_links.items()
    }


def _serialize_match_decision(matched: MatchedRow) -> dict[str, Any]:
    decision = matched.match_decision
    return {
        "status": decision.status.value,
        "reason_code": decision.reason_code,
        "message": decision.message,
        "score": decision.score,
        "meta": decision.meta,
        "selected": _serialize_candidate(decision.selected),
        "candidates": [_serialize_candidate(candidate) for candidate in decision.candidates],
    }


def _serialize_candidate(candidate: MatchCandidate | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "target_id": candidate.target_id,
        "identity": candidate.identity,
        "score": candidate.score,
        "match_mode": candidate.match_mode,
        "evidence": candidate.evidence,
    }


# ════════════════════════════════════════════════════════════════════════════════
# Deserialization helpers (used by load_pending_rows)
# ════════════════════════════════════════════════════════════════════════════════

def _deserialize_pending_matched_row(
    payload: dict,
) -> tuple[MatchedRow, dict[str, object]] | None:
    identity_data = payload.get("identity")
    row_ref_data = payload.get("row_ref")
    desired_state = payload.get("desired_state")
    existing = payload.get("existing")
    fingerprint = payload.get("fingerprint")
    fingerprint_fields = payload.get("fingerprint_fields")
    decision_data = payload.get("match_decision")
    if not isinstance(identity_data, dict):
        return None
    if not isinstance(row_ref_data, dict):
        return None
    if not isinstance(desired_state, dict):
        return None
    if existing is not None and not isinstance(existing, dict):
        return None
    if not isinstance(fingerprint, str) or not fingerprint:
        return None
    if not isinstance(fingerprint_fields, list):
        return None
    if not isinstance(decision_data, dict):
        return None

    values = identity_data.get("values")
    primary = identity_data.get("primary")
    if not isinstance(values, dict):
        return None
    if not isinstance(primary, str) or not primary:
        return None
    identity = Identity(primary=primary, values={str(k): str(v) for k, v in values.items() if v is not None})
    if not identity.primary_value:
        return None

    row_id = row_ref_data.get("row_id")
    line_no_raw = row_ref_data.get("line_no")
    if not isinstance(row_id, str) or not row_id:
        return None
    try:
        line_no = int(line_no_raw)
    except (TypeError, ValueError):
        return None
    row_ref = RowRef(
        line_no=line_no,
        row_id=row_id,
        identity_primary=row_ref_data.get("identity_primary"),
        identity_value=row_ref_data.get("identity_value"),
    )

    match_decision = _deserialize_match_decision(decision_data)
    if match_decision is None:
        return None

    source_links = _deserialize_source_links(payload.get("source_links"))
    if source_links is None:
        return None

    fingerprint_fields_tuple = tuple(str(item) for item in fingerprint_fields)
    target_id = payload.get("target_id")
    if target_id is not None:
        target_id = str(target_id)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}

    matched_row = MatchedRow(
        row_ref=row_ref,
        identity=identity,
        desired_state=desired_state,
        existing=existing,
        fingerprint=fingerprint,
        fingerprint_fields=fingerprint_fields_tuple,
        match_decision=match_decision,
        source_links=source_links,
        target_id=target_id,
    )
    return matched_row, meta


def _deserialize_match_decision(payload: dict) -> MatchDecision | None:
    status_raw = payload.get("status")
    reason_code = payload.get("reason_code")
    if not isinstance(status_raw, str):
        return None
    if not isinstance(reason_code, str) or not reason_code:
        return None
    try:
        status = MatchDecisionStatus(status_raw)
    except ValueError:
        return None

    selected_payload = payload.get("selected")
    selected = _deserialize_candidate(selected_payload) if selected_payload is not None else None
    if selected_payload is not None and selected is None:
        return None

    candidates_payload = payload.get("candidates")
    if not isinstance(candidates_payload, list):
        return None
    candidates: list[MatchCandidate] = []
    for item in candidates_payload:
        candidate = _deserialize_candidate(item)
        if candidate is None:
            return None
        candidates.append(candidate)

    score = payload.get("score")
    if score is not None and not isinstance(score, (int, float)):
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    message = payload.get("message")
    if message is not None and not isinstance(message, str):
        return None

    return MatchDecision(
        status=status,
        reason_code=reason_code,
        message=message,
        selected=selected,
        candidates=tuple(candidates),
        score=float(score) if isinstance(score, (int, float)) else None,
        meta=meta,
    )


def _deserialize_candidate(payload: object) -> MatchCandidate | None:
    if not isinstance(payload, dict):
        return None
    match_mode = payload.get("match_mode")
    if not isinstance(match_mode, str) or not match_mode:
        return None
    target_id = payload.get("target_id")
    identity = payload.get("identity")
    score = payload.get("score")
    if target_id is not None:
        target_id = str(target_id)
    if identity is not None:
        identity = str(identity)
    if score is not None and not isinstance(score, (int, float)):
        return None
    evidence = payload.get("evidence")
    if evidence is not None and not isinstance(evidence, dict):
        return None
    return MatchCandidate(
        target_id=target_id,
        identity=identity,
        score=float(score) if isinstance(score, (int, float)) else None,
        match_mode=match_mode,
        evidence=evidence,
    )


def _deserialize_source_links(payload: object) -> dict[str, Identity] | None:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        return None
    source_links: dict[str, Identity] = {}
    for field, raw_identity in payload.items():
        if not isinstance(field, str):
            return None
        if not isinstance(raw_identity, dict):
            return None
        primary = raw_identity.get("primary")
        values = raw_identity.get("values")
        if not isinstance(primary, str) or not primary:
            return None
        if not isinstance(values, dict):
            return None
        source_links[field] = Identity(
            primary=primary,
            values={str(k): str(v) for k, v in values.items() if v is not None},
        )
    return source_links


__all__ = ["PendingCodecAdapter", "PendingLoadResult", "load_pending_rows"]
