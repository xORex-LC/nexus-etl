"""
TargetSpec — декларативная спецификация target-системы на domain-уровне.

Назначение:
    Декларативное описание target: возможности, правила классификации ошибок
    (`fault_rules`), retry-политики (`retry_rules`), правила безопасного
    логирования (`redaction`), каталог operation aliases.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TargetFaultKind = Literal[
    "SPEC",
    "AUTH",
    "PERMISSION",
    "DATA",
    "NOT_FOUND",
    "CONFLICT",
    "THROTTLE",
    "TRANSIENT",
    "UNKNOWN",
]
TargetCapability = Literal["check", "execute", "read_paged"]
RetryDirective = Literal["NO_RETRY", "RETRY_BACKOFF", "RETRY_AFTER", "ESCALATE"]


class _SpecModel(BaseModel):
    """Базовая модель spec-слоя: неизменяемая и строгая."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class FaultRule(_SpecModel):
    """Правило классификации: HTTP статус / error code -> FaultKind."""

    fault_kind: TargetFaultKind
    match_status: int | None = None
    match_status_range: tuple[int, int] | None = None
    match_error_code: str | None = None

    @model_validator(mode="after")
    def _validate_matcher(self) -> "FaultRule":
        has_matcher = (
            self.match_status is not None
            or self.match_status_range is not None
            or self.match_error_code is not None
        )
        if not has_matcher:
            raise ValueError("fault rule requires match_status, match_status_range or match_error_code")
        if self.match_status is not None and self.match_status_range is not None:
            raise ValueError("fault rule cannot define both match_status and match_status_range")
        if self.match_status_range is not None:
            low, high = self.match_status_range
            if low > high:
                raise ValueError("fault rule status range must be ordered")
        return self


class RetryRule(_SpecModel):
    """Правило реакции: FaultKind / статус -> RetryDirective."""

    directive: RetryDirective
    match_fault: TargetFaultKind | None = None
    match_status: int | None = None
    match_reason: str | None = None
    mutation: str | None = None

    @model_validator(mode="after")
    def _validate_matcher(self) -> "RetryRule":
        if self.match_fault is None and self.match_status is None and self.match_reason is None:
            raise ValueError("retry rule requires match_fault, match_status or match_reason")
        if self.match_reason is not None:
            reason = self.match_reason.strip().lower()
            if reason == "":
                raise ValueError("retry rule match_reason must not be empty")
            object.__setattr__(self, "match_reason", reason)
        if self.mutation is not None:
            mutation = self.mutation.strip()
            if mutation == "":
                raise ValueError("retry rule mutation must not be empty")
            object.__setattr__(self, "mutation", mutation)
        return self


class RetryConfig(_SpecModel):
    """Параметры механики retry (backoff, jitter, лимиты)."""

    # `max_attempts` — число повторов (не включая базовую первую попытку).
    max_attempts: int = Field(default=3, ge=0)
    backoff_base: float = Field(default=0.5, ge=0.0)
    backoff_max: float = Field(default=30.0, ge=0.0)
    jitter: bool = True

    @model_validator(mode="after")
    def _validate_backoff(self) -> "RetryConfig":
        if self.backoff_max < self.backoff_base:
            raise ValueError("backoff_max must be greater or equal to backoff_base")
        return self


class OperationSpec(_SpecModel):
    """Декларация target-операции, разрешаемой по alias."""

    alias: str
    kind: str = "http"
    expected_statuses: tuple[int, ...] = (200,)
    timeout_ms: int | None = Field(default=None, ge=1)
    retry_profile: str | None = None
    redaction_override: dict[str, Any] | None = None
    # Transport-specific payload (http/db/file/...) остаётся opaque для target-core.
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_operation(self) -> "OperationSpec":
        alias = self.alias.strip()
        if alias == "":
            raise ValueError("operation alias must not be empty")
        object.__setattr__(self, "alias", alias)
        if self.kind == "http" and not self.data:
            raise ValueError("http operation requires transport payload")
        if not self.expected_statuses:
            raise ValueError("operation expected_statuses must not be empty")
        return self


class RedactionSpec(_SpecModel):
    """Правила маскирования для безопасного логирования."""

    forbidden_metadata_keys: frozenset[str] = frozenset(
        {
            "authorization",
            "cookie",
            "set-cookie",
            "x-api-key",
            "x-ankey-password",
        }
    )
    forbidden_fields: frozenset[str] = frozenset(
        {
            "password",
            "token",
            "secret",
            "api_key",
        }
    )
    body_mode: Literal["none", "keys_only", "truncated"] = "truncated"


class HealthSpec(_SpecModel):
    """Декларация health-check операции target-провайдера."""

    operation_alias: str = "health.check"

    @model_validator(mode="after")
    def _validate_alias(self) -> "HealthSpec":
        alias = self.operation_alias.strip()
        if alias == "":
            raise ValueError("health operation alias must not be empty")
        object.__setattr__(self, "operation_alias", alias)
        return self


class TargetSpec(_SpecModel):
    """Полная спецификация target-системы."""

    target_type: str
    capabilities: frozenset[TargetCapability]
    fault_rules: tuple[FaultRule, ...]
    retry_rules: tuple[RetryRule, ...]
    retry_config: RetryConfig
    redaction: RedactionSpec
    health: HealthSpec
    operations: dict[str, OperationSpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_spec_integrity(self) -> "TargetSpec":
        """Проверить целостность спецификации target.

        Инварианты:
            - health-check требует capability ``check``;
            - health operation alias должен присутствовать в каталоге operations;
            - ключ ``operations`` должен совпадать с ``OperationSpec.alias``.
        """
        if "check" not in self.capabilities:
            raise ValueError(
                "health specification requires 'check' capability in target capabilities",
            )
        if self.health.operation_alias not in self.operations:
            raise ValueError(
                f"health operation alias is not declared: {self.health.operation_alias!r}",
            )
        for alias, operation in self.operations.items():
            if alias != operation.alias:
                raise ValueError(
                    f"operation alias key mismatch: key={alias!r}, alias={operation.alias!r}",
                )
        return self


__all__ = [
    "FaultRule",
    "HealthSpec",
    "OperationSpec",
    "RedactionSpec",
    "RetryConfig",
    "RetryDirective",
    "RetryRule",
    "TargetCapability",
    "TargetFaultKind",
    "TargetSpec",
]

