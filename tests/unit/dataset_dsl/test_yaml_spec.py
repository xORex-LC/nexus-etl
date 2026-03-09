"""Tests for YamlDatasetSpec and registry auto-discovery."""

from __future__ import annotations

import pytest

from connector.datasets.registry import get_spec, list_specs
from connector.datasets.spec import UnsupportedStageError
from connector.datasets.yaml_spec import YamlDatasetSpec
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
