"""
Назначение:
    Сопоставление записей внутри источника и с кэшем.

    Source-dedup состояние вынесено в ISourceDedupStore (DI-зависимость).
    MatchCore не управляет lifecycle dedup-стора — reset() вызывается
    снаружи (PlanningPipeline) перед каждым прогоном.

Граница ответственности:
    MatchCore работает с generic MatchContext и row payload. Dataset-specific
    identity fields остаются в DSL/rule definitions и читаются из row, а не из
    runtime-контекста.
"""

from __future__ import annotations

from typing import Any, Iterable

from connector.domain.models import (
    DiagnosticStage,
    Identity,
    RowRef,
    DiagnosticItem,
)
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.context import error as diag_error, warning as diag_warning
from connector.domain.transform.matcher.context import MatchContext
from connector.domain.transform.matcher.match_models import (
    MatchCandidate,
    MatchDecision,
    MatchDecisionStatus,
    MatchDecisionReason,
    MatchedRow,
    build_fingerprint,
)
from connector.domain.transform_dsl.compilers.match import (
    FuzzyScoringRules,
    MatchingRules,
)
from connector.domain.transform_dsl.compilers.resolve import ResolveRules
from connector.domain.transform.matcher.scoring import is_tie, rank_candidates
from connector.domain.ports.cache.roles import MatchRuntimePort
from connector.domain.transform.matcher.ports import ISourceDedupStore
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.common.values import read_field_value


