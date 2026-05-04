"""Tests for SinkDrivenPayloadBuilder."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from connector.domain.dataset_dsl.payload_compiler import SinkDrivenPayloadBuilder
from connector.domain.transform_dsl.specs import SinkSpec


def _make_sink_spec(fields: list[dict], system_fields: list[dict] | None = None) -> SinkSpec:
    return SinkSpec.model_validate({
        "dataset": "test",
        "sink": {
            "fields": fields,
            "system_fields": system_fields or [],
        },
    })


class TestSinkSerializeSpecValidation:
    def test_bool_field_accepts_native_serialize(self):
        spec = _make_sink_spec([
            {
                "name": "active",
                "type": "bool",
                "required": True,
                "serialize": {"as": "native"},
            },
        ])

        field = spec.sink.fields[0]
        assert field.serialize is not None
        assert field.serialize.as_mode == "native"
        assert field.serialize.map is None

    def test_bool_field_accepts_literal_map(self):
        spec = _make_sink_spec([
            {
                "name": "active",
                "type": "bool",
                "required": True,
                "serialize": {
                    "as": "literal_map",
                    "map": {"true": 1, "false": 0},
                },
            },
        ])

        field = spec.sink.fields[0]
        assert field.serialize is not None
        assert field.serialize.map is not None
        assert field.serialize.map.true == 1
        assert field.serialize.map.false == 0

    def test_bool_field_literal_map_normalizes_yaml_bool_keys(self):
        spec = _make_sink_spec([
            {
                "name": "active",
                "type": "bool",
                "required": True,
                "serialize": {
                    "as": "literal_map",
                    "map": {True: "yes", False: "no"},
                },
            },
        ])

        field = spec.sink.fields[0]
        assert field.serialize is not None
        assert field.serialize.map is not None
        assert field.serialize.map.true == "yes"
        assert field.serialize.map.false == "no"

    def test_literal_map_requires_true_and_false(self):
        with pytest.raises(ValidationError, match="Field required"):
            _make_sink_spec([
                {
                    "name": "active",
                    "type": "bool",
                    "required": True,
                    "serialize": {
                        "as": "literal_map",
                        "map": {"true": 1},
                    },
                },
            ])

    def test_literal_map_is_invalid_for_non_bool_field(self):
        with pytest.raises(ValidationError, match="currently supported only for bool fields"):
            _make_sink_spec([
                {
                    "name": "status_code",
                    "type": "int",
                    "required": True,
                    "serialize": {
                        "as": "literal_map",
                        "map": {"true": 1, "false": 0},
                    },
                },
            ])

    def test_system_field_must_not_declare_serialize(self):
        with pytest.raises(ValidationError, match="must not declare serialize metadata"):
            _make_sink_spec(
                fields=[{"name": "email", "type": "string", "required": True}],
                system_fields=[
                    {
                        "name": "target_id",
                        "type": "string",
                        "required": True,
                        "generated": True,
                        "serialize": {"as": "native"},
                    },
                ],
            )


class TestSinkDrivenPayloadBuilder:
    def test_basic_mapping(self):
        spec = _make_sink_spec([
            {"name": "first_name", "type": "string", "required": True, "target": "firstName"},
        ])
        builder = SinkDrivenPayloadBuilder(spec)
        result = builder({"first_name": "John"})
        assert result == {"firstName": "John"}

    def test_no_target_uses_name(self):
        spec = _make_sink_spec([
            {"name": "email", "type": "string", "required": True},
        ])
        builder = SinkDrivenPayloadBuilder(spec)
        result = builder({"email": "a@b.com"})
        assert result == {"email": "a@b.com"}

    def test_bool_coercion(self):
        spec = _make_sink_spec([
            {"name": "active", "type": "bool", "required": True, "target": "isActive"},
        ])
        builder = SinkDrivenPayloadBuilder(spec)
        assert builder({"active": "true"}) == {"isActive": True}
        assert builder({"active": "false"}) == {"isActive": False}
        assert builder({"active": 1}) == {"isActive": True}
        assert builder({"active": 0}) == {"isActive": False}

    def test_bool_serialize_native_keeps_canonical_bool(self):
        spec = _make_sink_spec([
            {
                "name": "active",
                "type": "bool",
                "required": True,
                "target": "isActive",
                "serialize": {"as": "native"},
            },
        ])
        builder = SinkDrivenPayloadBuilder(spec)
        source = {"active": True}

        result = builder(source)

        assert result == {"isActive": True}
        assert source["active"] is True

    def test_bool_serialize_literal_map_applies_only_at_payload_boundary(self):
        spec = _make_sink_spec([
            {
                "name": "active",
                "type": "bool",
                "required": True,
                "target": "isActive",
                "serialize": {
                    "as": "literal_map",
                    "map": {"true": 1, "false": 0},
                },
            },
        ])
        builder = SinkDrivenPayloadBuilder(spec)
        source = {"active": True}

        result = builder(source)

        assert result == {"isActive": 1}
        assert source["active"] is True

    def test_bool_serialize_literal_map_uses_false_branch(self):
        spec = _make_sink_spec([
            {
                "name": "active",
                "type": "bool",
                "required": True,
                "target": "isActive",
                "serialize": {
                    "as": "literal_map",
                    "map": {"true": "yes", "false": "no"},
                },
            },
        ])
        builder = SinkDrivenPayloadBuilder(spec)

        result = builder({"active": False})

        assert result == {"isActive": "no"}

    def test_int_coercion(self):
        spec = _make_sink_spec([
            {"name": "org_id", "type": "int", "required": True, "nullable": True, "target": "organizationId"},
        ])
        builder = SinkDrivenPayloadBuilder(spec)
        assert builder({"org_id": "42"}) == {"organizationId": 42}
        assert builder({"org_id": None}) == {"organizationId": None}

    def test_required_validation(self):
        spec = _make_sink_spec([
            {"name": "email", "type": "string", "required": True},
        ])
        builder = SinkDrivenPayloadBuilder(spec)
        with pytest.raises(ValueError, match="Missing required fields"):
            builder({"email": ""})
        with pytest.raises(ValueError, match="Missing required fields"):
            builder({"email": None})

    def test_nullable_required_allows_none(self):
        spec = _make_sink_spec([
            {"name": "mgr", "type": "int", "required": True, "nullable": True},
        ])
        builder = SinkDrivenPayloadBuilder(spec)
        result = builder({"mgr": None})
        assert result == {"mgr": None}

    def test_conditional_field_excluded_when_empty(self):
        spec = _make_sink_spec([
            {"name": "password", "type": "string", "required": True, "target": "password"},
        ])
        builder = SinkDrivenPayloadBuilder(spec, conditional_fields=["password"])
        assert builder({"password": ""}) == {}
        assert builder({"password": None}) == {}
        assert builder({"password": "secret"}) == {"password": "secret"}

    def test_defaults_injected(self):
        spec = _make_sink_spec([
            {"name": "email", "type": "string", "required": True},
        ])
        builder = SinkDrivenPayloadBuilder(spec, defaults={"extra": 42})
        result = builder({"email": "a@b.com"})
        assert result == {"email": "a@b.com", "extra": 42}

    def test_defaults_override_field(self):
        """Fields whose target key appears in defaults are excluded from field processing."""
        spec = _make_sink_spec([
            {"name": "avatar_id", "type": "string", "required": True, "nullable": True, "target": "avatarId"},
            {"name": "email", "type": "string", "required": True, "target": "mail"},
        ])
        builder = SinkDrivenPayloadBuilder(spec, defaults={"avatarId": None})
        result = builder({"email": "a@b.com"})
        assert result == {"mail": "a@b.com", "avatarId": None}

    def test_system_fields_excluded(self):
        spec = _make_sink_spec(
            fields=[{"name": "email", "type": "string", "required": True}],
            system_fields=[{"name": "target_id", "type": "string", "required": True, "generated": True}],
        )
        builder = SinkDrivenPayloadBuilder(spec)
        result = builder({"email": "a@b.com"})
        assert "target_id" not in result

