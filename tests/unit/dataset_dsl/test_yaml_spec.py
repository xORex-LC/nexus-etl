"""Tests for YamlDatasetSpec and registry auto-discovery."""

from __future__ import annotations

import pytest

from connector.datasets import registry as registry_module
from connector.datasets.registry import get_spec, list_specs, validate_registry
from connector.datasets.spec import UnsupportedStageError
from connector.datasets.yaml_spec import YamlDatasetSpec
from connector.datasets.yaml_spec_loader import load_yaml_dataset_artifacts
from connector.domain.transform_dsl.specs import (
    EnrichSpec,
    MappingSpec,
    MatchSpec,
    NormalizeSpec,
    ResolveSpec,
    SinkSpec,
)


class TestAutoDiscovery:
    def test_get_spec_returns_yaml_spec(self):
        spec = get_spec("employees")
        assert isinstance(spec, YamlDatasetSpec)

    def test_get_spec_unknown_dataset(self):
        with pytest.raises(ValueError, match="Unsupported dataset"):
            get_spec("nonexistent")

    def test_list_specs_contains_employees(self):
        specs = list_specs()
        assert any(s.dataset_name == "employees" for s in specs)


class TestYamlDatasetSpecBuildSpecFor:
    @pytest.fixture()
    def spec(self):
        return get_spec("employees")

    def test_map(self, spec):
        result = spec.build_spec_for("map")
        assert isinstance(result, MappingSpec)

    def test_normalize(self, spec):
        result = spec.build_spec_for("normalize")
        assert isinstance(result, NormalizeSpec)

    def test_enrich(self, spec):
        result = spec.build_spec_for("enrich")
        assert isinstance(result, EnrichSpec)

    def test_match(self, spec):
        result = spec.build_spec_for("match")
        assert isinstance(result, MatchSpec)

    def test_resolve(self, spec):
        result = spec.build_spec_for("resolve")
        assert isinstance(result, ResolveSpec)

    def test_sink(self, spec):
        result = spec.build_spec_for("sink")
        assert isinstance(result, SinkSpec)
        assert result.dataset == "employees"

    def test_unsupported_stage(self, spec):
        with pytest.raises(UnsupportedStageError) as exc_info:
            spec.build_spec_for("nonexistent")
        assert exc_info.value.stage_type == "nonexistent"
        assert exc_info.value.dataset == "employees"

    def test_returns_deep_copy_on_each_call(self, spec):
        first = spec.build_spec_for("map")
        original_target = first.mapping.rules[0].target
        first.mapping.rules[0].target = "__mutated__"

        second = spec.build_spec_for("map")

        assert second.mapping.rules[0].target == original_target
        assert second.mapping.rules[0].target != "__mutated__"


class TestYamlDatasetSpecAdapters:
    @pytest.fixture()
    def spec(self):
        return get_spec("employees")

    def test_report_adapter(self, spec):
        adapter = spec.get_report_adapter()
        assert adapter.identity_label == "match_key"
        assert adapter.conflict_code == "MATCH_CONFLICT"
        assert adapter.conflict_field == "matchKey"

    def test_apply_adapter(self, spec):
        adapter = spec.get_apply_adapter()
        assert adapter.operation_alias == "users.upsert"

    def test_diagnostic_catalog(self, spec):
        catalog = spec.get_diagnostic_catalog(strict=False)
        assert catalog.contains("INVALID_AVATAR_ID")
        assert catalog.contains("USR_ORG_TAB_CONFLICT")
        assert catalog.contains("TARGET_ID_MISSING")
        assert catalog.contains("MATCH_KEY_MISSING")
        assert catalog.contains("INVALID_INT")
        assert catalog.contains("INVALID_EMAIL")
        assert catalog.contains("INVALID_BOOLEAN")

    def test_accessors_do_not_reload_yaml_after_construction(self, monkeypatch, tmp_path):
        artifacts = load_yaml_dataset_artifacts("employees")
        spec = YamlDatasetSpec(artifacts)

        def _unexpected(*args, **kwargs):
            raise AssertionError("runtime accessor must not call YAML loaders after construction")

        monkeypatch.setattr("connector.datasets.yaml_spec_loader.load_mapping_spec_for_dataset", _unexpected)
        monkeypatch.setattr("connector.datasets.yaml_spec_loader.load_normalize_spec_for_dataset", _unexpected)
        monkeypatch.setattr("connector.datasets.yaml_spec_loader.load_enrich_spec_for_dataset", _unexpected)
        monkeypatch.setattr("connector.datasets.yaml_spec_loader.load_match_spec_for_dataset", _unexpected)
        monkeypatch.setattr("connector.datasets.yaml_spec_loader.load_resolve_spec_for_dataset", _unexpected)
        monkeypatch.setattr("connector.datasets.yaml_spec_loader.load_sink_spec_for_dataset", _unexpected)
        monkeypatch.setattr("connector.datasets.yaml_spec_loader.load_source_spec_for_dataset", _unexpected)
        monkeypatch.setenv("EMPLOYEES_SOURCE_PATH", str(tmp_path / "employees.csv"))

        assert isinstance(spec.build_spec_for("map"), MappingSpec)
        assert spec.get_apply_adapter().operation_alias == "users.upsert"
        source = spec.build_record_source()
        assert source.has_header is True
        assert source.delimiter == ","
        assert source.encoding == "utf-8-sig"


class TestRegistryValidation:
    def test_validate_registry_eagerly_validates_yaml_datasets(self, monkeypatch):
        monkeypatch.setattr(
            registry_module,
            "load_registry",
            lambda: {"datasets": {"employees": {"mapping": "employees.mapping.yaml"}}},
        )

        def _boom(dataset_name: str):
            raise ValueError(f"invalid dataset snapshot: {dataset_name}")

        monkeypatch.setattr(registry_module, "_registry", None)
        monkeypatch.setattr("connector.datasets.yaml_spec_loader.load_yaml_dataset_artifacts", _boom)

        with pytest.raises(ValueError, match="invalid dataset snapshot: employees"):
            validate_registry()
