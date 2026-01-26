from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generic, Protocol, TypeVar

from connector.domain.models import DiagnosticStage, ValidationErrorItem
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord

T = TypeVar("T")

NormalizerParser = Callable[[Any, list[ValidationErrorItem], list[ValidationErrorItem]], Any]
NormalizerValidator = Callable[[Any, list[ValidationErrorItem], list[ValidationErrorItem]], None]


@dataclass(frozen=True)
class NormalizerRule:
    """
    Назначение:
        Декларативное правило нормализации одного поля.
    """

    target: str
    source_key: str
    parser: NormalizerParser | None = None
    validators: tuple[NormalizerValidator, ...] = ()
    required: bool = False

    def apply(self, values: dict[str, Any], errors: list[ValidationErrorItem], warnings: list[ValidationErrorItem]) -> Any:
        raw = values.get(self.source_key)
        if raw is None:
            if self.required:
                errors.append(
                    ValidationErrorItem(
                        stage=DiagnosticStage.NORMALIZE,
                        code="REQUIRED_FIELD_MISSING",
                        field=self.source_key,
                        message=f"{self.source_key} is required",
                    )
                )
            return None
        parsed = raw
        if self.parser:
            parsed = self.parser(raw, errors, warnings)
        for validator in self.validators:
            validator(parsed, errors, warnings)
        return parsed


class NormalizerSpec(Protocol, Generic[T]):
    """
    Назначение:
        Контракт набора правил нормализации для датасета.
    """

    rules: tuple[NormalizerRule, ...]

    def build_row(self, values: dict[str, Any]) -> T: ...


class Normalizer(Generic[T]):
    """
    Назначение:
        Ядро нормализатора: применяет правила и строит нормализованную строку.
    """

    def __init__(self, spec: NormalizerSpec[T]) -> None:
        self.spec = spec

    def normalize(self, record: SourceRecord) -> TransformResult[T]:
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []
        normalized_values: dict[str, Any] = {}

        for rule in self.spec.rules:
            normalized_values[rule.target] = rule.apply(record.values, errors, warnings)

        row = self.spec.build_row(normalized_values)
        return TransformResult(
            record=record,
            row=row,
            row_ref=None,
            match_key=None,
            secret_candidates={},
            errors=errors,
            warnings=warnings,
        )
