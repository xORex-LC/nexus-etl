from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import json

from connector.domain.models import DiagnosticStage, MatchStatus, ValidationErrorItem
from connector.domain.planning.deps import ResolverSettings
from connector.domain.planning.identity_keys import format_identity_key
from connector.domain.planning.match_models import MatchedRow, ResolvedRow, ResolveOp
from connector.domain.planning.rules import LinkFieldRule, LinkRules, ResolveRules
from connector.domain.ports.identity_repository import IdentityRepository
from connector.domain.ports.pending_links_repository import PendingLink, PendingLinksRepository


class Resolver:
    """
    Назначение/ответственность:
        Принятие решения по операции и формирование данных для плана.
    """

    def __init__(
        self,
        resolve_rules: ResolveRules,
        link_rules: LinkRules | None = None,
        *,
        identity_repo: IdentityRepository | None = None,
        pending_repo: PendingLinksRepository | None = None,
        settings: ResolverSettings | None = None,
    ) -> None:
        self.resolve_rules = resolve_rules
        self.link_rules = link_rules or LinkRules()
        self.identity_repo = identity_repo
        self.pending_repo = pending_repo
        self.settings = settings
        self._last_sweep_at: datetime | None = None
        self._expired: list[PendingLink] = []

    def drain_expired(self) -> list[PendingLink]:
        expired = list(self._expired)
        self._expired.clear()
        return expired

    def build_batch_index(
        self,
        matched_rows: list,
        dataset: str,
    ) -> dict[str, dict[str, list[str]]]:
        key_names, id_field = _collect_batch_keys(self.link_rules, dataset)
        if not key_names:
            return {}
        index: dict[str, dict[str, list[str]]] = {dataset: {}}
        for item in matched_rows:
            row = item.row
            if row is None:
                continue
            resolved_id = _extract_resolved_id(row, id_field)
            if not resolved_id:
                continue
            for key_name in key_names:
                value = _extract_identity_value(row, key_name)
                if value is None:
                    continue
                lookup_key = format_identity_key(key_name, value)
                bucket = index[dataset].setdefault(lookup_key, [])
                bucket.append(resolved_id)
        return index

    def _maybe_sweep_expired(self) -> None:
        if self.pending_repo is None:
            return
        interval = self.settings.pending_sweep_interval_seconds if self.settings else 0
        if interval <= 0:
            return
        now = datetime.now(timezone.utc)
        if self._last_sweep_at is not None:
            elapsed = (now - self._last_sweep_at).total_seconds()
            if elapsed < interval:
                return
        self._last_sweep_at = now
        expired = self.pending_repo.sweep_expired(now.isoformat(), reason="expired")
        if expired:
            self._expired.extend(expired)

    def resolve(
        self,
        matched: MatchedRow,
        *,
        resource_id_map: dict[str, str],
        meta: dict[str, Any] | None = None,
        batch_index: dict[str, dict[str, list[str]]] | None = None,
    ) -> tuple[ResolvedRow | None, list[ValidationErrorItem], list[ValidationErrorItem]]:
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []

        self._maybe_sweep_expired()

        if matched.match_status in (MatchStatus.CONFLICT_TARGET, MatchStatus.CONFLICT_SOURCE):
            errors.append(
                ValidationErrorItem(
                    stage=DiagnosticStage.RESOLVE,
                    code="RESOLVE_CONFLICT",
                    field=matched.identity.primary,
                    message="conflict during match stage",
                )
            )
            return None, errors, warnings

        desired_state = dict(matched.desired_state)
        if self.resolve_rules.merge_policy:
            desired_state = self.resolve_rules.merge_policy(matched.existing, desired_state)

        pending_created, should_stop = self._resolve_links(
            matched,
            desired_state,
            warnings,
            errors,
            meta,
            batch_index,
        )
        if should_stop:
            return None, errors, warnings

        resource_id = _resolve_resource_id(matched, resource_id_map)
        if not resource_id:
            errors.append(
                ValidationErrorItem(
                    stage=DiagnosticStage.RESOLVE,
                    code="RESOLVE_MISSING_EXISTING",
                    field="resource_id",
                    message="resource_id is missing for resolved row",
                )
            )
            return None, errors, warnings

        op, changes = _decide_op(matched, desired_state, self.resolve_rules)

        source_ref = (
            self.resolve_rules.build_source_ref(matched.identity)
            if self.resolve_rules.build_source_ref
            else None
        )
        secret_fields = (
            self.resolve_rules.secret_fields_for_op(op, desired_state, matched.existing)
            if self.resolve_rules.secret_fields_for_op
            else []
        )

        resolved = ResolvedRow(
            row_ref=matched.row_ref,
            identity=matched.identity,
            op=op,
            desired_state=desired_state,
            changes=changes,
            existing=matched.existing,
            resource_id=resource_id,
            source_ref=source_ref,
            secret_fields=secret_fields,
        )
        if not pending_created and self.pending_repo is not None:
            self.pending_repo.mark_resolved_for_source(matched.row_ref.row_id)
        return resolved, errors, warnings

    def _resolve_links(
        self,
        matched: MatchedRow,
        desired_state: dict[str, Any],
        warnings: list[ValidationErrorItem],
        errors: list[ValidationErrorItem],
        meta: dict[str, Any] | None,
        batch_index: dict[str, dict[str, list[str]]] | None,
    ) -> tuple[bool, bool]:
        if not self.link_rules.fields:
            return False
        if self.identity_repo is None or self.pending_repo is None:
            errors.append(
                ValidationErrorItem(
                    stage=DiagnosticStage.RESOLVE,
                    code="RESOLVE_CONFIG_MISSING",
                    field=None,
                    message="identity/pending repositories are not configured",
                )
            )
            return False, True

        pending_created = False
        should_stop = False
        for rule in self.link_rules.fields:
            if rule.field not in desired_state:
                continue
            current_value = desired_state.get(rule.field)
            if current_value is None:
                continue
            if isinstance(current_value, int):
                continue

            overrides = _extract_link_key_overrides(meta, rule.field)
            key_values = _extract_key_values(desired_state, rule.resolve_keys, overrides)
            resolved_id, reason, used_lookup = _resolve_with_rules(
                rule,
                key_values,
                desired_state,
                self.identity_repo,
                batch_index,
            )
            if resolved_id is None:
                pending_created = True
                if not _allow_partial(self.settings):
                    should_stop = True
                row_id = matched.row_ref.row_id
                expires_at = _build_expires_at(self.settings)
                lookup_key = used_lookup or ""
                payload = _serialize_pending_payload(matched, desired_state, meta)
                self.pending_repo.add_pending(
                    dataset=rule.target_dataset,
                    source_row_id=row_id,
                    field=rule.field,
                    lookup_key=lookup_key,
                    expires_at=expires_at,
                    payload=payload,
                )
                warnings.append(
                    ValidationErrorItem(
                        stage=DiagnosticStage.RESOLVE,
                        code="RESOLVE_PENDING",
                        field=rule.field,
                        message=reason or "link is pending",
                    )
                )
                continue

            desired_state[rule.field] = _coerce_resolved(resolved_id, rule)

        return pending_created, should_stop


