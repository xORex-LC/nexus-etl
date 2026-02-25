"""
Anti-regression: legacy matcher lifecycle shims must not return into MatchEngine.
"""

from __future__ import annotations

from connector.domain.transform.matcher.match_engine import MatchEngine


def test_match_engine_has_no_legacy_reset_source_dedup_shim():
    assert not hasattr(MatchEngine, "reset_source_dedup")


def test_match_engine_has_no_legacy_bind_runtime_scope_shim():
    assert not hasattr(MatchEngine, "bind_runtime_scope")
