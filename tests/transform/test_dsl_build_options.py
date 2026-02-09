from __future__ import annotations

from connector.domain.dsl.loader import (
    load_enrich_build_options_for_dataset,
    load_map_build_options_for_dataset,
    load_match_build_options_for_dataset,
    load_normalize_build_options_for_dataset,
    load_resolve_build_options_for_dataset,
)


def test_build_options_defaults_without_policy(monkeypatch):
    monkeypatch.setattr(
        "connector.domain.dsl.loader._load_registry",
        lambda: {"datasets": {"employees": {}}},
    )

    mapping = load_map_build_options_for_dataset("employees")
    normalize = load_normalize_build_options_for_dataset("employees")
    enrich = load_enrich_build_options_for_dataset("employees")
    match = load_match_build_options_for_dataset("employees")
    resolve = load_resolve_build_options_for_dataset("employees")

    assert mapping.strict is False
    assert normalize.validate_only_touched_fields is False
    assert enrich.require_match_key is False
    assert match.require_primary_identity_rule is False
    assert resolve.allow_pending_links is True


def test_build_options_merge_order(monkeypatch):
    monkeypatch.setattr(
        "connector.domain.dsl.loader._load_registry",
        lambda: {
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
        },
    )

    options = load_normalize_build_options_for_dataset("employees")

    # dataset.stage overrides global.stage and global.base
    assert options.validate_only_touched_fields is True
    assert options.strict is True
    # inherited from base (not overridden)
    assert options.fail_on_unknown_ops is True

