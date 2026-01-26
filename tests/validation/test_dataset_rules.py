from connector.domain.transform.normalizer import Normalizer
from connector.domain.validation.deps import DatasetValidationState, ValidationDependencies
from connector.domain.validation.dataset_rules import MatchKeyUniqueRule, OrgExistsRule, UsrOrgTabUniqueRule
from connector.domain.validation.pipeline import TypedRowValidator
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
from connector.datasets.employees.source_mapper import EmployeesSourceMapper
from connector.datasets.employees.mapping_spec import EmployeesMappingSpec
from connector.datasets.employees.normalizer_spec import EmployeesNormalizerSpec
from connector.datasets.employees.record_sources import NORMALIZED_COLUMNS


def _to_canonical_keys(values: dict[str, object]) -> dict[str, object]:
    return {
        "email": values.get("email"),
        "last_name": values.get("lastName"),
        "first_name": values.get("firstName"),
        "middle_name": values.get("middleName"),
        "is_logon_disable": values.get("isLogonDisable"),
        "user_name": values.get("userName"),
        "phone": values.get("phone"),
        "password": values.get("password"),
        "personnel_number": values.get("personnelNumber"),
        "manager_id": values.get("managerId"),
        "organization_id": values.get("organization_id"),
        "position": values.get("position"),
        "avatar_id": values.get("avatarId"),
        "usr_org_tab_num": values.get("usrOrgTabNum"),
    }


def _collect(values: list[str | None], line_no: int = 1) -> TransformResult[None]:
    mapped = dict(zip(NORMALIZED_COLUMNS, values))
    record = SourceRecord(
        line_no=line_no,
        record_id=f"line:{line_no}",
        values=_to_canonical_keys(mapped),
    )
    return TransformResult(
        record=record,
        row=None,
        row_ref=None,
        match_key=None,
        errors=[],
        warnings=[],
    )

class DummyOrgLookup:
    def __init__(self, existing_ids: set[int]):
        self.existing_ids = existing_ids

    def get_org_by_id(self, ouid: int):
        return {"_ouid": ouid} if ouid in self.existing_ids else None

def make_employee(values: list[str | None]):
    mapping_spec = EmployeesMappingSpec()
    normalizer = Normalizer(EmployeesNormalizerSpec())
    entity, result = TypedRowValidator(
        normalizer, EmployeesSourceMapper(mapping_spec), mapping_spec.required_fields
    ).validate(_collect(values, line_no=1))
    return entity, result

def test_match_key_unique_rule_detects_duplicate():
    state = DatasetValidationState(matchkey_seen={}, usr_org_tab_seen={})
    deps = ValidationDependencies()
    rule = MatchKeyUniqueRule()

    employee, result = make_employee(
        [
            "user@example.com",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe",
            "+111",
            "secret",
            "100",
            "",
            "20",
            "Engineer",
            "",
            "TAB-100",
        ]
    )
    rule.apply(employee, result, state, deps)
    # avatarId правило делает строку невалидной, но это не мешает проверять rule
    assert any(e.code == "INVALID_AVATAR_ID" for e in result.errors)

    # второй с тем же match_key
    employee2, result2 = make_employee(
        [
            "user2@example.com",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe2",
            "+222",
            "secret",
            "100",
            "",
            "20",
            "Engineer",
            "",
            "TAB-200",
        ]
    )
    rule.apply(employee2, result2, state, deps)
    assert not result2.valid
    assert any(e.code == "DUPLICATE_MATCHKEY" for e in result2.errors)

def test_usr_org_tab_unique_rule_detects_duplicate():
    state = DatasetValidationState(matchkey_seen={}, usr_org_tab_seen={})
    deps = ValidationDependencies()
    rule = UsrOrgTabUniqueRule()

    employee, result = make_employee(
        [
            "user@example.com",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe",
            "+111",
            "secret",
            "100",
            "",
            "20",
            "Engineer",
            "",
            "TAB-100",
        ]
    )
    rule.apply(employee, result, state, deps)
    assert any(e.code == "INVALID_AVATAR_ID" for e in result.errors)

    employee2, result2 = make_employee(
        [
            "user2@example.com",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe2",
            "+222",
            "secret",
            "200",
            "",
            "20",
            "Engineer",
            "",
            "TAB-100",  # duplicate
        ]
    )
    rule.apply(employee2, result2, state, deps)
    assert not result2.valid
    assert any(e.code == "DUPLICATE_USR_ORG_TAB_NUM" for e in result2.errors)

def test_org_exists_rule_checks_lookup():
    state = DatasetValidationState(matchkey_seen={}, usr_org_tab_seen={})
    deps = ValidationDependencies(org_lookup=DummyOrgLookup(existing_ids={20}))
    rule = OrgExistsRule()

    employee, result = make_employee(
        [
            "user@example.com",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe",
            "+111",
            "secret",
            "100",
            "",
            "20",  # exists
            "Engineer",
            "",
            "TAB-100",
        ]
    )
    rule.apply(employee, result, state, deps)
    assert any(e.code == "INVALID_AVATAR_ID" for e in result.errors)

    employee2, result2 = make_employee(
        [
            "user2@example.com",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe2",
            "+222",
            "secret",
            "200",
            "",
            "999",  # missing
            "Engineer",
            "",
            "TAB-200",
        ]
    )
    rule.apply(employee2, result2, state, deps)
    assert not result2.valid
    assert any(e.code == "ORG_NOT_FOUND" for e in result2.errors)
