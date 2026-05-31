"""
Назначение:
    Transform DSL: спецификации topology/canonicalizer capability.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from connector.domain.dsl.specs._base import DslBaseModel

TopologyComparisonLadderStep = Literal[
    "exact_canonical_path",
    "exact_leaf_parent_chain",
    "exact_leaf_root_depth",
]

TopologyMatchApplyOn = Literal["ambiguous_only", "all_candidates"]


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


class TopologyTrimOpSpec(DslBaseModel):
    """
    Назначение:
        Декларативный trim-оператор topology canonicalizer-а.
    """

    op: Literal["trim"] = "trim"


class TopologyLowerOpSpec(DslBaseModel):
    """
    Назначение:
        Декларативный lower-оператор topology canonicalizer-а.
    """

    op: Literal["lower"] = "lower"


class TopologyCompactOpSpec(DslBaseModel):
    """
    Назначение:
        Декларативный compact-оператор topology canonicalizer-а.
    """

    op: Literal["compact"] = "compact"


class TopologyRegexReplaceOpSpec(DslBaseModel):
    """
    Назначение:
        Декларативный regex_replace-оператор topology canonicalizer-а.
    """

    op: Literal["regex_replace"] = "regex_replace"
    pattern: str
    repl: str

    @field_validator("pattern", mode="after")
    @classmethod
    def _validate_pattern(cls, value: str) -> str:
        if value == "":
            raise ValueError(
                "topology.canonicalization.ops[].pattern must not be empty"
            )
        return value


TopologyCanonicalizeOpSpec = Annotated[
    TopologyTrimOpSpec
    | TopologyLowerOpSpec
    | TopologyCompactOpSpec
    | TopologyRegexReplaceOpSpec,
    Field(discriminator="op"),
]


class TopologyCanonicalizationSpec(DslBaseModel):
    """
    Назначение:
        Общий contract segment/path canonicalization для source и target topology.
    """

    ops: list[TopologyCanonicalizeOpSpec] = Field(default_factory=list)


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
    source: TopologySourcePathColumnsSpec
    target: TopologyTargetAdjacencySpec


class TopologySpec(DslBaseModel):
    """
    Назначение:
        Декларативная topology-спецификация датасета.
    """

    dataset: str
    topology: TopologyBlock
