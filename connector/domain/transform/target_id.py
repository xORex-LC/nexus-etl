from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from connector.domain.models import DiagnosticStage, ValidationErrorItem
from connector.domain.transform.enricher import EnrichRule

T = TypeVar("T")
D = TypeVar("D")


class TargetIdMode:
    """
    Назначение:
        Режим обработки target_id.
    """

    REQUIRED = "required"
    OPTIONAL = "optional"
    NONE = "none"


@dataclass(frozen=True)
class TargetIdPolicy(Generic[D]):
    """
    Назначение:
        Политика формирования target_id для конкретного датасета.
    """

    field_name: str = "target_id"
    mode: str = TargetIdMode.REQUIRED
    allow_source_value: bool = True
    generator: Callable[[], str] | None = None
    exists: Callable[[D, str], bool] | None = None
    max_attempts: int = 3


@dataclass(frozen=True)
class TargetIdRule(EnrichRule[T, D]):
    """
    Назначение:
        Универсальное правило формирования target_id по политике датасета.
    """

    policy: TargetIdPolicy[D]
    name: str = "target_id"

    def apply(self, result, deps, errors, warnings) -> None:
        _ = warnings
        row = result.row
        if row is None:
            return
        if self.policy.mode == TargetIdMode.NONE:
            return

        field = self.policy.field_name
        current = getattr(row, field, None)
        candidate = None
        if current is not None and self.policy.allow_source_value:
            candidate = str(current).strip() or None

        if candidate is None:
            if self.policy.generator is None:
                if self.policy.mode == TargetIdMode.REQUIRED:
                    errors.append(
                        ValidationErrorItem(
                            stage=DiagnosticStage.ENRICH,
                            code="TARGET_ID_MISSING",
                            field=field,
                            message="target_id is required",
                        )
                    )
                return
            candidate = self.policy.generator()

        attempts = 0
        max_attempts = max(1, self.policy.max_attempts)
        while attempts < max_attempts:
            if candidate is None:
                if self.policy.generator is None:
                    break
                candidate = self.policy.generator()
            if self.policy.exists is not None and self.policy.exists(deps, candidate):
                candidate = None
                attempts += 1
                continue
            setattr(row, field, candidate)
            return

        errors.append(
            ValidationErrorItem(
                stage=DiagnosticStage.ENRICH,
                code="TARGET_ID_CONFLICT",
                field=field,
                message="unable to generate unique target_id",
            )
        )


__all__ = ["TargetIdMode", "TargetIdPolicy", "TargetIdRule"]
