"""Tests for strict `spec_class` registry contract in DEC-009."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pytest

from connector.datasets import registry as registry_module
from connector.datasets.registry import get_spec, validate_registry
from connector.datasets.spec import ReportAdapter
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.transform.core.source_record import SourceRecord

FACTORY_CALLS: list[object] = []


@dataclass
class _CustomDatasetSpec:
    dataset_name: str
    received_secrets: object = None

    def build_spec_for(self, stage_type: str) -> object:
        return {"stage_type": stage_type}

    def build_record_source(self) -> Iterable[SourceRecord]:
        return ()

    def get_report_adapter(self) -> ReportAdapter:
        return ReportAdapter(
            identity_label="id",
            conflict_code="MATCH_CONFLICT",
            conflict_field="id",
        )

    def get_apply_adapter(self) -> object:
        return object()

    def get_diagnostic_catalog(self, strict: bool) -> ErrorCatalog:
        _ = strict
        return ErrorCatalog(strict=False)


def valid_spec_factory(*, secrets=None):
    FACTORY_CALLS.append(secrets)
    return _CustomDatasetSpec(dataset_name="custom", received_secrets=secrets)


class ValidCustomSpecClass(_CustomDatasetSpec):
    def __init__(self, *, secrets=None) -> None:
        super().__init__(dataset_name="custom-class", received_secrets=secrets)


def invalid_spec_factory_no_secrets():
    return _CustomDatasetSpec(dataset_name="custom")


def invalid_spec_factory_required_secrets(*, secrets):
    return _CustomDatasetSpec(dataset_name="custom", received_secrets=secrets)


def invalid_spec_factory_positional_only(secrets=None, /):
    return _CustomDatasetSpec(dataset_name="custom", received_secrets=secrets)


def invalid_spec_factory_wrong_return(*, secrets=None):
    _ = secrets
    return object()


def invalid_spec_factory_mismatch_dataset(*, secrets=None):
    return _CustomDatasetSpec(dataset_name="another-dataset", received_secrets=secrets)


@pytest.fixture(autouse=True)
def _reset_registry(monkeypatch):
    FACTORY_CALLS.clear()
    monkeypatch.setattr(registry_module, "_registry", None)


def _patch_registry(monkeypatch, dataset_name: str, spec_class_ref: str) -> None:
    monkeypatch.setattr(
        registry_module,
        "load_registry",
        lambda: {
            "datasets": {
                dataset_name: {"spec_class": spec_class_ref},
            }
        },
    )


class TestSpecClassRegistryContract:
    def test_get_spec_returns_custom_factory_instance(self, monkeypatch):
        _patch_registry(monkeypatch, "custom", f"{__name__}:valid_spec_factory")

        spec = get_spec("custom")

        assert spec.dataset_name == "custom"
        assert spec.received_secrets is None

    def test_get_spec_forwards_secrets_to_custom_factory(self, monkeypatch):
        _patch_registry(monkeypatch, "custom", f"{__name__}:valid_spec_factory")
        provider = object()

        spec = get_spec("custom", secrets=provider)

        assert spec.received_secrets is provider
        assert FACTORY_CALLS == [provider]

    def test_validate_registry_eagerly_calls_custom_factory(self, monkeypatch):
        _patch_registry(monkeypatch, "custom", f"{__name__}:valid_spec_factory")

        validate_registry()

        assert FACTORY_CALLS == [None]

    def test_validate_registry_accepts_class_based_spec_class(self, monkeypatch):
        _patch_registry(monkeypatch, "custom-class", f"{__name__}:ValidCustomSpecClass")

        validate_registry()
        spec = get_spec("custom-class")

        assert spec.dataset_name == "custom-class"

    def test_invalid_ref_format_raises_value_error(self, monkeypatch):
        _patch_registry(monkeypatch, "custom", "broken-ref")

        with pytest.raises(ValueError, match="expected format 'module.path:factory_or_class'"):
            validate_registry()

    def test_factory_without_secrets_is_rejected(self, monkeypatch):
        _patch_registry(monkeypatch, "custom", f"{__name__}:invalid_spec_factory_no_secrets")

        with pytest.raises(ValueError, match="must declare optional keyword parameter 'secrets'"):
            validate_registry()

    def test_factory_with_required_secrets_is_rejected(self, monkeypatch):
        _patch_registry(monkeypatch, "custom", f"{__name__}:invalid_spec_factory_required_secrets")

        with pytest.raises(ValueError, match="parameter 'secrets' must be optional"):
            validate_registry()

    def test_factory_with_positional_only_secrets_is_rejected(self, monkeypatch):
        _patch_registry(monkeypatch, "custom", f"{__name__}:invalid_spec_factory_positional_only")

        with pytest.raises(ValueError, match="parameter 'secrets' must be keyword-compatible"):
            validate_registry()

    def test_factory_returning_non_dataset_spec_is_rejected(self, monkeypatch):
        _patch_registry(monkeypatch, "custom", f"{__name__}:invalid_spec_factory_wrong_return")

        with pytest.raises(ValueError, match="factory must return DatasetSpec with non-empty 'dataset_name'"):
            validate_registry()

    def test_dataset_name_mismatch_is_rejected(self, monkeypatch):
        _patch_registry(monkeypatch, "custom", f"{__name__}:invalid_spec_factory_mismatch_dataset")

        with pytest.raises(ValueError, match="expected 'custom'"):
            validate_registry()
