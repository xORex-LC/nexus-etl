from __future__ import annotations

import pytest

from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.loader import (
    load_cache_build_options_for_runtime,
    load_enrich_build_options_for_dataset,
    load_map_build_options_for_dataset,
    load_match_build_options_for_dataset,
    load_normalize_build_options_for_dataset,
    load_resolve_build_options_for_dataset,
)


def _patch_registry(monkeypatch, registry: dict) -> None:
    monkeypatch.setattr("connector.domain.dsl.loader.transform._load_registry_or_raise", lambda: registry)
    monkeypatch.setattr("connector.domain.dsl.loader.cache._load_registry_or_raise", lambda: registry)


def test_build_options_defaults_without_policy(monkeypatch):
    registry = {"datasets": {"employees": {}}}
    _patch_registry(monkeypatch, registry)

    mapping = load_map_build_options_for_dataset("employees")
    normalize = load_normalize_build_options_for_dataset("employees")
    enrich = load_enrich_build_options_for_dataset("employees")
    match = load_match_build_options_for_dataset("employees")
    resolve = load_resolve_build_options_for_dataset("employees")
    cache = load_cache_build_options_for_runtime()

    assert mapping.strict is False
    assert normalize.validate_only_touched_fields is False
    assert enrich.require_match_key is False
    assert match.require_primary_identity_rule is False
    assert resolve.allow_pending_links is True
    assert cache.fail_on_unknown_dependencies is True


def test_build_options_merge_order(monkeypatch):
    registry = {
        "build_options": {
            "base": {
                "strict": False,
                "fail_on_unknown_ops": True,
            },
            "stages": {
                "normalize": {
                    "validate_only_touched_fields": False,
                    "strict": False,
                }
            },
        },
        "datasets": {
            "employees": {
                "build_options": {
                    "normalize": {
                        "validate_only_touched_fields": True,
                        "strict": True,
                    }
                }
            }
        },
    }
    _patch_registry(monkeypatch, registry)

    options = load_normalize_build_options_for_dataset("employees")

    # dataset.stage overrides global.stage and global.base
    assert options.validate_only_touched_fields is True
    assert options.strict is True
    # inherited from base (not overridden)
    assert options.fail_on_unknown_ops is True


def test_cache_build_options_merge_order(monkeypatch):
    _patch_registry(
        monkeypatch,
        {
            "build_options": {
                "base": {
                    "strict": False,
                    "fail_on_unknown_ops": True,
                },
                "stages": {
                    "cache": {
                        "strict": True,
                        "fail_on_unknown_dependencies": False,
                    }
                },
            },
            "datasets": {"employees": {}},
            "cache": {
                "datasets": {
                    "employees": {
                        "build_options": {
                            "cache": {
                                "strict": False,
                                "fail_on_unknown_projection_targets": False,
                            }
                        }
                    }
                }
            },
        },
    )

    options = load_cache_build_options_for_runtime(
        cli_overrides={"strict": True},
    )

    # CLI override > dataset override > global stage > global base
    assert options.strict is True
    assert options.fail_on_unknown_dependencies is False
    assert options.fail_on_unknown_projection_targets is False
    assert options.fail_on_unknown_ops is True


def test_strict_mode_enforces_fail_on_unknown_ops(monkeypatch):
    registry = {
        "build_options": {
            "base": {
                "strict": True,
                "fail_on_unknown_ops": False,
            },
        },
        "datasets": {"employees": {}},
    }
    _patch_registry(monkeypatch, registry)

    options = load_map_build_options_for_dataset("employees")

    assert options.strict is True
    assert options.fail_on_unknown_ops is True


def test_stage_build_options_fail_for_unknown_dataset(monkeypatch):
    registry = {"datasets": {"employees": {}}}
    _patch_registry(monkeypatch, registry)

    with pytest.raises(DslLoadError) as exc_info:
        load_map_build_options_for_dataset("missing_dataset")
    assert exc_info.value.code == "DSL_REGISTRY_INVALID"


def test_stage_build_options_strict_mode_fails_on_unknown_keys(monkeypatch):
    registry = {
        "build_options": {
            "base": {
                "strict": True,
                "unknown_option": True,
            }
        },
        "datasets": {"employees": {}},
    }
    _patch_registry(monkeypatch, registry)

    with pytest.raises(DslLoadError) as exc_info:
        load_map_build_options_for_dataset("employees")
    assert exc_info.value.code == "BUILD_OPTIONS_UNKNOWN_KEYS"


def test_cache_build_options_fails_when_registry_overrides_are_ambiguous(monkeypatch):
    registry = {
        "build_options": {
            "base": {"strict": False},
            "stages": {"cache": {"fail_on_unknown_ops": True}},
        },
        "datasets": {"employees": {}, "organizations": {}},
        "cache": {
            "datasets": {
                "employees": {"build_options": {"cache": {"strict": True}}},
                "organizations": {"build_options": {"cache": {"strict": False}}},
            }
        },
    }
    _patch_registry(monkeypatch, registry)

    with pytest.raises(DslLoadError) as exc_info:
        load_cache_build_options_for_runtime()
    assert exc_info.value.code == "CACHE_DSL_BUILD_OPTIONS_AMBIGUOUS"
