"""
Назначение:
    MapperCore: бизнес-логика применения DSL-правил маппинга.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.models import DiagnosticItem, DiagnosticStage
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.dsl.engine import TransformationEngine
from connector.domain.transform.dsl.issues import DslIssue, DslSeverity
from connector.domain.transform.dsl.diagnostics import append_dsl_issues
from connector.domain.transform.dsl.helpers import apply_ops
from connector.domain.transform.common.values import read_value
from connector.domain.transform.dsl.specs import MappingRule, MetaRule, MappingSpec, SinkSpec
from connector.domain.transform.common.sink_schema import validate_sink_row


@dataclass
class MappingOutcome:
    """
    Назначение:
        Внутренний результат маппинга до преобразования в TransformResult.
    """

    row: dict[str, Any] | None
    meta: dict[str, Any]
    errors: list[DiagnosticItem]
    warnings: list[DiagnosticItem]


class MapperCore:
    """
    Назначение/ответственность:
        Применить mapping-правила DSL к SourceRecord.
    """

    def __init__(
        self,
        spec: MappingSpec,
        engine: TransformationEngine,
        *,
        sink_spec: SinkSpec | None = None,
    ) -> None:
        self.spec = spec
        self.engine = engine
        self._source_index = {name: idx for idx, name in enumerate(spec.source_columns or [])}
        self.sink_spec = sink_spec

    def map_record(self, record: SourceRecord, *, catalog: ErrorCatalog) -> TransformResult[Mapping[str, Any]]:
        """
        Назначение:
            Преобразовать SourceRecord в TransformResult с mapped-строкой.
        """
        outcome = self._apply_rules(record, catalog)
        return TransformResult(
            record=record,
            row=outcome.row,
            row_ref=None,
            match_key=None,
            meta=outcome.meta,
            secret_candidates={},
            errors=tuple(outcome.errors),
            warnings=tuple(outcome.warnings),
        )

    def _apply_rules(self, record: SourceRecord, catalog: ErrorCatalog) -> MappingOutcome:
        row: dict[str, Any] = {}
        meta: dict[str, Any] = {}
        errors: list[DiagnosticItem] = []
        warnings: list[DiagnosticItem] = []

        for rule in self.spec.mapping.rules:
            value, issues = self._resolve_rule_value(record, row, rule)
            self._append_issues(issues, errors, warnings, rule, catalog, record)
            if issues and any(issue.severity == DslSeverity.ERROR for issue in issues):
                # если правило провалилось, не пытаемся назначать цель
                continue
            self._assign_targets(row, rule, value, errors, warnings, catalog, record)

        # post-validate результата mapping
        self._validate_schema(row, errors, warnings, catalog, record)
        self._validate_sink(row, errors, warnings, catalog, record)

        # meta rules
        if not errors:
            for meta_rule in self.spec.mapping.meta:
                meta_value, issues = self._resolve_meta_value(record, row, meta_rule)
                self._append_meta_issues(issues, errors, warnings, meta_rule, catalog, record)
                if issues and any(issue.severity == DslSeverity.ERROR for issue in issues):
                    continue
                if meta_value is not None:
                    self._set_meta(meta, meta_rule.target, meta_value)

        final_row: dict[str, Any] | None = row
        if errors:
            final_row = None

        return MappingOutcome(
            row=final_row,
            meta=meta,
            errors=errors,
            warnings=warnings,
        )

    def _resolve_rule_value(
        self,
        record: SourceRecord,
        row: Mapping[str, Any],
        rule: MappingRule,
    ) -> tuple[Any, list[DslIssue]]:
        issues: list[DslIssue] = []
        if rule.sources:
            values: list[Any] = []
            for name in rule.sources:
                value, exists = self._read_source(record, name)
                if not exists:
                    issues.append(
                        DslIssue(
                            code="missing_source_column",
                            message=f"Missing source column '{name}'",
                            field=name,
                            severity=DslSeverity.ERROR,
                        )
                    )
                values.append(value)
            value = values
        else:
            value, exists = self._read_source(record, rule.source)
            if not exists and rule.source is not None:
                issues.append(
                    DslIssue(
                        code="missing_source_column",
                        message=f"Missing source column '{rule.source}'",
                        field=rule.source,
                        severity=DslSeverity.ERROR,
                    )
                )
        if rule.ops:
            resolved, op_issues = apply_ops(self.engine, value, rule.ops)
            issues.extend(op_issues)
            return resolved, issues
        return value, issues

    def _resolve_meta_value(
        self,
        record: SourceRecord,
        row: Mapping[str, Any],
        rule: MetaRule,
    ) -> tuple[Any, list[DslIssue]]:
        if rule.sources:
            values = [read_value(record_values=record.values, row_values=row, path=name) for name in rule.sources]
            value = values
        elif rule.source:
            value = read_value(record_values=record.values, row_values=row, path=rule.source)
        else:
            value = None
        if rule.ops:
            resolved, op_issues = apply_ops(self.engine, value, rule.ops)
            return resolved, list(op_issues)
        return value, []

    def _read_source(self, record: SourceRecord, name: str | None) -> tuple[Any, bool]:
        if name is None:
            return None, False
        raw = record.values
        if name in raw:
            return raw.get(name), True
        index = self._source_index.get(name)
        if index is not None:
            alt = f"col_{index}"
            if alt in raw:
                return raw.get(alt), True
        return None, False

    def _assign_targets(
        self,
        row: dict[str, Any],
        rule: MappingRule,
        value: Any,
        errors: list[DiagnosticItem],
        warnings: list[DiagnosticItem],
        catalog: ErrorCatalog,
        record: SourceRecord,
    ) -> None:
        targets = rule.targets or ([] if rule.target is None else [rule.target])
        if not targets:
            return
        if rule.targets:
            if isinstance(value, dict):
                for target in targets:
                    row[target] = value.get(target)
            elif isinstance(value, (list, tuple)):
                for idx, target in enumerate(targets):
                    row[target] = value[idx] if idx < len(value) else None
            else:
                for target in targets:
                    row[target] = value
        else:
            row[targets[0]] = value

        if rule.required:
            for target in targets:
                if not _is_present(row.get(target)):
                    self._append_issue(
                        errors,
                        warnings,
                        rule,
                        catalog,
                        record,
                        DslIssue(
                            code="REQUIRED_FIELD_MISSING",
                            message=f"{target} is required",
                            field=target,
                            severity=DslSeverity.ERROR,
                        ),
                    )

    def _validate_schema(
        self,
        row: Mapping[str, Any],
        errors: list[DiagnosticItem],
        warnings: list[DiagnosticItem],
        catalog: ErrorCatalog,
        record: SourceRecord,
    ) -> None:
        schema = self.spec.mapping.schema_
        if schema is None:
            return
        for field in schema.required:
            if not _is_present(row.get(field)):
                self._append_issue(
                    errors,
                    warnings,
                    None,
                    catalog,
                    record,
                    DslIssue(
                        code="REQUIRED_FIELD_MISSING",
                        message=f"{field} is required",
                        field=field,
                        severity=DslSeverity.ERROR,
                    ),
                )

    def _validate_sink(
        self,
        row: Mapping[str, Any],
        errors: list[DiagnosticItem],
        warnings: list[DiagnosticItem],
        catalog: ErrorCatalog,
        record: SourceRecord,
    ) -> None:
        if self.sink_spec is None:
            return
        issues = validate_sink_row(row, self.sink_spec, check_types=False)
        if issues:
            append_dsl_issues(
                errors=errors,
                warnings=warnings,
                issues=issues,
                stage=DiagnosticStage.MAP,
                catalog=catalog,
                record_ref=None,
                on_error="warn",
            )

    def _append_issues(
        self,
        issues: Iterable[DslIssue],
        errors: list[DiagnosticItem],
        warnings: list[DiagnosticItem],
        rule: MappingRule,
        catalog: ErrorCatalog,
        record: SourceRecord,
    ) -> None:
        append_dsl_issues(
            errors=errors,
            warnings=warnings,
            issues=issues,
            stage=DiagnosticStage.MAP,
            catalog=catalog,
            record_ref=None,
            on_error=getattr(rule, "on_error", "error"),
        )

    def _append_meta_issues(
        self,
        issues: Iterable[DslIssue],
        errors: list[DiagnosticItem],
        warnings: list[DiagnosticItem],
        rule: MetaRule,
        catalog: ErrorCatalog,
        record: SourceRecord,
    ) -> None:
        append_dsl_issues(
            errors=errors,
            warnings=warnings,
            issues=issues,
            stage=DiagnosticStage.MAP,
            catalog=catalog,
            record_ref=None,
            on_error=getattr(rule, "on_error", "error"),
        )

    def _set_meta(self, meta: dict[str, Any], path: str, value: Any) -> None:
        parts = path.split(".")
        current = meta
        for key in parts[:-1]:
            current = current.setdefault(key, {})
        current[parts[-1]] = value


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True
