from connector.models import CsvRow
from connector.validation.deps import DatasetValidationState, ValidationDependencies
from connector.validation.dataset_rules import MatchKeyUniqueRule, OrgExistsRule, UsrOrgTabUniqueRule
from connector.validation.pipeline import RowValidator
from connector.validation.row_rules import FIELD_RULES

class DummyOrgLookup:
    def __init__(self, existing_ids: set[int]):
        self.existing_ids = existing_ids

    def get_org_by_id(self, ouid: int):
        return {"_ouid": ouid} if ouid in self.existing_ids else None

def make_employee(values: list[str | None]):
    row = CsvRow(file_line_no=1, data_line_no=1, values=values)
    employee, result = RowValidator(FIELD_RULES).validate(row)
    return employee, result

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
