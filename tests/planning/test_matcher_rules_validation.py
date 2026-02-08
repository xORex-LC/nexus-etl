from __future__ import annotations

import pytest

from connector.domain.transform.matcher.rules import FuzzyScoringRules


def test_fuzzy_rules_default_is_valid():
    rules = FuzzyScoringRules()
    assert rules.accept_threshold == 0.90
    assert rules.review_threshold == 0.70


@pytest.mark.parametrize(
    ("kwargs", "error_part"),
    [
        ({"accept_threshold": -0.1}, "accept_threshold"),
        ({"accept_threshold": 1.1}, "accept_threshold"),
        ({"review_threshold": -0.1}, "review_threshold"),
        ({"review_threshold": 1.1}, "review_threshold"),
        ({"accept_threshold": 0.5, "review_threshold": 0.6}, "review_threshold"),
        ({"tie_delta": -0.01}, "tie_delta"),
        ({"max_candidates": 0}, "max_candidates"),
        ({"top_k": 0}, "top_k"),
        ({"score_round": -1}, "score_round"),
        ({"weights": {"email": -1.0}}, "weights"),
        ({"weights": {"email": float("nan")}}, "weights"),
    ],
)
def test_fuzzy_rules_invalid_config_raises(kwargs: dict[str, object], error_part: str):
    with pytest.raises(ValueError, match=error_part):
        FuzzyScoringRules(**kwargs)