class MatchCore:
    """
    Назначение/ответственность:
        Ядро матчинга: сопоставление валидированной строки с кэшем/target
        без принятия решений apply/resolve.

    Граница ответственности:
        - Owns: identity lookup, fuzzy scoring, source-dedup policy.
        - Does NOT: управлять lifecycle dedup-стора — reset() вызывается
          снаружи (PlanningPipeline) перед каждым прогоном.
        - Does NOT: знать о scoped runtime state или dataset-prefix в ключах.

    Зависимости (инжектируются через __init__):
        dedup_store — ISourceDedupStore: хранит и проверяет source-dedup состояние.
    """

    def __init__(
        self,
        dataset: str,
        cache_gateway: MatchRuntimePort,
        matching_rules: MatchingRules,
        resolve_rules: ResolveRules,
        include_deleted: bool,
        catalog: ErrorCatalog,
        dedup_store: ISourceDedupStore,
    ) -> None:
        self.dataset = dataset
        self.cache_gateway = cache_gateway
        self.matching_rules = matching_rules
        if not self.matching_rules.identity_rules:
            raise ValueError("matching identity_rules must not be empty")
        self.resolve_rules = resolve_rules
        self.include_deleted = include_deleted
        self.catalog = catalog
        self._dedup_store = dedup_store

    def match_stream(self, enriched_source: Iterable[TransformResult[Any]]) -> Iterable[TransformResult[MatchedRow]]:
        """
        Назначение:
            Потоковый match + source-dedup.

        Инвариант:
            reset() dedup_store — ответственность PlanningPipeline,
            не вызывается здесь.
        """
        for enriched in enriched_source:
            yield self.match_with_source_dedup(enriched)

    def match_with_source_dedup(self, enriched: TransformResult[Any]) -> TransformResult[MatchedRow]:
        """
        Назначение:
            Выполнить match и применить source-dedup политики через dedup_store.
        """
        matched = self.match(enriched)
        if matched.row is None:
            return matched

        dedup_rules = self.matching_rules.source_dedup
        if not dedup_rules.enabled:
            return matched

        dedup_key = _build_source_dedup_key(matched.row.identity)
        if dedup_key is None:
            return matched

        outcome = self._dedup_store.check_and_register(dedup_key, matched.row.fingerprint)
        if outcome.is_first:
            return matched

        if outcome.is_duplicate:
            warning = _build_source_duplicate_warning(self.catalog, matched.row)
            return _drop_matched_row(
                matched,
                warning=warning,
                drop_reason="duplicate_source",
            )

        # outcome.is_conflict
        if dedup_rules.on_conflict == "warn":
            warning = _build_source_conflict_warning(self.catalog, matched.row)
            return _drop_matched_row(
                matched,
                warning=warning,
                drop_reason="conflict_source",
            )

        error = _build_source_conflict_error(self.catalog, matched.row)
        return _drop_matched_row(
            matched,
            error=error,
            drop_reason="conflict_source",
        )

    def match(self, enriched: TransformResult[Any]) -> TransformResult[MatchedRow]:
        """
        Назначение:
            Построить MatchedRow по строке после enrich.

        Алгоритм:
            - Определяет identity по правилам.
            - Ищет кандидатов в кэше.
            - Формирует desired_state и fingerprint.
        """
        row, match_context = _extract_row_and_context(enriched)
        if row is None:
            extra_errors = ()
            if not enriched.errors:
                extra_errors = (
                    _make_match_error(
                        self.catalog,
                        "MATCH_IDENTITY_MISSING",
                        None,
                        "empty enriched row",
                        match_context.row_ref,
                    ),
                )
            return TransformResult(
                record=enriched.record,
                row=None,
                row_ref=match_context.row_ref,
                match_key=enriched.match_key,
                meta=enriched.meta,
                secret_candidates=enriched.secret_candidates,
                errors=(*enriched.errors, *extra_errors),
                warnings=enriched.warnings,
            )

        identity, existing, decision_status, error = self._match_identity(row, match_context)
        if error is not None:
            return TransformResult(
                record=enriched.record,
                row=None,
                row_ref=match_context.row_ref,
                match_key=enriched.match_key,
                meta=enriched.meta,
                secret_candidates=enriched.secret_candidates,
                errors=(*enriched.errors, error),
                warnings=enriched.warnings,
            )

        identity_value = identity.primary_value if identity else None
        if not identity or not identity_value:
            return TransformResult(
                record=enriched.record,
                row=None,
                row_ref=match_context.row_ref,
                match_key=enriched.match_key,
                meta=enriched.meta,
                secret_candidates=enriched.secret_candidates,
                errors=(
                    *enriched.errors,
                    _make_match_error(
                        self.catalog,
                        "MATCH_IDENTITY_MISSING",
                        None,
                        "identity value is empty",
                        match_context.row_ref,
                    ),
                ),
                warnings=enriched.warnings,
            )

        desired_state = self.resolve_rules.build_desired_state(row, match_context)
        fingerprint, fingerprint_fields = build_fingerprint(
            desired_state,
            ignored_fields=self.matching_rules.ignored_fields,
        )
        match_mode = "exact"
        score: float | None = None
        decision_reason: str | None = None
        top_candidates: tuple[dict[str, Any], ...] = ()

        if decision_status == MatchDecisionStatus.MATCHED:
            score = 1.0
            decision_reason = MatchDecisionReason.IDENTITY_EXACT
            top_candidates = self._build_top_candidates(
                [(existing, score)] if existing is not None else [],
                top_k=max(1, self.matching_rules.fuzzy.top_k),
            )
            decision_status = MatchDecisionStatus.MATCHED
        elif self.matching_rules.fuzzy.enabled:
            (
                existing,
                decision_status,
                score,
                decision_reason,
                top_candidates,
            ) = self._match_with_fuzzy(
                row=row,
                desired_state=desired_state,
                identity=identity,
            )
            match_mode = "fuzzy"
        else:
            decision_reason = MatchDecisionReason.IDENTITY_NOT_FOUND
            decision_status = MatchDecisionStatus.NOT_FOUND

        links = {}
        if self.matching_rules.build_links:
            links = self.matching_rules.build_links(row, match_context)

        decision_candidates = _to_match_candidates(
            top_candidates,
            match_mode=match_mode,
        )
        selected_candidate = None
        if decision_status == MatchDecisionStatus.MATCHED:
            selected_candidate = _build_selected_candidate(
                existing=existing,
                identity=identity,
                score=score,
                match_mode=match_mode,
            )
            if selected_candidate is not None and not decision_candidates:
                decision_candidates = (selected_candidate,)
        match_decision = MatchDecision(
            status=decision_status,
            reason_code=decision_reason or MatchDecisionReason.IDENTITY_NOT_FOUND,
            selected=selected_candidate,
            candidates=decision_candidates,
            score=score,
            meta={"match_mode": match_mode},
        )

        row_ref = _ensure_row_ref(match_context, identity, identity_value)
        matched_row = MatchedRow(
            row_ref=row_ref,
            identity=identity,
            desired_state=desired_state,
            existing=existing,
            fingerprint=fingerprint,
            fingerprint_fields=fingerprint_fields,
            source_links=links,
            target_id=read_field_value(row, "target_id"),
            match_decision=match_decision,
        )

        return TransformResult(
            record=enriched.record,
            row=matched_row,
            row_ref=row_ref,
            match_key=enriched.match_key,
            meta=enriched.meta,
            secret_candidates=enriched.secret_candidates,
            errors=enriched.errors,
            warnings=enriched.warnings,
        )

    def _match_with_fuzzy(
        self,
        *,
        row: Any,
        desired_state: dict[str, Any],
        identity: Identity,
    ) -> tuple[
        dict[str, Any] | None,
        MatchDecisionStatus,
        float | None,
        str,
        tuple[dict[str, Any], ...],
    ]:
        fuzzy = self.matching_rules.fuzzy
        candidates = self._collect_blocking_candidates(
            row=row,
            desired_state=desired_state,
            identity=identity,
            fuzzy=fuzzy,
        )
        if not candidates:
            return (
                None,
                MatchDecisionStatus.NOT_FOUND,
                None,
                MatchDecisionReason.FUZZY_NO_CANDIDATES,
                (),
            )

        source_values = self._build_source_values(
            row=row,
            desired_state=desired_state,
            identity=identity,
            fuzzy=fuzzy,
        )
        ranked = rank_candidates(
            source_values,
            candidates,
            comparators=fuzzy.comparators,
            weights=fuzzy.weights,
            score_round=max(0, fuzzy.score_round),
        )
        if not ranked:
            return None, MatchDecisionStatus.NOT_FOUND, None, MatchDecisionReason.FUZZY_NO_RANKED, ()

        top_candidates = self._build_top_candidates(
            [(item.candidate, item.score) for item in ranked],
            top_k=max(1, fuzzy.top_k),
        )
        best = ranked[0]
        if is_tie(ranked, tie_delta=max(0.0, fuzzy.tie_delta)):
            return (
                None,
                MatchDecisionStatus.AMBIGUOUS,
                best.score,
                MatchDecisionReason.FUZZY_TIE,
                top_candidates,
            )

        accept_threshold = min(1.0, max(0.0, float(fuzzy.accept_threshold)))
        review_threshold = min(accept_threshold, max(0.0, float(fuzzy.review_threshold)))
        if best.score >= accept_threshold:
            return (
                best.candidate,
                MatchDecisionStatus.MATCHED,
                best.score,
                MatchDecisionReason.FUZZY_ACCEPT,
                top_candidates,
            )
        if best.score >= review_threshold:
            return (
                None,
                MatchDecisionStatus.AMBIGUOUS,
                best.score,
                MatchDecisionReason.FUZZY_REVIEW,
                top_candidates,
            )
        return (
            None,
            MatchDecisionStatus.NOT_FOUND,
            best.score,
            MatchDecisionReason.FUZZY_REJECT,
            top_candidates,
        )

    def _collect_blocking_candidates(
        self,
        *,
        row: Any,
        desired_state: dict[str, Any],
        identity: Identity,
        fuzzy: FuzzyScoringRules,
    ) -> list[dict[str, Any]]:
        if not fuzzy.blocking_keys:
            return []

        found: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        limit = max(1, int(fuzzy.max_candidates))

        for key_name in fuzzy.blocking_keys:
            key_value = _read_value(
                key_name,
                row=row,
                desired_state=desired_state,
                identity=identity,
            )
            if key_value in (None, ""):
                continue
            try:
                matches = self.cache_gateway.find(
                    self.dataset,
                    {key_name: key_value},
                    include_deleted=self.include_deleted,
                )
            except ValueError:
                # Transitional mode: skip unknown blocking keys silently.
                continue
            for item in matches:
                candidate_key = _candidate_dedup_key(item)
                if candidate_key in seen_keys:
                    continue
                seen_keys.add(candidate_key)
                found.append(item)
                if len(found) >= limit:
                    return found
        return found

    def _build_source_values(
        self,
        *,
        row: Any,
        desired_state: dict[str, Any],
        identity: Identity,
        fuzzy: FuzzyScoringRules,
    ) -> dict[str, Any]:
        fields = set(fuzzy.comparators.keys()) | set(fuzzy.weights.keys())
        values: dict[str, Any] = {}
        for field in fields:
            values[field] = _read_value(
                field,
                row=row,
                desired_state=desired_state,
                identity=identity,
            )
        return values

    def _build_top_candidates(
        self,
        ranked: list[tuple[dict[str, Any], float]],
        *,
        top_k: int,
    ) -> tuple[dict[str, Any], ...]:
        items: list[dict[str, Any]] = []
        for candidate, candidate_score in ranked[:top_k]:
            target_id = candidate.get("_id") or candidate.get("target_id")
            items.append(
                {
                    "target_id": str(target_id) if target_id is not None else None,
                    "score": candidate_score,
                }
            )
        return tuple(items)

    def _match_identity(
        self,
        row: Any,
        match_context: MatchContext,
    ) -> tuple[Identity | None, dict[str, Any] | None, MatchDecisionStatus, DiagnosticItem | None]:
        """
        Назначение:
            Выбрать identity и найденную запись из кэша.

        Алгоритм:
            - Перебирает правила identity (в приоритете явно заданные).
            - Возвращает конфликт при множественных кандидатах.
        """
        identity: Identity | None = None
        existing: dict[str, Any] | None = None
        decision_status = MatchDecisionStatus.NOT_FOUND

        for rule in self.matching_rules.identity_rules:
            candidate = rule.build_identity(row, match_context)
            candidate_value = candidate.primary_value
            if not candidate_value:
                continue
            if identity is None:
                identity = candidate

            candidates = self.cache_gateway.find(
                self.dataset,
                {candidate.primary: candidate_value},
                include_deleted=self.include_deleted,
            )
            if len(candidates) > 1:
                return (
                    identity,
                    None,
                    MatchDecisionStatus.NOT_FOUND,
                    _build_conflict_error(self.catalog, candidate, rule.name, match_context.row_ref),
                )
            if candidates:
                identity = candidate
                existing = candidates[0]
                decision_status = MatchDecisionStatus.MATCHED
                return identity, existing, decision_status, None

        if identity is None:
            return None, None, MatchDecisionStatus.NOT_FOUND, _build_identity_error(
                self.catalog,
                None,
                "identity value is empty",
                match_context.row_ref,
            )
        return identity, None, decision_status, None


