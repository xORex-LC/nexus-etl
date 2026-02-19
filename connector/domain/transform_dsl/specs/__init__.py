"""
Назначение:
    Transform DSL спецификации (public API).
"""

from connector.domain.transform_dsl.specs.enrich import (
    EnrichBlock,
    EnrichRule,
    EnrichSpec,
    ExistsRef,
    MatchKeySpec,
    ProviderRef,
    SecretsSpec,
)
from connector.domain.transform_dsl.specs.mapping import (
    MappingBlock,
    MappingRule,
    MappingSchema,
    MappingSpec,
    MetaRule,
)
from connector.domain.transform_dsl.specs.match import (
    FuzzySpec,
    MatchBlock,
    MatchRule,
    MatchSpec,
    SourceDedupSpec,
)
from connector.domain.transform_dsl.specs.normalize import (
    NormalizeBlock,
    NormalizeRule,
    NormalizeSpec,
)
from connector.domain.transform_dsl.specs.resolve import (
    ResolveBlock,
    ResolveDesiredStateSpec,
    ResolveDiffFieldSpec,
    ResolveDiffSpec,
    ResolveLinkKeySpec,
    ResolveLinkSpec,
    ResolveMergeFieldSpec,
    ResolveMergeSpec,
    ResolveSecretsSpec,
    ResolveSourceRefSpec,
    ResolveSpec,
)
from connector.domain.transform_dsl.specs.sink import (
    SinkBlock,
    SinkFieldSpec,
    SinkSpec,
)
from connector.domain.transform_dsl.specs.source import (
    SourceConfig,
    SourceFieldSpec,
    SourceSpec,
)
from connector.domain.transform_dsl.specs.validate import (
    ConditionalCheck,
    FieldCheck,
    ValidationBlock,
    ValidationSpec,
)

__all__ = [
    # Mapping
    "MappingRule",
    "MetaRule",
    "MappingSchema",
    "MappingBlock",
    "MappingSpec",
    # Source
    "SourceFieldSpec",
    "SourceConfig",
    "SourceSpec",
    # Sink
    "SinkFieldSpec",
    "SinkBlock",
    "SinkSpec",
    # Normalize
    "NormalizeRule",
    "NormalizeBlock",
    "NormalizeSpec",
    # Enrich
    "MatchKeySpec",
    "SecretsSpec",
    "ProviderRef",
    "ExistsRef",
    "EnrichRule",
    "EnrichBlock",
    "EnrichSpec",
    # Validate
    "FieldCheck",
    "ConditionalCheck",
    "ValidationBlock",
    "ValidationSpec",
    # Match
    "MatchRule",
    "SourceDedupSpec",
    "FuzzySpec",
    "MatchBlock",
    "MatchSpec",
    # Resolve
    "ResolveDesiredStateSpec",
    "ResolveSourceRefSpec",
    "ResolveDiffFieldSpec",
    "ResolveDiffSpec",
    "ResolveMergeFieldSpec",
    "ResolveMergeSpec",
    "ResolveSecretsSpec",
    "ResolveLinkKeySpec",
    "ResolveLinkSpec",
    "ResolveBlock",
    "ResolveSpec",
]
