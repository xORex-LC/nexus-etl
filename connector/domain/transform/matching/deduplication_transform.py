"""
Назначение:
    Сопоставление записей внутри источника и с кэшем.
"""

from __future__ import annotations

from typing import Any, Iterable

from connector.domain.models import (
    DiagnosticStage,
    Identity,
    MatchStatus,
    RowRef,
    DiagnosticItem,
)
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.context import error as diag_error, warning as diag_warning
from connector.domain.transform.matching.context import MatchContext
from connector.domain.transform.matching.match_models import MatchedRow, build_fingerprint
from connector.domain.transform.matching.rules import IdentityRule, MatchingRules, ResolveRules
from connector.domain.ports.cache.identity import IdentityRepository
from connector.domain.ports.cache.repository import CacheRepositoryProtocol
from connector.domain.transform.core.result import TransformResult


class DeduplicationTransform:
    """
    Назначение/ответственность:
        Сопоставление валидированной строки с кэшем/target без принятия решений.
    """

    def __init__(
        self,
        dataset: str,
        cache_repo: CacheRepositoryProtocol,
        matching_rules: MatchingRules,
        resolve_rules: ResolveRules,
        include_deleted: bool,
        catalog: ErrorCatalog,
        identity_repo: IdentityRepository | None = None,
    ) -> None:
        self.dataset = dataset
        self.cache_repo = cache_repo
        self.matching_rules = matching_rules
        self.resolve_rules = resolve_rules
        self.include_deleted = include_deleted
        self.catalog = catalog
        self.identity_repo = identity_repo
        self._seen_source: dict[str, str] = {}
        self._runtime_scope: str | None = None

    def reset_source_dedup(self) -> None:
        """
        Назначение:
            Сбросить in-memory состояние source-dedup перед новым прогоном.
        """
        self._seen_source.clear()

    def bind_runtime_scope(self, scope: str | None) -> None:
        """
        Назначение:
            Подключить scoped runtime-state для source-dedup.
        """
        self._runtime_scope = scope

    def match_stream(self, enriched_source: Iterable[TransformResult[Any]]) -> Iterable[TransformResult[MatchedRow]]:
        """
        Назначение:
            Потоковый match + source-dedup внутри matcher-core.
        """
        self.reset_source_dedup()
        for enriched in enriched_source:
            yield self.match_with_source_dedup(enriched)

    def match_with_source_dedup(self, enriched: TransformResult[Any]) -> TransformResult[MatchedRow]:
        """
        Назначение:
            Выполнить match и применить source-dedup политики.
        """
        matched = self.match(enriched)
        if matched.row is None:
            return matched

        dedup_rules = self.matching_rules.source_dedup
        if not dedup_rules.enabled:
            return matched

        dedup_key = _build_source_dedup_key(
            self.dataset,
            matched.row.identity,
            allow_fallback=dedup_rules.fallback_identity_value,
        )
        if dedup_key is None:
            return matched

        prev_fingerprint = self._read_seen_fingerprint(dedup_key)
        if prev_fingerprint is None:
            self._write_seen_fingerprint(dedup_key, matched.row.fingerprint)
            return matched

        if prev_fingerprint == matched.row.fingerprint:
            warning = _build_source_duplicate_warning(self.catalog, matched.row)
            return _drop_matched_row(
                matched,
                warning=warning,
                drop_reason="duplicate_source",
            )

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

    def _read_seen_fingerprint(self, dedup_key: str) -> str | None:
        scope = self._runtime_scope
        if scope and self.identity_repo is not None:
            value = self.identity_repo.get_runtime_state(scope, self.dataset, dedup_key)
            if value is not None:
                return value
        return self._seen_source.get(dedup_key)

    def _write_seen_fingerprint(self, dedup_key: str, fingerprint: str) -> None:
        self._seen_source[dedup_key] = fingerprint
        scope = self._runtime_scope
        if scope and self.identity_repo is not None:
            self.identity_repo.set_runtime_state(scope, self.dataset, dedup_key, fingerprint)

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

        identity, existing, match_status, error = self._match_identity(row, match_context)
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

        links = {}
        if self.matching_rules.build_links:
            links = self.matching_rules.build_links(row, match_context)

        row_ref = _ensure_row_ref(match_context, identity, identity_value)
        matched_row = MatchedRow(
            row_ref=row_ref,
            identity=identity,
            match_status=match_status,
            desired_state=desired_state,
            existing=existing,
            fingerprint=fingerprint,
            fingerprint_fields=fingerprint_fields,
            source_links=links,
            target_id=getattr(row, "target_id", None),
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

    def _match_identity(
        self,
        row: Any,
        match_context: MatchContext,
    ) -> tuple[Identity | None, dict[str, Any] | None, MatchStatus, DiagnosticItem | None]:
        """
        Назначение:
            Выбрать identity и найденную запись из кэша.

        Алгоритм:
            - Перебирает правила identity (в приоритете явно заданные).
            - Возвращает конфликт при множественных кандидатах.
        """
        identity: Identity | None = None
        existing: dict[str, Any] | None = None
        match_status = MatchStatus.NOT_FOUND

        for rule in _iter_identity_rules(self.matching_rules):
            candidate = rule.build_identity(row, match_context)
            candidate_value = candidate.primary_value
            if not candidate_value:
                continue
            if identity is None:
                identity = candidate

            candidates = self.cache_repo.find(
                self.dataset,
                {candidate.primary: candidate_value},
                include_deleted=self.include_deleted,
            )
            if len(candidates) > 1:
                return (
                    identity,
                    None,
                    MatchStatus.NOT_FOUND,
                    _build_conflict_error(self.catalog, candidate, rule.name, match_context.row_ref),
                )
            if candidates:
                identity = candidate
                existing = candidates[0]
                match_status = MatchStatus.MATCHED
                return identity, existing, match_status, None

        if identity is None:
            return None, None, MatchStatus.NOT_FOUND, _build_identity_error(
                self.catalog,
                None,
                "identity value is empty",
                match_context.row_ref,
            )
        return identity, None, match_status, None


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


def _iter_identity_rules(matching_rules: MatchingRules) -> tuple[IdentityRule, ...]:
    """
    Назначение:
        Вернуть список правил identity с fallback на build_identity.
    """
    if matching_rules.identity_rules:
        return matching_rules.identity_rules
    return (
        IdentityRule(
            name="primary",
            build_identity=matching_rules.build_identity,
        ),
    )


def _extract_row_and_context(source: TransformResult[Any]) -> tuple[Any | None, MatchContext]:
    """
    Назначение:
        Построить единый match-контекст для matcher без ValidateStage.
    """
    row = source.row
    return row, _build_match_context(source, row)


def _build_source_dedup_key(
    dataset: str,
    identity: Identity,
    *,
    allow_fallback: bool,
) -> str | None:
    primary = (identity.primary or "").strip()
    value = (identity.primary_value or "").strip()
    if value == "":
        return None
    if primary:
        return f"{dataset}:{primary}:{value}"
    if allow_fallback:
        return f"{dataset}:_fallback:{value}"
    return None


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


def _build_match_context(source: TransformResult[Any], row: Any | None) -> MatchContext:
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
        usr_org_tab_num=getattr(row, "usr_org_tab_num", None),
        row_ref=row_ref,
        secret_candidates=dict(source.secret_candidates),
        secret_fields=secret_fields,
        errors=list(source.errors),
        warnings=list(source.warnings),
    )
