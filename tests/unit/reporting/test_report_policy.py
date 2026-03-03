from __future__ import annotations

from connector.domain.reporting.policy import (
    ReportPolicy,
    ReportPolicyCapabilities,
    ReportPolicyProfile,
    resolve_report_policy,
)


def test_report_policy_profiles_match_fixed_matrix() -> None:
    minimal = ReportPolicy.minimal()
    standard = ReportPolicy.standard()
    debug = ReportPolicy.debug()

    assert minimal.profile == ReportPolicyProfile.MINIMAL
    assert minimal.capabilities == ReportPolicyCapabilities(
        include_ok_items=False,
        include_failed_items=True,
        include_skipped_items=False,
        include_payload_masked=False,
        include_upstream_diagnostics=False,
        include_subsystem_metrics=False,
        include_runtime_secondary_as_items=True,
    )

    assert standard.profile == ReportPolicyProfile.STANDARD
    assert standard.capabilities == ReportPolicyCapabilities(
        include_ok_items=True,
        include_failed_items=True,
        include_skipped_items=True,
        include_payload_masked=True,
        include_upstream_diagnostics=False,
        include_subsystem_metrics=True,
        include_runtime_secondary_as_items=True,
    )

    assert debug.profile == ReportPolicyProfile.DEBUG
    assert debug.capabilities == ReportPolicyCapabilities(
        include_ok_items=True,
        include_failed_items=True,
        include_skipped_items=True,
        include_payload_masked=True,
        include_upstream_diagnostics=True,
        include_subsystem_metrics=True,
        include_runtime_secondary_as_items=True,
    )


def test_effective_include_skipped_items_is_capability_and_cli_override() -> None:
    assert ReportPolicy.minimal().resolve_include_skipped_items(cli_include_skipped=False) is False
    assert ReportPolicy.minimal().resolve_include_skipped_items(cli_include_skipped=True) is False

    assert ReportPolicy.standard().resolve_include_skipped_items(cli_include_skipped=False) is False
    assert ReportPolicy.standard().resolve_include_skipped_items(cli_include_skipped=True) is True

    assert ReportPolicy.debug().resolve_include_skipped_items(cli_include_skipped=False) is False
    assert ReportPolicy.debug().resolve_include_skipped_items(cli_include_skipped=True) is True


def test_cli_override_cannot_expand_policy_capability() -> None:
    policy = ReportPolicy.minimal()

    assert policy.capabilities.include_skipped_items is False
    assert policy.resolve_include_skipped_items(cli_include_skipped=True) is False


def test_resolve_report_policy_uses_context_when_explicit_not_passed() -> None:
    policy = ReportPolicy.minimal()
    policy_context = policy.to_context_payload(
        cli_include_skipped=True,
        effective_include_skipped_items=False,
    )

    resolved = resolve_report_policy(policy_context)

    assert resolved.profile == ReportPolicyProfile.MINIMAL


def test_resolve_report_policy_prefers_explicit_policy() -> None:
    policy_context = ReportPolicy.minimal().to_context_payload(
        cli_include_skipped=True,
        effective_include_skipped_items=False,
    )
    explicit = ReportPolicy.debug()

    resolved = resolve_report_policy(policy_context, explicit)

    assert resolved.profile == ReportPolicyProfile.DEBUG
