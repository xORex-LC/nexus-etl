"""Transform DSL: спецификации topology и topology-specific capability policy."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from connector.domain.transform_dsl.specs.canonicalization import (
    CanonicalizationSpec,
    CanonicalizeOpSpec,
    CompactOpSpec,
    LowerOpSpec,
    RegexReplaceOpSpec,
    TrimOpSpec,
)
from connector.domain.dsl.specs._base import DslBaseModel

TopologyComparisonLadderStep = Literal[
    "exact_canonical_path",
    "exact_leaf_parent_chain",
    "exact_leaf_root_depth",
]

TopologyMatchApplyOn = Literal["ambiguous_only", "all_candidates"]
TopologySourceUnanchoredPolicy = Literal["skip", "warn", "hard_error"]


class TopologyPathColumnSpec(DslBaseModel):
    """
    Назначение:
        Описание одного source path-column для topology bootstrap.
    """

    field: str

    @field_validator("field", mode="after")
    @classmethod
    def _validate_field(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("topology.source.path_columns[].field must not be blank")
        return normalized


TopologyTrimOpSpec = TrimOpSpec
TopologyLowerOpSpec = LowerOpSpec
TopologyCompactOpSpec = CompactOpSpec
TopologyRegexReplaceOpSpec = RegexReplaceOpSpec
TopologyCanonicalizeOpSpec = CanonicalizeOpSpec
TopologyCanonicalizationSpec = CanonicalizationSpec


class TopologyFreshnessPolicySpec(DslBaseModel):
    """
    Назначение:
        Декларативный shape freshness-policy для target topology readiness.
    """

    mode: Literal["none", "max_age", "revision_required"] = "none"
    max_age_seconds: int | None = None
    require_revision: bool = False

    @model_validator(mode="after")
    def _validate_policy(self) -> "TopologyFreshnessPolicySpec":
        if self.max_age_seconds is not None and self.max_age_seconds <= 0:
            raise ValueError("topology.freshness.max_age_seconds must be > 0")
        if self.mode == "max_age" and self.max_age_seconds is None:
            raise ValueError(
                "topology.freshness.max_age_seconds is required when mode='max_age'"
            )
        return self


class TopologySourcePathColumnsSpec(DslBaseModel):
    """
    Назначение:
        Декларативный source-side topology ingress через ordered path columns.
    """

    mode: Literal["path_columns"] = "path_columns"
    path_columns: list[TopologyPathColumnSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_columns(self) -> "TopologySourcePathColumnsSpec":
        if not self.path_columns:
            raise ValueError("topology.source.path_columns must not be empty")
        return self


class TopologySourceAdjacencyListSpec(DslBaseModel):
    """
    Назначение:
        Декларативный source-side ingress через id/parent_id adjacency list.
    """

    mode: Literal["adjacency_list"] = "adjacency_list"
    node_id_field: str
    parent_id_field: str
    label_field: str
    target_membership_field: str
    on_unanchored: TopologySourceUnanchoredPolicy = "skip"

    @field_validator(
        "node_id_field",
        "parent_id_field",
        "label_field",
        "target_membership_field",
        mode="after",
    )
    @classmethod
    def _validate_required_fields(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("topology.source adjacency fields must not be blank")
        return normalized


TopologySourceSpec = Annotated[
    TopologySourcePathColumnsSpec | TopologySourceAdjacencyListSpec,
    Field(discriminator="mode"),
]


class TopologyTargetAdjacencySpec(DslBaseModel):
    """
    Назначение:
        Декларативный target-side ingress через adjacency list.
    """

    mode: Literal["adjacency_list"] = "adjacency_list"
    node_id_field: str
    parent_id_field: str
    target_label_field: str
    payload_target_id_field: str | None = None

    @field_validator(
        "node_id_field",
        "parent_id_field",
        "target_label_field",
        mode="after",
    )
    @classmethod
    def _validate_required_fields(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("topology.target required fields must not be blank")
        return normalized

    @field_validator("payload_target_id_field", mode="after")
    @classmethod
    def _validate_optional_payload_target_id_field(
        cls, value: str | None
    ) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError(
                "topology.target.payload_target_id_field must not be blank"
            )
        return normalized


class MatchTopologyPolicySpec(DslBaseModel):
    """
    Назначение:
        Политика использования topology signal в match/disambiguation.
    """

    enabled: bool = False
    apply_on: TopologyMatchApplyOn = "ambiguous_only"
    on_missing_topology: Literal["skip", "hard_error"] = "skip"
    comparison_ladder: list[TopologyComparisonLadderStep] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_policy(self) -> "MatchTopologyPolicySpec":
        if self.enabled and not self.comparison_ladder:
            raise ValueError(
                "match.topology.comparison_ladder must not be empty when enabled"
            )
        return self


class ResolveTopologyLinkSpec(DslBaseModel):
    """
    Назначение:
        Политика topology-backed link resolution для resolve-стадии.
    """

    enabled: bool = False
    field: str = ""
    on_missing_topology: Literal["pending", "hard_error", "skip"] = "pending"
    on_ambiguous_topology: Literal["pending", "hard_error", "skip"] = "pending"
    comparison_ladder: list[TopologyComparisonLadderStep] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_link(self) -> "ResolveTopologyLinkSpec":
        if self.enabled and not self.field.strip():
            raise ValueError(
                "resolve.topology_link.field must not be blank when enabled"
            )
        if self.enabled and not self.comparison_ladder:
            raise ValueError(
                "resolve.topology_link.comparison_ladder must not be empty when enabled"
            )
        return self


class TopologyBlock(DslBaseModel):
    """
    Назначение:
        Полная topology-capability конфигурация датасета.
    """

    canonicalization: TopologyCanonicalizationSpec = Field(
        default_factory=TopologyCanonicalizationSpec
    )
    source: TopologySourceSpec
    target: TopologyTargetAdjacencySpec


class TopologySpec(DslBaseModel):
    """
    Назначение:
        Декларативная topology-спецификация датасета.
    """

    dataset: str
    topology: TopologyBlock