def _make_match_error(
    catalog: ErrorCatalog,
    code: str,
    field: str | None,
    message: str,
    record_ref: RowRef | None,
) -> DiagnosticItem:
    """
    Назначение:
        Сформировать диагностическую ошибку match-стадии.
    """
    return diag_error(
        catalog=catalog,
        stage=DiagnosticStage.MATCH,
        code=code,
        field=field,
        message=message,
        record_ref=record_ref,
    )


def _ensure_row_ref(match_context: MatchContext, identity: Identity, identity_value: str) -> RowRef:
    """
    Назначение:
        Гарантировать row_ref с актуальным identity.
    """
    row_ref = match_context.row_ref
    if row_ref is None:
        return RowRef(
            line_no=match_context.line_no,
            row_id=f"line:{match_context.line_no}",
            identity_primary=identity.primary,
            identity_value=identity_value,
        )
    if row_ref.identity_primary == identity.primary and row_ref.identity_value == identity_value:
        return row_ref
    return RowRef(
        line_no=row_ref.line_no,
        row_id=row_ref.row_id,
        identity_primary=identity.primary,
        identity_value=identity_value,
    )


def _build_identity_error(
    catalog: ErrorCatalog,
    identity: Identity | None,
    message: str,
    record_ref: RowRef | None,
) -> DiagnosticItem:
    """
    Назначение:
        Ошибка отсутствия identity.
    """
    return diag_error(
        catalog=catalog,
        stage=DiagnosticStage.MATCH,
        code="MATCH_IDENTITY_MISSING",
        field=identity.primary if identity else None,
        message=message,
        record_ref=record_ref,
    )


