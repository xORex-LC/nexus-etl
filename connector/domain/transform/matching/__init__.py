"""Matching/deduplication + lookup resolution for data transform."""

from connector.domain.transform.matching.deduplication_transform import DeduplicationTransform
from connector.domain.transform.matching.context import MatchContext
from connector.domain.transform.matching.lookup_enricher import LookupEnricher
from connector.domain.transform.matching.match_models import MatchedRow, ResolvedRow, ResolveOp, build_fingerprint_for_keys
from connector.domain.transform.matching.rules import MatchingRules, ResolveRules, LinkRules, LinkFieldRule, LinkKeyRule
from connector.domain.transform.matching.identity_keys import format_identity_key
from connector.domain.transform.matching.resolve_deps import ResolverSettings

__all__ = [
    "DeduplicationTransform",
    "MatchContext",
    "LookupEnricher",
    "MatchedRow",
    "ResolvedRow",
    "ResolveOp",
    "build_fingerprint_for_keys",
    "MatchingRules",
    "ResolveRules",
    "LinkRules",
    "LinkFieldRule",
    "LinkKeyRule",
    "format_identity_key",
    "ResolverSettings",
]
