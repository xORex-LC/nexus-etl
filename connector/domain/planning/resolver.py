from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from connector.domain.models import DiagnosticStage, MatchStatus, ValidationErrorItem
from connector.domain.planning.deps import ResolverSettings
from connector.domain.planning.identity_keys import format_identity_key
from connector.domain.planning.match_models import MatchedRow, ResolvedRow, ResolveOp
from connector.domain.planning.rules import LinkFieldRule, LinkRules, ResolveRules
from connector.domain.ports.identity_repository import IdentityRepository
from connector.domain.ports.pending_links_repository import PendingLinksRepository


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

    def resolve(
        self,
        matched: MatchedRow,
        *,
        resource_id_map: dict[str, str],
        meta: dict[str, Any] | None = None,
    ) -> tuple[ResolvedRow | None, list[ValidationErrorItem], list[ValidationErrorItem]]:
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []

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

        should_stop = self._resolve_links(matched, desired_state, warnings, errors, meta)
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
        return resolved, errors, warnings

    def _resolve_links(
        self,
        matched: MatchedRow,
        desired_state: dict[str, Any],
        warnings: list[ValidationErrorItem],
        errors: list[ValidationErrorItem],
        meta: dict[str, Any] | None,
    ) -> bool:
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
            return True

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
            )
            if resolved_id is None:
                if not _allow_partial(self.settings):
                    should_stop = True
                row_id = matched.row_ref.row_id
                expires_at = _build_expires_at(self.settings)
                lookup_key = used_lookup or ""
                self.pending_repo.add_pending(
                    dataset=rule.target_dataset,
                    source_row_id=row_id,
                    field=rule.field,
                    lookup_key=lookup_key,
                    expires_at=expires_at,
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

        return should_stop


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
) -> tuple[str | None, str | None, str | None]:
    used_lookup = None
    for key in rule.resolve_keys:
        value = key_values.get(key.name)
        if not value:
            continue
        lookup_key = format_identity_key(key.name, value)
        used_lookup = lookup_key
        candidates = identity_repo.find_candidates(rule.target_dataset, lookup_key)
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
            ids = identity_repo.find_candidates(rule.target_dataset, lookup_key)
            rule_candidates = rule_candidates.intersection(ids)
        if rule_candidates:
            remaining = rule_candidates
        if len(remaining) == 1:
            return list(remaining)
    return list(remaining)


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
