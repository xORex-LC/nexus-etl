"""Tests for dataset_dsl Pydantic specs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from connector.domain.dataset_dsl.specs import (
    ApplyAdapterSpec,
    DatasetDslSpec,
    DiagnosticEntrySpec,
    PayloadSpec,
    ParamsSpec,
    ReportAdapterSpec,
)


class TestReportAdapterSpec:
    def test_valid(self):
        spec = ReportAdapterSpec(
            identity_label="match_key",
            conflict_code="MATCH_CONFLICT",
            conflict_field="matchKey",
        )
        assert spec.identity_label == "match_key"
        assert spec.conflict_code == "MATCH_CONFLICT"
        assert spec.conflict_field == "matchKey"

    def test_missing_field_raises(self):
        with pytest.raises(ValidationError):
            ReportAdapterSpec(identity_label="x", conflict_code="y")

    def test_extra_field_forbidden(self):
        with pytest.raises(ValidationError):
            ReportAdapterSpec(
                identity_label="x",
                conflict_code="y",
                conflict_field="z",
                unknown="bad",
            )


class TestPayloadSpec:
    def test_defaults(self):
        spec = PayloadSpec()
        assert spec.source == "sink"
        assert spec.defaults == {}
        assert spec.conditional_fields == []

    def test_with_values(self):
        spec = PayloadSpec(
            source="sink",
            defaults={"avatarId": None},
            conditional_fields=["password"],
        )
        assert spec.defaults == {"avatarId": None}
        assert spec.conditional_fields == ["password"]


class TestParamsSpec:
    def test_default_mode(self):
        spec = ParamsSpec()
        assert spec.mode == "target_id"

    def test_none_mode(self):
        spec = ParamsSpec(mode="none")
        assert spec.mode == "none"

    def test_invalid_mode(self):
        with pytest.raises(ValidationError):
            ParamsSpec(mode="bad_mode")


class TestApplyAdapterSpec:
    def test_minimal(self):
        spec = ApplyAdapterSpec(operation_alias="users.upsert")
        assert spec.operation_alias == "users.upsert"
        assert spec.payload.source == "sink"
        assert spec.params.mode == "target_id"


class TestDiagnosticEntrySpec:
    def test_valid(self):
        spec = DiagnosticEntrySpec(
            code="INVALID_EMAIL",
            system_code="DATA_INVALID",
            severity="error",
            message="bad email",
        )
        assert spec.code == "INVALID_EMAIL"
        assert spec.message == "bad email"

    def test_message_default(self):
        spec = DiagnosticEntrySpec(
            code="X", system_code="Y", severity="error",
        )
        assert spec.message == ""


class TestDatasetDslSpec:
    def test_full(self):
        spec = DatasetDslSpec(
            report=ReportAdapterSpec(
                identity_label="mk",
                conflict_code="CC",
                conflict_field="cf",
            ),
            apply=ApplyAdapterSpec(operation_alias="op.do"),
            diagnostics=[
                DiagnosticEntrySpec(
                    code="E1", system_code="DATA_INVALID", severity="error",
                ),
            ],
        )
        assert spec.report.identity_label == "mk"
        assert spec.apply.operation_alias == "op.do"
        assert len(spec.diagnostics) == 1

    def test_diagnostics_default_empty(self):
        spec = DatasetDslSpec(
            report=ReportAdapterSpec(
                identity_label="mk", conflict_code="CC", conflict_field="cf",
            ),
            apply=ApplyAdapterSpec(operation_alias="op.do"),
        )
        assert spec.diagnostics == []

    def test_missing_report_raises(self):
        with pytest.raises(ValidationError):
            DatasetDslSpec(apply=ApplyAdapterSpec(operation_alias="op.do"))

    def test_missing_apply_raises(self):
        with pytest.raises(ValidationError):
            DatasetDslSpec(
                report=ReportAdapterSpec(
                    identity_label="mk", conflict_code="CC", conflict_field="cf",
                ),
            )
