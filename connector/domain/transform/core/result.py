from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Generic, Iterable, Mapping, TypeVar

from connector.domain.models import RowRef, DiagnosticItem
from connector.domain.transform.ids.match_key import MatchKey
from connector.domain.transform.core.source_record import SourceRecord

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class TransformResult(Generic[T]):
    """
    Назначение:
        Унифицированный результат transform-пайплайна для этапов collect/map/validate.
    """

    record: SourceRecord
    row: T | None
    row_ref: RowRef | None
    match_key: MatchKey | None
    meta: Mapping[str, Any] = field(default_factory=dict)
    secret_candidates: Mapping[str, str] = field(default_factory=dict)
    errors: tuple[DiagnosticItem, ...] = field(default_factory=tuple)
    warnings: tuple[DiagnosticItem, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "meta", _freeze_mapping(self.meta))
        object.__setattr__(self, "secret_candidates", _freeze_mapping(self.secret_candidates))
        object.__setattr__(self, "errors", tuple(self.errors))
        object.__setattr__(self, "warnings", tuple(self.warnings))

    @property
    def issues(self) -> tuple[DiagnosticItem, ...]:
        return (*self.errors, *self.warnings)

    def with_row(self, row: T | None) -> "TransformResult[T]":
        return replace(self, row=row)

    def with_row_ref(self, row_ref: RowRef | None) -> "TransformResult[T]":
        return replace(self, row_ref=row_ref)

    def with_match_key(self, match_key: MatchKey | None) -> "TransformResult[T]":
        return replace(self, match_key=match_key)

    def with_meta_update(self, update: Mapping[str, Any] | None) -> "TransformResult[T]":
        if not update:
            return self
        merged = dict(self.meta)
        merged.update(update)
        return replace(self, meta=merged)

    def with_secret_candidates(self, candidates: Mapping[str, str] | None) -> "TransformResult[T]":
        return replace(self, secret_candidates=dict(candidates or {}))

    def with_added_errors(self, errors: Iterable[DiagnosticItem]) -> "TransformResult[T]":
        if not errors:
            return self
        return replace(self, errors=(*self.errors, *tuple(errors)))

    def with_added_warnings(self, warnings: Iterable[DiagnosticItem]) -> "TransformResult[T]":
        if not warnings:
            return self
        return replace(self, warnings=(*self.warnings, *tuple(warnings)))

    def with_errors(self, errors: Iterable[DiagnosticItem]) -> "TransformResult[T]":
        return replace(self, errors=tuple(errors))

    def with_warnings(self, warnings: Iterable[DiagnosticItem]) -> "TransformResult[T]":
        return replace(self, warnings=tuple(warnings))

    def as_builder(self) -> "TransformResultBuilder[T]":
        return TransformResultBuilder(self)


@dataclass
class TransformResultBuilder(Generic[T]):
    """
    Назначение:
        Mutable builder для TransformResult (используется внутри стадии).
    """

    _base: TransformResult[T]
    record: SourceRecord | None = None
    row: T | None = None
    row_ref: RowRef | None = None
    match_key: MatchKey | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    secret_candidates: dict[str, str] = field(default_factory=dict)
    errors: list[DiagnosticItem] = field(default_factory=list)
    warnings: list[DiagnosticItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        base = self._base
        self.record = base.record
        self.row = base.row
        self.row_ref = base.row_ref
        self.match_key = base.match_key
        self.meta = dict(base.meta)
        self.secret_candidates = dict(base.secret_candidates)
        self.errors = list(base.errors)
        self.warnings = list(base.warnings)

    def add_error_item(self, item: DiagnosticItem) -> DiagnosticItem:
        self.errors.append(item)
        return item

    def add_warning_item(self, item: DiagnosticItem) -> DiagnosticItem:
        self.warnings.append(item)
        return item

    def update_meta(self, update: Mapping[str, Any] | None) -> "TransformResultBuilder[T]":
        if update:
            self.meta.update(update)
        return self

    def set_meta(self, key: str, value: Any) -> "TransformResultBuilder[T]":
        self.meta[key] = value
        return self

    def update_secret_candidates(self, update: Mapping[str, str] | None) -> "TransformResultBuilder[T]":
        if update:
            self.secret_candidates.update(update)
        return self

    def set_secret_candidate(self, key: str, value: str) -> "TransformResultBuilder[T]":
        self.secret_candidates[key] = value
        return self

    def set_row(self, row: T | None) -> "TransformResultBuilder[T]":
        self.row = row
        return self

    def set_row_ref(self, row_ref: RowRef | None) -> "TransformResultBuilder[T]":
        self.row_ref = row_ref
        return self

    def set_match_key(self, match_key: MatchKey | None) -> "TransformResultBuilder[T]":
        self.match_key = match_key
        return self

    def build(self) -> TransformResult[T]:
        return TransformResult(
            record=self.record or self._base.record,
            row=self.row,
            row_ref=self.row_ref,
            match_key=self.match_key,
            meta=self.meta,
            secret_candidates=self.secret_candidates,
            errors=tuple(self.errors),
            warnings=tuple(self.warnings),
        )


def _freeze_mapping(values: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not values:
        return MappingProxyType({})
    if isinstance(values, MappingProxyType):
        return values
    return MappingProxyType(dict(values))
