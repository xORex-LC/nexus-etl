from __future__ import annotations

from connector.domain.dsl.ops import op_map_dict


def test_op_map_dict_casefold_handles_unhashable_mapping_values() -> None:
    mapping = {
        "admin": {"role": "ADMIN"},
        "user": {"role": "USER"},
    }

    result = op_map_dict("AdMiN", mapping=mapping, casefold=True)

    assert result == {"role": "ADMIN"}
