"""Matching core + lookup resolution for data transform."""

from connector.domain.transform.matching.match_core import MatchCore
from connector.domain.transform.matching.match_dsl import MatchDsl
from connector.domain.transform.matching.match_engine import MatchEngine
from connector.domain.transform.matching.context import MatchContext
from connector.domain.transform.matching.lookup_enricher import LookupEnricher
from connector.domain.transform.matching.match_models import (
    MatchCandidate,
    MatchDecision,
    MatchDecisionStatus,
    MatchDecisionReason,
    MatchedRow,
    ResolvedRow,
    ResolveOp,
    build_fingerprint_for_keys,
)
from connector.domain.transform.matching.rules import (
    FuzzyScoringRules,
    MatchingRules,
    ResolveRules,
    LinkRules,
    LinkFieldRule,
    LinkKeyRule,
    SourceDedupRules,
)
from connector.domain.transform.matching.identity_keys import format_identity_key
from connector.domain.transform.matching.resolve_deps import ResolverSettings

__all__ = [
    "MatchCore",
    "MatchDsl",
    "MatchEngine",
    "MatchContext",
    "LookupEnricher",
    "MatchedRow",
    "ResolvedRow",
    "ResolveOp",
    "MatchCandidate",
    "MatchDecision",
    "MatchDecisionStatus",
    "MatchDecisionReason",
    "build_fingerprint_for_keys",
    "FuzzyScoringRules",
    "MatchingRules",
    "SourceDedupRules",
    "ResolveRules",
    "LinkRules",
    "LinkFieldRule",
    "LinkKeyRule",
    "format_identity_key",
    "ResolverSettings",
]
