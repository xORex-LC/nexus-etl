from __future__ import annotations

import pytest

from connector.domain.dsl.engine import TransformationEngine
from connector.domain.dsl.ops import (
    op_at,
    op_capitalize,
    op_compact,
    op_contains_non_ascii,
    op_count,
    op_digits_only,
    op_filter_regex,
    op_first,
    op_format_mask,
    op_last,
    op_map_dict,
    op_parse_bool,
    op_pick_when_blank,
    op_random_digits,
    op_reject_regex,
    op_substring,
    op_title,
    op_to_bool,
    op_transliterate,
    op_unique,
)
from connector.domain.dsl.specs import OperationCall


def test_op_map_dict_casefold_handles_unhashable_mapping_values() -> None:
    mapping = {
        "admin": {"role": "ADMIN"},
        "user": {"role": "USER"},
    }

    result = op_map_dict("AdMiN", mapping=mapping, casefold=True)

    assert result == {"role": "ADMIN"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (["a", "b"], "a"),
        ([], None),
        ("a", "a"),
        (None, None),
    ],
)
def test_op_first_tolerant_contract(value, expected) -> None:
    assert op_first(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (["a", "b"], "b"),
        ([], None),
        ("a", "a"),
        (None, None),
    ],
)
def test_op_last_tolerant_contract(value, expected) -> None:
    assert op_last(value) == expected


def test_op_at_supports_sequences_and_scalar_zero_index() -> None:
    assert op_at(["a", "b", "c"], index=1) == "b"
    assert op_at(["a"], index=5) is None
    assert op_at("single", index=0) == "single"
    assert op_at("single", index=1) is None


def test_op_compact_removes_blank_values() -> None:
    result = op_compact([None, "", "  ", "x", 0, False])

    assert result == ["x", 0, False]


def test_op_compact_wraps_scalar_in_list() -> None:
    assert op_compact("value") == ["value"]
    assert op_compact("   ") == []
    assert op_compact(None) == []


def test_op_unique_preserves_order() -> None:
    result = op_unique(["a", "b", "a", "c", "b"])

    assert result == ["a", "b", "c"]


def test_op_count_uses_tolerant_list_contract() -> None:
    assert op_count(None) == 0
    assert op_count("value") == 1
    assert op_count(["a", "b"]) == 2


def test_op_filter_regex_keeps_matches() -> None:
    result = op_filter_regex(["org:1", "team", "org:2"], pattern=r"^org:")

    assert result == ["org:1", "org:2"]


def test_op_filter_regex_supports_fullmatch_and_flags() -> None:
    result = op_filter_regex(
        ["Admin", "USER", "guest"],
        pattern=r"admin|user",
        match_mode="fullmatch",
        flags=["ignorecase"],
    )

    assert result == ["Admin", "USER"]


def test_op_reject_regex_excludes_matches() -> None:
    result = op_reject_regex(["org:1", "team", "org:2"], pattern=r"^org:")

    assert result == ["team"]


def test_op_title_and_capitalize_transform_case() -> None:
    assert op_title("иванов иван") == "Иванов Иван"
    assert op_capitalize("иванов иван") == "Иванов иван"


def test_op_transliterate_returns_ascii_and_preserves_ascii_input() -> None:
    assert op_transliterate("Ivan") == "Ivan"
    assert op_transliterate("Иван") == "Ivan"
    assert op_transliterate(None) is None
    assert op_transliterate("") == ""


def test_op_substring_extracts_slice_without_failing_on_bounds() -> None:
    assert op_substring("Ivan", start=0, length=1) == "I"
    assert op_substring("Ivan", start=2) == "an"
    assert op_substring("Ivan", start=10, length=2) == ""


def test_op_substring_rejects_negative_length() -> None:
    with pytest.raises(ValueError, match="length must be >= 0"):
        op_substring("Ivan", start=0, length=-1)


def test_op_contains_non_ascii_is_predicate_only() -> None:
    assert op_contains_non_ascii("Ivan") is False
    assert op_contains_non_ascii("Иван") is True
    assert op_contains_non_ascii(None) is None


