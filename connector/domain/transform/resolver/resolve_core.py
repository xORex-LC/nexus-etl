"""
Назначение:
    Resolve-стадия: связывание и обогащение по lookup.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import json
import logging

from connector.domain.models import DiagnosticStage, DiagnosticItem
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.context import error as diag_error, warning as diag_warning
from connector.domain.transform.common.sink_schema import validate_sink_fields
from connector.domain.dsl.diagnostics import append_dsl_issues
from connector.domain.transform_dsl.specs import SinkSpec
from connector.domain.transform.resolver.resolve_deps import ResolverSettings
from connector.domain.transform.matcher.identity_keys import format_identity_key
from connector.domain.transform.matcher.match_models import (
    MatchedRow,
    MatchDecisionStatus,
    ResolvedRow,
    ResolveOp,
    build_fingerprint_for_keys,
    resolve_decision_status,
)
from connector.domain.transform_dsl.compilers.resolve import (
    LinkFieldRule,
    LinkRules,
    ResolveRules,
    SecretLifecyclePolicy,
)
from connector.domain.ports.cache.models import PendingLink
from connector.domain.ports.cache.roles import ResolveRuntimePort

logger = logging.getLogger(__name__)


class ResolveCore:
    """
    Назначение/ответственность:
        Ядро resolve-стадии: принятие решения по операции и формирование данных для плана.
    """

    def __init__(
        self,
        resolve_rules: ResolveRules,
        link_rules: LinkRules | None = None,
        *,
        cache_gateway: ResolveRuntimePort | None = None,
        settings: ResolverSettings | None = None,
        catalog: ErrorCatalog,
        sink_spec: SinkSpec | None = None,
    ) -> None:
        self.resolve_rules = resolve_rules
        self.link_rules = link_rules or LinkRules()
        self.cache_gateway = cache_gateway
        self.settings = settings
        self.catalog = catalog
        self.sink_spec = sink_spec
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
        """
        Назначение:
            Построить индекс resolved id по identity-ключам в пределах батча.
        """
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
        if self.cache_gateway is None:
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
        expired = self.cache_gateway.sweep_expired(now.isoformat(), reason="expired")
        if expired:
            self._expired.extend(expired)

    def resolve(
        self,
        matched: MatchedRow,
        *,
        target_id_map: dict[str, str],
        meta: dict[str, Any] | None = None,
        batch_index: dict[str, dict[str, list[str]]] | None = None,
    ) -> tuple[ResolvedRow | None, list[DiagnosticItem], list[DiagnosticItem]]:
        """
        Назначение:
            Принять решение по операции (create/update/skip) и вернуть ResolvedRow.

        Алгоритм:
            - Проверяет конфликты match-стадии.
            - Применяет merge_policy для desired_state.
            - Разрешает ссылки через lookup (pending при необходимости).
            - Определяет target_id и решает операцию.
        """
        errors: list[DiagnosticItem] = []
        warnings: list[DiagnosticItem] = []

        self._maybe_sweep_expired()

        decision_status = resolve_decision_status(matched)
        if decision_status in (MatchDecisionStatus.AMBIGUOUS, MatchDecisionStatus.CONFLICT_SOURCE):
            # Политика: конфликт на этапе match = hard-fail, план не строим.
            is_ambiguous = decision_status == MatchDecisionStatus.AMBIGUOUS
            conflict_reason = "ambiguous match result" if is_ambiguous else "conflict during match stage"
            diag_code = "RESOLVE_AMBIGUOUS" if is_ambiguous else "RESOLVE_CONFLICT"
            errors.append(
                diag_error(
                    catalog=self.catalog,
                    stage=DiagnosticStage.RESOLVE,
                    code=diag_code,
                    field=matched.identity.primary,
                    message=conflict_reason,
                    record_ref=matched.row_ref,
                )
            )
            return None, errors, warnings

        original_desired = dict(matched.desired_state)
        desired_state = dict(original_desired)
        mutated_fields: set[str] = set()
        if self.resolve_rules.merge_policy:
            # merge_policy должен только дополнять desired_state на основе existing,
            # не затирая явно заданные значения.
            merged = self.resolve_rules.merge_policy(matched.existing, desired_state)
            if merged is not None:
                overwritten = [
                    key for key, value in original_desired.items() if key in merged and merged[key] != value
                ]
                if overwritten:
                    logger.warning(
                        "merge_policy tried to overwrite desired fields; preserving source values. row_id=%s fields=%s",
                        matched.row_ref.row_id,
                        overwritten,
                    )
                for key, value in original_desired.items():
                    merged[key] = value
                desired_state = merged
                mutated_fields.update(_collect_changed_fields(original_desired, desired_state))

        pending_created, should_stop, link_mutations = self._resolve_links(
            matched,
            desired_state,
            warnings,
            errors,
            meta,
            batch_index,
        )
        mutated_fields.update(link_mutations)
        if should_stop:
            return None, errors, warnings
        if self._validate_sink_mutations(
            matched=matched,
            desired_state=desired_state,
            mutated_fields=mutated_fields,
            errors=errors,
            warnings=warnings,
        ):
            return None, errors, warnings

        target_id = _resolve_target_id(matched, target_id_map)
        if not target_id:
            errors.append(
                diag_error(
                    catalog=self.catalog,
                    stage=DiagnosticStage.RESOLVE,
                    code="RESOLVE_TARGET_ID_MISSING",
                    field="target_id",
                    message="target_id is missing for resolved row",
                    record_ref=matched.row_ref,
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
            target_id=target_id,
            source_ref=source_ref,
            secret_fields=secret_fields,
            secret_lifecycle=_serialize_secret_lifecycle(self.resolve_rules.secret_lifecycle),
        )
        if not pending_created and self.cache_gateway is not None:
            self.cache_gateway.mark_resolved_for_source(matched.row_ref.row_id)
        return resolved, errors, warnings

    def _resolve_links(
        self,
        matched: MatchedRow,
        desired_state: dict[str, Any],
        warnings: list[DiagnosticItem],
        errors: list[DiagnosticItem],
        meta: dict[str, Any] | None,
        batch_index: dict[str, dict[str, list[str]]] | None,
    ) -> tuple[bool, bool, set[str]]:
        """
        Назначение:
            Разрешить связи (foreign keys) по правилам LinkRules.

        Возвращает:
            (pending_created, should_stop, changed_fields).
        """
        if not self.link_rules.fields:
            return False, False, set()
        if self.cache_gateway is None:
            errors.append(
                diag_error(
                    catalog=self.catalog,
                    stage=DiagnosticStage.RESOLVE,
                    code="RESOLVE_CONFIG_MISSING",
                    field=None,
                    message="cache gateway is not configured",
                    record_ref=matched.row_ref,
                )
            )
            return False, True, set()

        pending_created = False
        should_stop = False
        changed_fields: set[str] = set()
        for rule in self.link_rules.fields:
            if rule.field not in desired_state:
                continue
            current_value = desired_state.get(rule.field)
            if current_value is None:
                continue
            if isinstance(current_value, int) and _should_skip_int(rule):
                continue

            overrides = _extract_link_key_overrides(meta, rule.field)
            key_values = _extract_key_values(desired_state, rule.resolve_keys, overrides)
            resolved_id, reason, used_lookup = _resolve_with_rules(
                rule,
                key_values,
                desired_state,
                self.cache_gateway,
                batch_index,
            )
            if resolved_id is None:
                if rule.on_unresolved == "hard_error":
                    errors.append(
                        diag_error(
                            catalog=self.catalog,
                            stage=DiagnosticStage.RESOLVE,
                            code="RESOLVE_CONFLICT",
                            field=rule.field,
                            message=reason or "link is unresolved",
                            record_ref=matched.row_ref,
                        )
                    )
                    return pending_created, True, changed_fields
                pending_created = True
                row_id = matched.row_ref.row_id
                expires_at = _build_expires_at(self.settings)
                lookup_key = used_lookup or ""
                payload = _serialize_pending_payload(matched, desired_state, meta)
                pending_id = self.cache_gateway.add_pending(
                    dataset=rule.target_dataset,
                    source_row_id=row_id,
                    field=rule.field,
                    lookup_key=lookup_key,
                    expires_at=expires_at,
                    payload=payload,
                )
                attempts = self.cache_gateway.touch_attempt(pending_id)
                max_attempts = _max_attempts(self.settings)
                if max_attempts > 0 and attempts >= max_attempts:
                    self.cache_gateway.mark_conflict(pending_id, reason="max attempts reached")
                    errors.append(
                        diag_error(
                            catalog=self.catalog,
                            stage=DiagnosticStage.RESOLVE,
                            code="RESOLVE_MAX_ATTEMPTS",
                            field=rule.field,
                            message="pending max attempts reached",
                            record_ref=matched.row_ref,
                        )
                    )
                    return pending_created, True, changed_fields
                warnings.append(
                    diag_warning(
                        catalog=self.catalog,
                        stage=DiagnosticStage.RESOLVE,
                        code="RESOLVE_PENDING",
                        field=rule.field,
                        message=reason or "link is pending",
                        record_ref=matched.row_ref,
                    )
                )
                if not _allow_partial(self.settings):
                    should_stop = True
                continue

            resolved_value = _coerce_resolved(resolved_id, rule)
            if desired_state.get(rule.field) != resolved_value:
                desired_state[rule.field] = resolved_value
                changed_fields.add(rule.field)

        return pending_created, should_stop, changed_fields

    def _validate_sink_mutations(
        self,
        *,
        matched: MatchedRow,
        desired_state: dict[str, Any],
        mutated_fields: set[str],
        errors: list[DiagnosticItem],
        warnings: list[DiagnosticItem],
    ) -> bool:
        if self.sink_spec is None:
            return False
        if not mutated_fields:
            return False
        issues = validate_sink_fields(
            desired_state,
            self.sink_spec,
            fields=sorted(mutated_fields),
            check_types=True,
        )
        if not issues:
            return False
        append_dsl_issues(
            errors=errors,
            warnings=warnings,
            issues=issues,
            stage=DiagnosticStage.RESOLVE,
            catalog=self.catalog,
            record_ref=matched.row_ref,
            on_error="error",
        )
        return True


def _resolve_target_id(matched: MatchedRow, target_id_map: dict[str, str]) -> str | None:
    """
    Назначение:
        Вычислить target_id с учётом match-статуса и batch-map.
    """
    if resolve_decision_status(matched) == MatchDecisionStatus.MATCHED:
        existing_id = matched.existing.get("_id") if matched.existing else None
        return str(existing_id) if existing_id is not None else None
    return matched.target_id or target_id_map.get(matched.identity.primary_value)


def _decide_op(matched: MatchedRow, desired_state: dict[str, Any], rules: ResolveRules) -> tuple[str, dict[str, Any]]:
    """
    Назначение:
        Определить операцию и diff (если нужно).
    """
    if resolve_decision_status(matched) == MatchDecisionStatus.NOT_FOUND:
        return ResolveOp.CREATE, {}
    if _can_skip_with_fingerprint(matched, desired_state, rules):
        return ResolveOp.SKIP, {}

    diff_policy = rules.diff_policy or _default_diff
    changes = diff_policy(matched.existing, desired_state)
    if not changes:
        return ResolveOp.SKIP, {}
    return ResolveOp.UPDATE, changes


def _can_skip_with_fingerprint(
    matched: MatchedRow,
    desired_state: dict[str, Any],
    rules: ResolveRules,
) -> bool:
    if resolve_decision_status(matched) != MatchDecisionStatus.MATCHED:
        return False
    if matched.existing is None:
        return False
    if not matched.fingerprint_fields:
        return False
    if rules.merge_policy is not None:
        return False
    if rules.diff_policy is not None:
        return False
    desired_fingerprint = build_fingerprint_for_keys(desired_state, matched.fingerprint_fields)
    existing_fingerprint = build_fingerprint_for_keys(matched.existing, matched.fingerprint_fields)
    return desired_fingerprint == existing_fingerprint


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
    cache_gateway: ResolveRuntimePort,
    batch_index: dict[str, dict[str, list[str]]] | None,
) -> tuple[str | None, str | None, str | None]:
    """
    Назначение:
        Попытаться найти целевую запись по ключам связи.
    """
    used_lookup = None
    for key in rule.resolve_keys:
        value = key_values.get(key.name)
        if not value:
            continue
        lookup_key = format_identity_key(key.name, value)
        used_lookup = lookup_key
        candidates = _lookup_candidates(batch_index, cache_gateway, rule.target_dataset, lookup_key)
        if not candidates:
            continue
        if len(candidates) == 1:
            return candidates[0], None, used_lookup

        narrowed = _apply_dedup_rules(
            candidates,
            rule,
            key_values,
            desired_state,
            cache_gateway,
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
    cache_gateway: ResolveRuntimePort,
    batch_index: dict[str, dict[str, list[str]]] | None,
) -> list[str]:
    """
    Назначение:
        Сузить список кандидатов по дедуп-правилам.
    """
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
            ids = _lookup_candidates(batch_index, cache_gateway, rule.target_dataset, lookup_key)
            rule_candidates = rule_candidates.intersection(ids)
        if rule_candidates:
            remaining = rule_candidates
        if len(remaining) == 1:
            return list(remaining)
    return list(remaining)


def _lookup_candidates(
    batch_index: dict[str, dict[str, list[str]]] | None,
    cache_gateway: ResolveRuntimePort,
    dataset: str,
    lookup_key: str,
) -> list[str]:
    """
    Назначение:
        Получить кандидатов из batch_index или репозитория.
    """
    batch_hits = []
    if batch_index:
        batch_hits = batch_index.get(dataset, {}).get(lookup_key, [])
    if batch_hits:
        return list(dict.fromkeys(batch_hits))
    return cache_gateway.find_candidates(dataset, lookup_key)


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


def _max_attempts(settings: ResolverSettings | None) -> int:
    if settings is None:
        return 0
    return settings.pending_max_attempts


def _should_skip_int(rule: LinkFieldRule) -> bool:
    for key in rule.resolve_keys:
        if key.name == rule.target_id_field:
            return False
    return True


def _collect_batch_keys(link_rules: LinkRules, dataset: str) -> tuple[set[str], str]:
    """
    Назначение:
        Собрать ключи, нужные для batch-индекса.
    """
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


def _collect_changed_fields(
    before: dict[str, Any],
    after: dict[str, Any],
) -> set[str]:
    changed: set[str] = set()
    for key in set(before.keys()) | set(after.keys()):
        if before.get(key) != after.get(key):
            changed.add(key)
    return changed


def _extract_resolved_id(row: MatchedRow, id_field: str) -> str | None:
    if resolve_decision_status(row) == MatchDecisionStatus.MATCHED and row.existing:
        existing_id = row.existing.get(id_field)
        if existing_id is not None:
            return str(existing_id).strip()
    desired = row.desired_state
    if desired and id_field in desired and desired.get(id_field) is not None:
        return str(desired.get(id_field)).strip()
    if id_field == "_id" and row.target_id:
        return str(row.target_id).strip()
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
    """
    Назначение:
        Сериализовать pending-пейлоад в JSON.
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


def _serialize_candidate(candidate) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "target_id": candidate.target_id,
        "identity": candidate.identity,
        "score": candidate.score,
        "match_mode": candidate.match_mode,
        "evidence": candidate.evidence,
    }


def _serialize_secret_lifecycle(policy: SecretLifecyclePolicy | None) -> dict[str, Any] | None:
    if policy is None:
        return None
    return {
        "mode": policy.mode,
        "delete_on_success": bool(policy.delete_on_success),
        "ttl_seconds": policy.ttl_seconds,
    }


__all__ = ["ResolveCore"]
