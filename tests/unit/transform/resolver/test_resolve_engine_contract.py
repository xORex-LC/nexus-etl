"""
Anti-regression: legacy compatibility shims must not return into ResolveEngine.
"""

from __future__ import annotations

from connector.domain.transform.resolver.resolve_engine import ResolveEngine


def test_resolve_engine_has_no_legacy_drain_expired_shim():
    assert not hasattr(ResolveEngine, "drain_expired")
