"""Golden contract tests for employees payload behavior in DEC-009."""

from __future__ import annotations

import pytest

from connector.datasets.registry import get_spec
from connector.domain.planning.plan_models import PlanItem


def _employees_source(**overrides):
    source = {
        "email": "u@example.com",
        "last_name": "Last",
        "first_name": "First",
        "middle_name": "Middle",
        "is_logon_disable": False,
        "user_name": "user",
        "phone": "+1",
        "password": "secret",
        "personnel_number": "10",
        "manager_id": None,
        "organization_id": "5",
        "position": "Engineer",
        "usr_org_tab_num": "TAB-10",
    }
    source.update(overrides)
    return source


class TestEmployeesPayloadContract:
    @pytest.fixture()
    def builder(self):
        return get_spec("employees").get_apply_adapter().payload_builder

    def test_happy_path_payload_matches_expected_contract(self, builder):
        payload = builder(_employees_source())

        assert payload == {
            "mail": "u@example.com",
            "lastName": "Last",
            "firstName": "First",
            "middleName": "Middle",
            "isLogonDisabled": False,
            "userName": "user",
            "phone": "+1",
            "password": "secret",
            "personnelNumber": "10",
            "managerId": None,
            "organization_id": 5,
            "position": "Engineer",
            "avatarId": None,
            "usrOrgTabNum": "TAB-10",
        }

    def test_password_is_omitted_when_empty(self, builder):
        payload = builder(_employees_source(password=""))

        assert "password" not in payload
        assert payload["avatarId"] is None

    def test_avatar_id_default_is_always_present(self, builder):
        payload = builder(_employees_source(password=None))

        assert payload["avatarId"] is None

    def test_nullable_payload_fields_are_present_with_null(self, builder):
        payload = builder(_employees_source(email=None, phone=None, position=None))

        assert payload["mail"] is None
        assert payload["phone"] is None
        assert payload["position"] is None
        assert payload["avatarId"] is None

    def test_manager_id_nullable_int_contract(self, builder):
        payload = builder(_employees_source(manager_id="42"))
        assert payload["managerId"] == 42

        payload = builder(_employees_source(manager_id=""))
        assert payload["managerId"] is None

    def test_organization_id_is_coerced_to_int(self, builder):
        payload = builder(_employees_source(organization_id="7"))

        assert payload["organization_id"] == 7

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("true", True),
            ("false", False),
            ("1", True),
            ("0", False),
            ("yes", True),
            ("no", False),
            (1, True),
            (0, False),
        ],
    )
    def test_boolean_coercion_variants(self, builder, value, expected):
        payload = builder(_employees_source(is_logon_disable=value))

        assert payload["isLogonDisabled"] is expected

    def test_invalid_boolean_raises_value_error(self, builder):
        with pytest.raises(ValueError, match="Invalid boolean value"):
            builder(_employees_source(is_logon_disable="maybe"))

    def test_missing_required_fields_raise_value_error(self, builder):
        with pytest.raises(ValueError, match="Missing required fields"):
            builder(_employees_source(email=None, user_name=None))

    def test_apply_adapter_builds_request_with_expected_payload(self):
        adapter = get_spec("employees").get_apply_adapter()
        item = PlanItem(
            row_id="line:1",
            line_no=1,
            op="create",
            target_id="abc",
            desired_state=_employees_source(password=""),
            changes={},
            source_ref={"match_key": "MK-1"},
        )

        spec = adapter.to_request(item)

        assert spec.operation_alias == "users.upsert"
        assert spec.operation_params == {"target_id": "abc"}
        assert spec.payload == {
            "mail": "u@example.com",
            "lastName": "Last",
            "firstName": "First",
            "middleName": "Middle",
            "isLogonDisabled": False,
            "userName": "user",
            "phone": "+1",
            "personnelNumber": "10",
            "managerId": None,
            "organization_id": 5,
            "position": "Engineer",
            "avatarId": None,
            "usrOrgTabNum": "TAB-10",
        }