def _build_conflict_error(
    catalog: ErrorCatalog,
    identity: Identity,
    rule_name: str | None = None,
    record_ref: RowRef | None = None,
) -> DiagnosticItem:
    """
    Назначение:
        Ошибка конфликта identity (несколько кандидатов).
    """
    suffix = f" ({rule_name})" if rule_name else ""
    return diag_error(
        catalog=catalog,
        stage=DiagnosticStage.MATCH,
        code="MATCH_CONFLICT_TARGET",
        field=identity.primary,
        message=f"multiple existing candidates found{suffix}",
        record_ref=record_ref,
    )


def _extract_row_and_context(source: TransformResult[Any]) -> tuple[Any | None, MatchContext]:
    """
    Назначение:
        Построить единый match-контекст для matcher без ValidateStage.
    """
    row = source.row
    return row, _build_match_context(source)


def _build_source_dedup_key(identity: Identity) -> str | None:
    """
    Назначение:
        Построить ключ дедупликации из identity без dataset-prefix.

    Dataset-prefix убран: изоляция прогонов обеспечивается через
    reset() dedup_store перед каждым прогоном (PlanningPipeline),
    а не через namespace в ключе.
    """
    primary = (identity.primary or "").strip()
    value = (identity.primary_value or "").strip()
    if value == "":
        return None
    if primary == "":
        return None
    return f"{primary}:{value}"


def _read_value(
    field: str,
    *,
    row: Any,
    desired_state: dict[str, Any],
    identity: Identity,
) -> Any:
    if field in desired_state:
        return desired_state.get(field)
    if field == identity.primary:
        return identity.primary_value
    return read_field_value(row, field)