def _resolve_resource_id(matched: MatchedRow, resource_id_map: dict[str, str]) -> str | None:
    if matched.match_status == MatchStatus.MATCHED:
        existing_id = matched.existing.get("_id") if matched.existing else None
        return str(existing_id) if existing_id is not None else None
    return matched.resource_id or resource_id_map.get(matched.identity.primary_value)


def _decide_op(matched: MatchedRow, desired_state: dict[str, Any], rules: ResolveRules) -> tuple[str, dict[str, Any]]:
    if matched.match_status == MatchStatus.NOT_FOUND:
        return ResolveOp.CREATE, {}

    diff_policy = rules.diff_policy or _default_diff
    changes = diff_policy(matched.existing, desired_state)
    if not changes:
        return ResolveOp.SKIP, {}
    return ResolveOp.UPDATE, changes


def _default_diff(existing: dict[str, Any] | None, desired_state: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        return {}
    changes: dict[str, Any] = {}
    for key, value in desired_state.items():
        if key.startswith("__"):
            continue
        if existing.get(key) != value:
            changes[key] = value
    return changes


def _extract_key_values(
    desired_state: dict[str, Any],
    keys: tuple,
    overrides: dict[str, str] | None,
) -> dict[str, str]:
    key_values: dict[str, str] = {}
    for key in keys:
        if overrides and key.name in overrides:
            value = overrides[key.name]
        else:
            value = desired_state.get(key.field)
        if value is None:
            continue
        if isinstance(value, int):
            value_str = str(value)
        else:
            value_str = str(value).strip()
        if value_str == "":
            continue
        key_values[key.name] = value_str
    return key_values


def _extract_link_key_overrides(meta: dict[str, Any] | None, field: str) -> dict[str, str] | None:
    if not meta:
        return None
    link_keys = meta.get("link_keys")
    if not isinstance(link_keys, dict):
        return None
    field_overrides = link_keys.get(field)
    if not isinstance(field_overrides, dict):
        return None
    cleaned: dict[str, str] = {}
    for name, value in field_overrides.items():
        if value is None:
            continue
        value_str = str(value).strip()
        if value_str == "":
            continue
        cleaned[str(name)] = value_str
    return cleaned or None


def _resolve_with_rules(
    rule: LinkFieldRule,
    key_values: dict[str, str],
    desired_state: dict[str, Any],
    identity_repo: IdentityRepository,
    batch_index: dict[str, dict[str, list[str]]] | None,
) -> tuple[str | None, str | None, str | None]:
    used_lookup = None
    for key in rule.resolve_keys:
        value = key_values.get(key.name)
        if not value:
            continue
        lookup_key = format_identity_key(key.name, value)
        used_lookup = lookup_key
        candidates = _lookup_candidates(batch_index, identity_repo, rule.target_dataset, lookup_key)
        if not candidates:
            continue
        if len(candidates) == 1:
            return candidates[0], None, used_lookup

        narrowed = _apply_dedup_rules(
            candidates,
            rule,
            key_values,
            desired_state,
            identity_repo,
            batch_index,
        )
        if len(narrowed) == 1:
            return narrowed[0], None, used_lookup
        return None, "multiple candidates found for link", used_lookup

    return None, "no candidates found for link", used_lookup


def _apply_dedup_rules(
    candidates: list[str],
    rule: LinkFieldRule,
    key_values: dict[str, str],
    desired_state: dict[str, Any],
    identity_repo: IdentityRepository,
    batch_index: dict[str, dict[str, list[str]]] | None,
) -> list[str]:
    if not rule.dedup_rules:
        return candidates
    remaining = set(candidates)
    for dedup in rule.dedup_rules:
        if not remaining:
            return []
        rule_candidates = set(remaining)
        for key_name in dedup:
            lookup_value = key_values.get(key_name)
            if not lookup_value:
                raw = desired_state.get(key_name)
                if raw is None:
                    rule_candidates = set()
                    break
                lookup_value = str(raw).strip()
            if lookup_value == "":
                rule_candidates = set()
                break
            lookup_key = format_identity_key(key_name, lookup_value)
            ids = _lookup_candidates(batch_index, identity_repo, rule.target_dataset, lookup_key)
            rule_candidates = rule_candidates.intersection(ids)
        if rule_candidates:
            remaining = rule_candidates
        if len(remaining) == 1:
            return list(remaining)
    return list(remaining)


def _lookup_candidates(
    batch_index: dict[str, dict[str, list[str]]] | None,
    identity_repo: IdentityRepository,
    dataset: str,
    lookup_key: str,
) -> list[str]:
    batch_hits = []
    if batch_index:
        batch_hits = batch_index.get(dataset, {}).get(lookup_key, [])
    if batch_hits:
        return list(dict.fromkeys(batch_hits))
    return identity_repo.find_candidates(dataset, lookup_key)


def _build_expires_at(settings: ResolverSettings | None) -> str | None:
    if settings is None:
        ttl = 120
    else:
        ttl = settings.pending_ttl_seconds
    if ttl <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()


def _allow_partial(settings: ResolverSettings | None) -> bool:
    if settings is None:
        return False
    return settings.pending_allow_partial


def _coerce_resolved(resolved_id: str, rule: LinkFieldRule) -> Any:
    if rule.coerce == "int":
        try:
            return int(resolved_id)
        except ValueError:
            return resolved_id
    return resolved_id


def _collect_batch_keys(link_rules: LinkRules, dataset: str) -> tuple[set[str], str]:
    keys: set[str] = set()
    id_field = "_id"
    for rule in link_rules.fields:
        if rule.target_dataset != dataset:
            continue
        keys.update(key.name for key in rule.resolve_keys)
        for dedup in rule.dedup_rules:
            keys.update(dedup)
        if id_field != rule.target_id_field:
            id_field = rule.target_id_field
    return keys, id_field


def _extract_resolved_id(row: MatchedRow, id_field: str) -> str | None:
    if row.match_status == MatchStatus.MATCHED and row.existing:
        existing_id = row.existing.get(id_field)
        if existing_id is not None:
            return str(existing_id).strip()
    desired = row.desired_state
    if desired and id_field in desired and desired.get(id_field) is not None:
        return str(desired.get(id_field)).strip()
    if id_field == "_id" and row.resource_id:
        return str(row.resource_id).strip()
    return None


def _extract_identity_value(row: MatchedRow, key_name: str) -> str | None:
    value = row.identity.values.get(key_name)
    if value:
        return str(value).strip()
    if row.desired_state and key_name in row.desired_state:
        raw = row.desired_state.get(key_name)
        if raw is not None:
            return str(raw).strip()
    return None


def _serialize_pending_payload(
    matched: MatchedRow,
    desired_state: dict[str, Any],
    meta: dict[str, Any] | None,
) -> str:
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
        "resource_id": matched.resource_id,
        "meta": meta or {},
    }
    return json.dumps(payload, ensure_ascii=True, default=str)