def test_op_to_bool_remains_strict() -> None:
    assert op_to_bool("true") is True
    assert op_to_bool("false") is False
    with pytest.raises(ValueError, match="Invalid boolean value"):
        op_to_bool("1")


def test_op_parse_bool_is_declarative_and_distinct_from_to_bool() -> None:
    args = {
        "true_values": ["true", "1", "yes", "y"],
        "false_values": ["false", "0", "no", "n"],
        "casefold": True,
        "trim": True,
    }

    assert op_parse_bool(" YES ", **args) is True
    assert op_parse_bool("0", **args) is False
    assert op_parse_bool(None, **args) is None


def test_op_parse_bool_rejects_overlapping_literal_sets() -> None:
    with pytest.raises(ValueError, match="must not overlap"):
        op_parse_bool(
            "x",
            true_values=["x"],
            false_values=["x"],
        )


def test_op_parse_bool_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="Invalid boolean value"):
        op_parse_bool(
            "maybe",
            true_values=["yes"],
            false_values=["no"],
        )


def test_op_digits_only_extracts_digits() -> None:
    assert op_digits_only("+7 (999) 123-45-67") == "79991234567"
    assert op_digits_only("abc") is None


def test_op_random_digits_returns_exact_digit_string() -> None:
    result = op_random_digits(None, length=8)

    assert len(result) == 8
    assert result.isdigit()


def test_op_random_digits_rejects_non_positive_length() -> None:
    with pytest.raises(ValueError, match="length must be > 0"):
        op_random_digits(None, length=0)


def test_op_pick_when_blank_returns_value_only_for_blank_guard() -> None:
    assert op_pick_when_blank([None, "secret"], guard_index=0, value_index=1) == "secret"
    assert op_pick_when_blank(["existing", "secret"], guard_index=0, value_index=1) is None
    assert op_pick_when_blank(["", "secret"], guard_index=0, value_index=1) == "secret"


def test_op_format_mask_formats_canonical_input() -> None:
    result = op_format_mask("79991234567", mask="+# (###) ###-##-##")

    assert result == "+7 (999) 123-45-67"


def test_op_format_mask_requires_exact_length() -> None:
    with pytest.raises(ValueError, match="mask expects 11 characters, got 3"):
        op_format_mask("123", mask="+# (###) ###-##-##")


def test_map_each_applies_nested_pipeline() -> None:
    engine = TransformationEngine.with_core_ops()

    result = engine.apply(
        " admin ; user ; ",
        [
            OperationCall(op="split", args={"sep": ";"}),
            OperationCall(
                op="map_each",
                args={
                    "ops": [
                        {"op": "trim", "args": {}},
                        {"op": "upper", "args": {}},
                    ]
                },
            ),
            OperationCall(op="compact", args={}),
        ],
    )

    assert result.issues == ()
    assert result.value == ["ADMIN", "USER"]


def test_map_each_surfaces_nested_operation_failure() -> None:
    engine = TransformationEngine.with_core_ops()

    result = engine.apply(
        ["1", "oops"],
        [
            OperationCall(
                op="map_each",
                args={
                    "ops": [
                        {"op": "to_int", "args": {}},
                    ]
                },
            ),
        ],
    )

    assert len(result.issues) == 1
    assert result.issues[0].code == "DSL_OP_FAILED"
    assert result.issues[0].details["op"] == "map_each"


def test_register_core_ops_exposes_new_stage_one_operations() -> None:
    engine = TransformationEngine.with_core_ops()

    for name in {
        "first",
        "last",
        "at",
        "substring",
        "compact",
        "unique",
        "count",
        "map_each",
        "transliterate",
        "contains_non_ascii",
        "filter_regex",
        "reject_regex",
        "title",
        "capitalize",
        "parse_bool",
        "digits_only",
        "random_digits",
        "format_mask",
    }:
        assert engine.registry.get(name) is not None
