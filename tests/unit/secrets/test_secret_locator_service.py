from __future__ import annotations

import pytest

from connector.domain.secrets.secret_locator_service import LOCATOR_VERSION_V1, SecretLocatorService


def test_locator_hash_is_deterministic_for_same_payload():
    locator = SecretLocatorService()
    source_ref = {"match_key": "Doe|John|M|100"}

    first = locator.build_locator_hash(
        dataset="employees",
        field="password",
        source_ref=source_ref,
    )
    second = locator.build_locator_hash(
        dataset="employees",
        field="password",
        source_ref={"match_key": "Doe|John|M|100"},
    )

    assert first == second


def test_locator_hash_is_stable_for_key_order_and_empty_values():
    locator = SecretLocatorService()

    first = locator.build_locator_hash(
        dataset="employees",
        field="password",
        source_ref={"b": "2", "a": "1", "empty": "", "none": None},
    )
    second = locator.build_locator_hash(
        dataset="employees",
        field="password",
        source_ref={"a": "1", "b": "2"},
    )

    assert first == second


def test_locator_hash_changes_for_different_scope():
    locator = SecretLocatorService()
    base = locator.build_locator_hash(
        dataset="employees",
        field="password",
        source_ref={"match_key": "m1"},
    )
    different_field = locator.build_locator_hash(
        dataset="employees",
        field="token",
        source_ref={"match_key": "m1"},
    )
    different_source = locator.build_locator_hash(
        dataset="employees",
        field="password",
        source_ref={"match_key": "m2"},
    )

    assert base != different_field
    assert base != different_source


def test_locator_rejects_unsupported_version():
    locator = SecretLocatorService()

    with pytest.raises(ValueError, match="Unsupported locator version"):
        locator.build_locator_hash(
            dataset="employees",
            field="password",
            source_ref={"match_key": "m1"},
            locator_version="v2",
        )


def test_locator_reports_supported_versions():
    locator = SecretLocatorService()
    assert locator.supported_versions() == (LOCATOR_VERSION_V1,)
