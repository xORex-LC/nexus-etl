from __future__ import annotations

import pytest

from connector.config.config import _parse_bool, _parse_float, _parse_int, _parse_str


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("true", True),
        ("yes", True),
        ("0", False),
        ("false", False),
        ("no", False),
        (1, True),
        (0, False),
    ],
)
def test_parse_bool_supported_values(raw, expected):
    assert _parse_bool(raw, source="test", field_name="flag", optional=False) is expected


def test_parse_int_rejects_bool():
    with pytest.raises(ValueError):
        _parse_int(True, source="test", field_name="retries", optional=False)


def test_parse_float_accepts_numbers_and_strings():
    assert _parse_float(10, source="test", field_name="timeout_seconds", optional=False) == 10.0
    assert _parse_float("10.5", source="test", field_name="timeout_seconds", optional=False) == 10.5


def test_parse_str_optional_none_preserved():
    assert _parse_str(None, source="test", field_name="ca_file", optional=True) is None