def _candidate_dedup_key(candidate: dict[str, Any]) -> str:
    target_id = candidate.get("_id") or candidate.get("target_id")
    if target_id is not None:
        return f"id:{target_id}"
    parts = [f"{k}={candidate.get(k)}" for k in sorted(candidate.keys())]
    return "|".join(parts)


def _to_match_candidates(
    top_candidates: tuple[dict[str, Any], ...],
    *,
    match_mode: str,
) -> tuple[MatchCandidate, ...]:
    candidates: list[MatchCandidate] = []
    for item in top_candidates:
        candidates.append(
            MatchCandidate(
                target_id=str(item.get("target_id")) if item.get("target_id") is not None else None,
                identity=None,
                score=float(item.get("score")) if item.get("score") is not None else None,
                match_mode=match_mode,
                evidence=None,
            )
        )
    return tuple(candidates)


def _build_selected_candidate(
    *,
    existing: dict[str, Any] | None,
    identity: Identity,
    score: float | None,
    match_mode: str,
) -> MatchCandidate | None:
    if existing is None:
        return None
    target_id = existing.get("_id") or existing.get("target_id")
    return MatchCandidate(
        target_id=str(target_id) if target_id is not None else None,
        identity=identity.primary_value or None,
        score=score,
        match_mode=match_mode,
        evidence={"identity_primary": identity.primary},
    )


def _drop_matched_row(
    matched: TransformResult[MatchedRow],
    *,
    warning: DiagnosticItem | None = None,
    error: DiagnosticItem | None = None,
    drop_reason: str,
) -> TransformResult[MatchedRow]:
    builder = matched.as_builder()
    builder.set_row(None)
    builder.set_meta("match_drop_reason", drop_reason)
    if warning is not None:
        builder.add_warning_item(warning)
    if error is not None:
        builder.add_error_item(error)
    return builder.build()


def _build_source_duplicate_warning(catalog: ErrorCatalog, row: MatchedRow) -> DiagnosticItem:
    return diag_warning(
        catalog=catalog,
        stage=DiagnosticStage.MATCH,
        code="MATCH_DUPLICATE_SOURCE",
        field=row.identity.primary,
        message="duplicate row in source batch",
        record_ref=row.row_ref,
    )


def _build_source_conflict_warning(catalog: ErrorCatalog, row: MatchedRow) -> DiagnosticItem:
    return diag_warning(
        catalog=catalog,
        stage=DiagnosticStage.MATCH,
        code="MATCH_CONFLICT_SOURCE",
        field=row.identity.primary,
        message="conflicting rows in source batch",
        record_ref=row.row_ref,
    )


def _build_source_conflict_error(catalog: ErrorCatalog, row: MatchedRow) -> DiagnosticItem:
    return diag_error(
        catalog=catalog,
        stage=DiagnosticStage.MATCH,
        code="MATCH_CONFLICT_SOURCE",
        field=row.identity.primary,
        message="conflicting rows in source batch",
        record_ref=row.row_ref,
    )


def _build_match_context(source: TransformResult[Any]) -> MatchContext:
    """
    Назначение:
        Собрать generic runtime context для matcher/resolver.

    Инвариант:
        Dataset-specific row fields не проецируются в MatchContext и должны
        читаться из row через compiled identity rules.
    """
    match_key_value = source.match_key.value if source.match_key else ""
    row_ref = source.row_ref or RowRef(
        line_no=source.record.line_no,
        row_id=source.record.record_id,
        identity_primary="match_key",
        identity_value=match_key_value or None,
    )
    if row_ref.identity_primary is None:
        row_ref = RowRef(
            line_no=row_ref.line_no,
            row_id=row_ref.row_id,
            identity_primary="match_key",
            identity_value=match_key_value or None,
        )
    meta_secret_fields = source.meta.get("secret_fields") if source.meta else None
    secret_fields: list[str] = []
    if isinstance(meta_secret_fields, (list, tuple, set)):
        secret_fields = [str(item) for item in meta_secret_fields if item]
    if not secret_fields and source.secret_candidates:
        secret_fields = list(source.secret_candidates.keys())
    return MatchContext(
        line_no=source.record.line_no,
        match_key=match_key_value,
        match_key_complete=source.match_key is not None,
        row_ref=row_ref,
        secret_candidates=dict(source.secret_candidates),
        secret_fields=secret_fields,
        errors=list(source.errors),
        warnings=list(source.warnings),
    )
