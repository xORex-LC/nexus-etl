"""Matcher package: Match DSL/engine/core and related contracts."""

from connector.domain.transform.matcher.context import MatchContext
from connector.domain.transform.matcher.identity_keys import format_identity_key
from connector.domain.transform.matcher.match_core import MatchCore
from connector.domain.transform_dsl.compilers.match import MatchDsl
from connector.domain.transform.matcher.match_engine import MatchEngine
from connector.domain.transform.matcher.match_models import (
    MatchCandidate,
    MatchDecision,
    MatchDecisionReason,
    MatchDecisionStatus,
    MatchedRow,
    ResolveOp,
    ResolvedRow,
    build_fingerprint,
    build_fingerprint_for_keys,
    resolve_decision_status,
)
from connector.domain.transform_dsl.compilers.match import (
    FuzzyScoringRules,
    IdentityRule,
    MatchingRules,
    SourceDedupRules,
)
from connector.domain.transform_dsl.compilers.resolve import (
    LinkFieldRule,
    LinkKeyRule,
    LinkRules,
    ResolveRules,
)

__all__ = [
    "MatchContext",
    "format_identity_key",
    "MatchCore",
    "MatchDsl",
    "MatchEngine",
    "MatchCandidate",
    "MatchDecision",
    "MatchDecisionReason",
    "MatchDecisionStatus",
    "MatchedRow",
    "ResolveOp",
    "ResolvedRow",
    "build_fingerprint",
    "build_fingerprint_for_keys",
    "resolve_decision_status",
    "FuzzyScoringRules",
    "IdentityRule",
    "LinkFieldRule",
    "LinkKeyRule",
    "LinkRules",
    "MatchingRules",
    "ResolveRules",
    "SourceDedupRules",
]
