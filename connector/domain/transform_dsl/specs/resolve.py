"""
Назначение:
    Transform DSL: спецификации resolve-стадии.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from connector.domain.dsl.specs._base import DslBaseModel
from connector.domain.transform_dsl.specs.topology import ResolveTopologyLinkSpec


class ResolveDesiredStateSpec(DslBaseModel):
    """
    Назначение:
        Декларативная сборка desired_state из входной строки.
    """

    mode: Literal["project_fields"] = "project_fields"
    fields: list[str] = Field(default_factory=list)
    drop_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_fields(self) -> "ResolveDesiredStateSpec":
        if not self.fields:
            raise ValueError("resolve.desired_state.fields must not be empty")
        return self


class ResolveSourceRefSpec(DslBaseModel):
    """
    Назначение:
        Декларативная сборка source_ref из identity.
    """

    mode: Literal["from_identity"] = "from_identity"
    fields: list[str] = Field(default_factory=list)
    include_primary: bool = True


class ResolveDiffFieldSpec(DslBaseModel):
    """
    Назначение:
        Декларативное сравнение одного поля в diff-policy.
    """

    field: str
    existing: str | None = None
    output: str | None = None
    normalize: Literal["none", "text", "bool"] = "none"


class ResolveDiffSpec(DslBaseModel):
    """
    Назначение:
        Декларативный diff-policy resolver.
    """

    class FromSinkSpec(DslBaseModel):
        """
        Назначение:
            Конфигурация генерации базовых diff-полей из sink-спеки.
        """

        enabled: bool = False
        exclude_fields: list[str] = Field(default_factory=list)
        normalize_by_type: bool = True

    mode: Literal["compare_fields"] = "compare_fields"
    fields: list[ResolveDiffFieldSpec] = Field(default_factory=list)
    ignore_fields: list[str] = Field(default_factory=list)
    from_sink: FromSinkSpec = Field(default_factory=FromSinkSpec)

    @model_validator(mode="after")
    def _validate_fields(self) -> "ResolveDiffSpec":
        if not self.fields and not self.from_sink.enabled:
            raise ValueError(
                "resolve.diff.fields must not be empty when resolve.diff.from_sink.enabled is false"
            )
        return self


class ResolveMergeFieldSpec(DslBaseModel):
    """
    Назначение:
        Правило merge для fill_empty_from_existing.
    """

    field: str
    existing: str | None = None
    normalize: Literal["none", "text", "bool"] = "none"


class ResolveMergeSpec(DslBaseModel):
    """
    Назначение:
        Декларативная merge-policy resolver.
    """

    mode: Literal["none", "fill_empty_from_existing"] = "none"
    fields: list[ResolveMergeFieldSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_fields(self) -> "ResolveMergeSpec":
        if self.mode == "fill_empty_from_existing" and not self.fields:
            raise ValueError(
                "resolve.merge.fields must not be empty for fill_empty_from_existing"
            )
        return self


class ResolveSecretsSpec(DslBaseModel):
    """
    Назначение:
        Декларативная политика секретов для resolver output.
    """

    mode: Literal["none", "by_op"] = "none"
    create: list[str] = Field(default_factory=list)
    update: list[str] = Field(default_factory=list)
    lifecycle: "ResolveSecretLifecycleSpec | None" = None


class ResolveSecretLifecycleSpec(DslBaseModel):
    """
    Назначение:
        Декларативная lifecycle-политика retention для секретов.
    """

    mode: Literal["persistent", "ephemeral"] = "persistent"
    delete_on_success: bool | None = None
    ttl_seconds: int | None = None


class ResolveLinkKeySpec(DslBaseModel):
    """
    Назначение:
        Декларативный ключ поиска для link-resolve.
    """

    name: str
    field: str


class ResolveLinkSpec(DslBaseModel):
    """
    Назначение:
        Декларативное resolve-правило для одного link-поля.
    """

    field: str
    target_dataset: str
    resolve_keys: list[ResolveLinkKeySpec] = Field(default_factory=list)
    dedup_rules: list[list[str]] = Field(default_factory=list)
    target_id_field: str = "_id"
    coerce: Literal["int", "str"] | None = None
    on_unresolved: Literal["pending", "hard_error"] = "pending"

    @model_validator(mode="after")
    def _validate_link(self) -> "ResolveLinkSpec":
        if not self.resolve_keys:
            raise ValueError("resolve.links[].resolve_keys must not be empty")
        for idx, rule in enumerate(self.dedup_rules):
            if not rule:
                raise ValueError(
                    f"resolve.links[].dedup_rules[{idx}] must not be empty"
                )
            for key_name in rule:
                if not str(key_name).strip():
                    raise ValueError(
                        f"resolve.links[].dedup_rules[{idx}] must not contain empty key names"
                    )
        return self


class ResolveBlock(DslBaseModel):
    desired_state: ResolveDesiredStateSpec | None = None
    source_ref: ResolveSourceRefSpec | None = None
    diff: ResolveDiffSpec | None = None
    merge: ResolveMergeSpec | None = None
    secrets: ResolveSecretsSpec | None = None
    links: list[ResolveLinkSpec] = Field(default_factory=list)
    topology_link: ResolveTopologyLinkSpec | None = None

    @model_validator(mode="after")
    def _validate_block(self) -> "ResolveBlock":
        fields = [item.field for item in self.links]
        duplicates = sorted({name for name in fields if fields.count(name) > 1})
        if duplicates:
            raise ValueError(f"resolve.links has duplicate field entries: {duplicates}")
        if self.desired_state is None:
            raise ValueError("resolve.desired_state is required")
        if self.diff is None:
            raise ValueError("resolve.diff is required")
        return self


class ResolveSpec(DslBaseModel):
    dataset: str
    resolve: ResolveBlock
